---
applyTo:
  - "one_bpmn/agents/shape_tools.py"
  - "one_bpmn/agents/llm_provider/**"
  - "one_bpmn/one_bpmn/engine.py"
  - "one_bpmn/security/**"
  - "one_bpmn/tools/tool_for_server_scripts.py"
  - "one_bpmn/utils/chat_persistence.py"
  - "spiff/src/components/LogixCanvas.vue"
  - "spiff/src/components/LogixChat.vue"
---

# Logix AI Assistant

Logix is an AI assistant embedded in the Processa BPMN editor. It helps users write and modify
Frappe Server Scripts attached to BPMN Script Tasks. It is provider-agnostic — the active LLM
is selected via `AI Chat Settings → Processa LLM Provider` (Anthropic, Gemini, or OpenAI).

## Architecture: Sub-Agent Pipeline

```
User message  (process_context carries shape_kind: script_task | agent_tool)
  └─► IntentClassifier  →  CREATE | MODIFY | DISAMBIGUATE   (+ shape_kind routing)
         ├─ DISAMBIGUATE → Clarifier            (asks one clarifying question, writes no code)
         ├─ CREATE/MODIFY + script_task → ScriptWriter        (general dual-contract writer)
         └─ CREATE/MODIFY + agent_tool  → ToolWriter          (specialist — Agent Tool standard)
                              └─► ScriptReviewer   (receives "Shape kind: X" preamble; knows both contracts)
                                    └─► validate_script()  ← security gate  → optimize_script()
                                          ├─ valid   → return final script + diff (MODIFY)
                                          └─ invalid → _build_regeneration_prompt() → retry (max 3)
```

At runtime the pipeline stages are inlined DB Server Scripts ("Logix – Tool ...") called as
Agent Tools by the "Run Logix Agent" AI Agent Task in the "Logix – Script Task Agent" process
model. `classify_intent` returns `next` = `clarify` | `write_script` | `write_agent_tool`.

Each pipeline step is a separate `_run()` call via the active `BaseLLMAdapter`. Steps do not share
session state — each call receives a fresh prompt built from conversation history.

## LLM Provider Abstraction (`agents/llm_provider/`)

Logix is decoupled from any specific LLM vendor via `BaseLLMAdapter`:

| File | Class | Provider |
|---|---|---|
| `gemini.py` | `GeminiAdapter` | Google Gemini (`google.genai`) |
| `anthropic_adapter.py` | `AnthropicAdapter` | Anthropic Claude (`anthropic`) |
| `openai_adapter.py` | `OpenAIAdapter` | OpenAI (`openai`) |

`factory.py → get_llm_adapter_from_settings()` resolves the active provider in this priority order:

1. `AI Agent Configuration → llm_provider_override` (per-agent)
2. `AI Chat Settings → processa_llm_provider` (global for all BPMN agents)
3. `AI Chat Settings → llm_provider` (chatbot fallback)
4. `"gemini"` (hard fallback)

To add a new provider: create a new adapter class, add one branch in `get_llm_adapter()`.

## Script Contracts (non-negotiable)

There are TWO contracts, selected by `shape_kind` in `process_context`:

**script_task** — BPMN Script Tasks run INSIDE the SpiffWorkflow engine
(`FrappeScriptEngine._run_frappe_server_script` in `one_bpmn/one_bpmn/engine.py`), **not** inside an
HTTP request, in ONE merged exec namespace. `frappe.form_dict` is always empty and `frappe.response`
is ignored. The engine injects `doc`, `context_doctype`, `context_docname`, `task_data`, `result`, and
`frappe` as local variables; generated scripts must use them:

```python
# Injected by the engine: doc, context_doctype, context_docname, task_data, result, frappe.

# Read the context document directly (or frappe.get_doc(context_doctype, context_docname)):
process_name = doc.process_name

# Read workflow variables produced by earlier steps:
threshold = task_data.get("threshold")

# ... business logic ...

# Write outputs onto the pre-defined `result` dict — the engine merges it back into
# task.data so downstream steps and gateways can read the keys:
result["approved"] = True
result["next_step"] = "manager_review"
```

- Never use `frappe.form_dict` (always empty here) or `frappe.response` (ignored). Read inputs from
  `doc` / `task_data`; write outputs onto `result`.
- `doc`, `context_doctype`, `context_docname`, `task_data`, and `result` DO exist — they are injected.
  Do not redefine them.
