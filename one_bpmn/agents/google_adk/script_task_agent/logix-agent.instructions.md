---
applyTo:
  - "one_bpmn/agents/google_adk/script_task_agent/**"
  - "one_bpmn/security/**"
  - "one_bpmn/tools/tool_for_server_scripts.py"
  - "spiff/src/components/LogixChat.vue"
---

# Logix AI Assistant

Logix is an AI assistant embedded in the Processa BPMN editor. It helps users write and modify
Frappe API-type Server Scripts attached to BPMN Script Tasks. It is powered by Google ADK
(`LlmAgent`, `Runner`, `InMemorySessionService`) and uses `gemini-2.0-flash` by default.

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

## Script Contracts (non-negotiable — see `docs/agent-tool-authoring-standard.md`)

There are TWO contracts, selected by `shape_kind` in `process_context`:

**script_task** — runs INSIDE the SpiffWorkflow engine
(`FrappeScriptEngine._run_frappe_server_script` in `one_bpmn/one_bpmn/engine.py`), **not** inside an
HTTP request, in ONE merged exec namespace. `frappe.form_dict` is always empty and `frappe.response`
is ignored. The engine injects `doc`, `context_doctype`, `context_docname`, `task_data`, `result`,
and `frappe`; generated scripts must use them:

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

- **Pass 1 — AST scan**: walks `ast.Import` and `ast.ImportFrom` nodes; blocks anything in `FORBIDDEN_MODULES`
  (os, sys, subprocess, socket, requests, pickle, ctypes, inspect, pathlib, and others).
- **Pass 2 — Regex scan**: blocks `open()`, `eval()`, `exec()`, `__import__()`, `compile()`,
  `globals()`, `locals()`, `vars()`, `__builtins__`, MRO traversal, and destructive `frappe.db.sql`
  (DROP / TRUNCATE / ALTER / CREATE TABLE).
- Returns `{"valid": bool, "violations": [...]}`.
- On failure: violations are logged via `frappe.log_error(title="Logix Security Validator", ...)`,
  then injected back into the writer prompt via `_build_regeneration_prompt()`.
- Maximum 3 attempts total. On exhaustion, return a user-facing error — never expose the violation list.

## ADK Tools (`tools/tool_for_server_scripts.py`)

Four tools are registered on the writer/clarifier agents:

| Function | Purpose |
|---|---|
| `get_server_script_content(script_name)` | Read an existing script's Python source |
| `get_server_script_meta(script_name)` | Read type, doctype, event, method, disabled flag |
| `list_api_server_scripts()` | List all enabled API-type scripts |
| `get_doctype_fields(doctype)` | List field names and types for a DocType |

All tools return strings (JSON or plain text). They never raise — errors are embedded in the return value.

## Agent Configuration

- Credentials: read from `AI Chat Settings` DocType (`google_vertex_ai_api_key`, `gemini_model`).
- Sub-prompt overrides: loaded from `AI Agent Configuration` via `get_agent_config(AGENT_ID)`.
  Key names: `intent_classifier`, `clarifier`, `script_writer`, `script_reviewer`, `test_writer`,
  `tool_writer` (optional specialist — Agent Tool authoring standard).
- `AGENT_ID = "logix_agent"`. Falls back to hardcoded `_DEFAULT_*_INSTRUCTION` strings if config is absent.

## Return Shape

`run_logix_message()` always returns a dict with these keys:

```python
{
    "intent":          "CREATE" | "MODIFY" | "DISAMBIGUATE",
    "response":        str,           # agent text shown to user
    "diff":            str | None,    # unified diff (MODIFY only)
    "original_script": str | None,    # original code (MODIFY only)
    "modified_script": str | None,    # new code (CREATE or MODIFY)
    "options":         list | None,   # MCQ choices (DISAMBIGUATE only)
    "suggested_name":  str | None,    # pre-fills Apply dialog (CREATE only)
}
```

## API Endpoints (`api.py`)

| Endpoint | Purpose |
|---|---|
| `process_logix_message()` | Main entry — fetches `original_content` then calls `run_logix_message()` |
| `create_server_script()` | Creates new Server Script; always sets `api_method`; returns `{name, api_method, api_url}` |
| `update_server_script(script_name, script)` | Saves modified script body; same permission elevation as create |
| `check_server_script_exists(script_name)` | Returns `{"exists": bool}` |

All endpoints use `frappe.session.user = "Administrator"` elevation (scripts require System Manager).

## Frontend (`LogixChat.vue`)

- `elementLabel` must be a `computed()` — never a static IIFE — so it updates when the user switches Script Tasks.
- A `watch([props.element?.id, props.currentScript], ...)` resets `messages` and re-runs `initGreeting()` on task switch.
- `initGreeting()` has three cases:
  1. Script linked → "redefining" greeting.
  2. No script, label matches existing Server Script → notification + Link / Create buttons.
  3. No script, no match → "defining [label]" greeting.
- `parseSplitDiff(unifiedDiff)` returns `[{type, left, right}]` rows for side-by-side rendering.
  A `-` line immediately followed by `+` is a `changed` pair; standalone `-` is `deleted`; standalone `+` is `added`.
- After `approve_create` / `approve_modify` succeeds, show the `api_url` from the response in a confirmation message.
- The Apply Script button is hidden on messages with `CREATE` or `MODIFY` intent (approval is via Approve button instead).
- Context variables available to the writer (injected by the BPMN engine): `doc`, `context_doctype`, `context_docname`, `task_data`, `result`, `frappe`. Never `frappe.form_dict` / `frappe.response` — they don't work in the script-task runtime.

## Review Checklist

- `validate_script()` must be called on every writer output before the result is returned.
- `_run_agent()` may return `None` (no final event). All callers must guard against `None`.
- `run_logix_message()` is synchronous (`asyncio.run()`). Never call it from inside an already-running event loop.
- `InMemorySessionService` sessions must be deleted in the `finally` block of `process_message()`.
- Never log the full generated script at INFO level — only log on security violations via `frappe.log_error`.