- The Server Script record's `script_type` defaults to `"API"`; all four Frappe types are supported
  (`API`, `DocType Event`, `Scheduler Event`, `Permission Query`), and the canvas settings panel
  exposes the correct sub-fields for each. This governs how the record is stored/configured, not the
  runtime injection above.
- Never use bare `return` — Server Scripts run as top-level code, so `return` is a SyntaxError.
  Use `if/else` for branching and `frappe.throw()` to abort.

**agent_tool** — backs a shape inside an AI Agent Task's ad-hoc Tools sub-process, executed by
`_run_server_script` in `one_bpmn/agents/shape_tools.py` against a synthetic task with SPLIT exec
globals/locals. Injected: the calling LLM's arguments as top-level names (declared via
`spiffworkflow:aiToolParams`), plus `frappe`, `context_doctype`, `context_docname`, `doc`, `result`.

- NO workflow variables and NO `task_data` — reading `task_data` raises NameError.
- STRAIGHT-LINE code only — an inline helper `def`/`lambda` referencing a top-level name dies with
  NameError under split namespaces (imported module functions are fine).
- Never raise for expected failures — report via `result["error"] = "..."` so the LLM can recover.
- `result` must be a flat JSON-serialisable dict — it is serialised as the tool result the LLM reads.
- The turn-state bridge (`get_turn(context_docname)` / `update_turn(...)`) is the CORRECT pattern for
  reaching per-turn state — never "fix" thin wrappers into inline logic.

## Security Validator (`security/script_validator.py`)

All generated code passes through `validate_script(code)` before being returned to the user.

- **Pass 1 — AST scan**: walks `ast.Import` / `ast.ImportFrom` nodes; blocks anything in
  `FORBIDDEN_MODULES` (os, sys, subprocess, socket, requests, pickle, ctypes, inspect, pathlib, etc.).
- **Pass 2 — Regex scan**: blocks `open()`, `eval()`, `exec()`, `__import__()`, `compile()`,
  `globals()`, `locals()`, `vars()`, `__builtins__`, MRO traversal, and destructive
  `frappe.db.sql` (DROP / TRUNCATE / ALTER / CREATE TABLE).
- Returns `{"valid": bool, "violations": [...]}`.
- Non-code responses (greetings, clarifying questions) bypass validation — checked via
  regex for a ` ```python ``` ` block before calling the validator.
- On failure: logged via `frappe.log_error(title="Logix Security Validator — Auto-regenerating", ...)`
  with violations and the flagged code. The violations are injected into the next writer prompt via
  `_build_regeneration_prompt()` which instructs the agent to use safe Frappe ORM methods instead.
- On final attempt failure: logged as `"Logix Security Validator — Max retries reached"`.
  Returns a user-facing error — the violation list is never exposed to the user.
- Maximum 3 attempts total.

## Tools (`tools/tool_for_server_scripts.py`)

Four tools are available to the writer and clarifier agents:

| Function | Purpose |
|---|---|
| `get_server_script_content(script_name)` | Read an existing script's Python source |
| `get_server_script_meta(script_name)` | Read type, doctype, event, method, disabled flag |
| `list_api_server_scripts()` | List all enabled API-type scripts |
| `get_doctype_fields(doctype)` | List field names and types for a DocType |

All tools return strings (JSON or plain text). They never raise — errors are embedded in the return value.

## Agent Configuration

- Provider credentials: read from `AI Chat Settings` DocType. Key fields:
  `processa_llm_provider`, `anthropic_api_key`, `anthropic_model`, `gemini_api_key`,
  `google_vertex_ai_api_key`, `gemini_model`, `openai_api_key`, `openai_model`.
- Sub-prompt overrides: loaded from `AI Agent Configuration` via `get_agent_config(AGENT_ID)`.
  Key names: `intent_classifier`, `clarifier`, `script_writer`, `script_reviewer`, `test_writer`,
  `tool_writer` (optional specialist — Agent Tool authoring standard).
- `AGENT_ID = "logix_agent"`. Falls back to hardcoded `_DEFAULT_*_INSTRUCTION` strings if absent.

## Chat Persistence (`utils/chat_persistence.py`)

Conversations are persisted to three doctypes in `onefm_mcp`:

| Doctype | Purpose |
|---|---|
| `Chat Conversation` | One record per session; holds `agent_mode = "Logix"`, title, status |
| `Chat Message` | Individual messages; `sender` = user email or agent name (`"Logix"`), `receiver` = `"User"` or `"Logix"` |
| `Chat Conversation State` | JSON state blob per conversation |

Key helpers:

```python
create_conversation(agent_mode, title, user) -> str   # returns conversation name
save_user_message(conversation_name, text)             # sender=user, receiver="Logix"
save_bot_message(conversation_name, text, metadata)    # sender="Logix", receiver="User"
load_history(conversation_name, limit=30)              # returns [{"role", "content"}]
```

`process_logix_message()` creates a conversation on the first turn (when `conversation_name` is
`None`) and passes `conversation_name` back to the frontend for all subsequent turns. History is
always loaded fresh from the DB — the `chat_history` parameter is kept for backward compatibility
but ignored when `conversation_name` is provided.

## Return Shape

`run_logix_message()` always returns:

```python
{
    "intent":          "CREATE" | "MODIFY" | "DISAMBIGUATE",
    "response":        str,           # agent text shown to user
    "diff":            str | None,    # unified diff (MODIFY only)
    "original_script": str | None,    # original code (MODIFY only)
    "modified_script": str | None,    # new code (CREATE or MODIFY)
    "options":         list | None,   # MCQ choices (DISAMBIGUATE only)
    "suggested_name":  str | None,    # pre-fills script name (CREATE only)
}
```

## API Endpoints (`api.py`)

| Endpoint | Purpose |
|---|---|
| `process_logix_message(message, session_id, conversation_name, element_name, current_script)` | Main entry — loads history, calls agent, persists messages |
| `create_server_script(script_name, script_type, script, ...)` | Upserts Server Script; auto-derives `api_method` for API type |
| `update_server_script(script_name, script, ...)` | Updates script body and metadata |
| `check_server_script_exists(script_name)` | Returns `{"exists": bool}` |

All write endpoints use `frappe.set_user("Administrator")` elevation (Server Scripts require System Manager).

## Frontend (`LogixCanvas.vue`)

### Layout
- Modal: `min(92vw, 1520px)` wide (set via `:deep(.dialog-content:has(.lc-root))` override in `Editor.vue`).
- Chat panel: `580px` fixed width. Canvas panel takes remaining space.
- Diff viewer is wrapped in `.lc-split-scroll` (`overflow-x: auto`) so long lines scroll horizontally
  without clipping. Header and body scroll together.

### Greeting (`initGreeting()`)
Three cases on open:
1. Script already linked → `"How would you like me to assist in defining the **[script name]** server script?"`
2. No script linked, but a Server Script with the same name as the BPMN label exists →
   notification + **"Link to script task"** / **"Create new"** buttons.
3. No script, no match → `"How would you like me to assist in defining the **[label]** server script?"`

### Action Buttons by Intent

| Intent | Buttons |
|---|---|
| `CREATE` | **Approve** — applies code, sets script name, triggers auto-save + BPMN link |
| `MODIFY` | **Approve & Save** (purple) — applies changes + auto-save; **Reject** (red) — discards, leaves existing script unchanged |
| `DISAMBIGUATE` | One button per clarification option — clicks send the option as the next message |

The "Reject" button uses `.lc-action-btn--reject` (red border/hover).

### Auto-save
`scheduleAutoSave()` is called whenever `canvasCode` changes (including after Approve). It debounces
1500 ms then calls `saveScript()`, which:
1. Renames the DB record if `canvasScriptName` changed.
2. POSTs to `create_server_script` (upsert).
3. Fires `spiff.script.update` on `props.eventBus` to link the script to the BPMN element.
4. Sets `isDirty = false`, `isSaved = true` (resets after 3 s).

### Key Rules
- `elementLabel` must be a `computed()` — never a static IIFE — so it updates when the user switches tasks.
- A `watch` on `[props.element?.id, props.currentScript]` resets messages and re-runs `initGreeting()` on task switch.
- `parseSplitDiff(unifiedDiff)` returns `[{type, left, right}]` rows for side-by-side rendering.
  A `-` line immediately followed by `+` is a `changed` pair; standalone `-` is `deleted`; standalone `+` is `added`.
- Never show the security violation list to the user. Only the regeneration failure message is user-visible.

## Review Checklist

- `validate_script()` must be called on every writer output that contains a Python code block.
- `_run()` may return an empty string. All callers must guard against falsy output.
- `run_logix_message()` is async. Call it with `await` inside the agent; `api.py` runs it via `asyncio.run()`.
- Never log the full generated script at INFO level — only log on security violations via `frappe.log_error`.
- `conversation_name` must be returned in every `process_logix_message` response so the frontend can persist it for the next turn.
