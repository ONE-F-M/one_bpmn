# Agent Tool Authoring Standard

**Status:** Authoritative. This document defines how Server Scripts that back
**Agent Tools** (shapes inside an AI Agent Task's ad-hoc "Tools" sub-process)
must be written, and how they differ from ordinary **Script Task** scripts.
Logix's `tool_writer` sub-agent generates to this standard; the
`script_writer` / `script_reviewer` sub-prompts carry both contracts.

## Why two contracts exist

The same Server Script DocType backs two different execution paths with
**different namespaces**:

| | Script Task | Agent Tool |
|---|---|---|
| Runner | `FrappeScriptEngine._run_frappe_server_script` — `one_bpmn/one_bpmn/engine.py` | `_run_server_script` — `one_bpmn/agents/shape_tools.py` |
| exec form | `exec(script, exec_ns)` — **one** merged namespace | `exec(script, exec_globals, local_vars)` — **separate** globals/locals |
| Task object | the real SpiffWorkflow task | `_synthetic_task(bpmn_id, kwargs)` — `data` is **only** the arguments the LLM passed |
| Workflow variables | spread as top-level names **and** bundled in `task_data` | **absent** — there is no `task_data` at all |
| Helper `def`s | work (single namespace) | **NameError** — a top-level `def`'s `__globals__` is `exec_globals`, which never contains the injected locals |

Neither runner is "wrong"; they are different by design of the synthetic-task
mechanism. If they are ever aligned (single namespace + `task_data` in
shape_tools), half of this standard can be deleted — until then, scripts must
be written to the contract of the path that will execute them.

## The Agent Tool contract

### What a tool receives (top-level names, injected as exec locals)

- **The LLM's arguments** — every key of the `kwargs` the model passed when
  calling the tool appears as a top-level name (via `_synthetic_task`, whose
  `data` is `dict(kwargs)`). A tool with no `aiToolParams` schema is called
  with **zero arguments** — do not read names you did not declare.
- `frappe` — the real Frappe module (also present in exec globals).
- `context_doctype` / `context_docname` — strings identifying the BPMN
  Process Instance's context document (for Logix chat: the Chat Conversation).
- `doc` — the context document, already loaded (`frappe._dict()` if there is
  no context or loading failed — never assume fields exist).
- `result` — an empty dict. **Write every output here.**

### What a tool does NOT receive

- **No workflow variables.** The synthetic task's `data` holds only the LLM's
  kwargs. Nothing produced by earlier process steps is visible.
- **No `task_data`.** Reading it raises `NameError`. A script that calls
  `task_data.get(...)` was written against the wrong contract.

### How a tool returns

Write a **flat dict of JSON-serialisable values** onto `result`
(`result["key"] = value`). After the script runs, `result` is merged into the
synthetic task's data and serialised to JSON as the tool result the LLM reads
(`shape_tools.execute_shape`). Deep nesting, documents, or non-serialisable
objects will break or bloat the tool result.

### Constraints (hard rules)

1. **Straight-line code only.** No helper `def`s, no `lambda`s that close over
   top-level names. The split globals/locals exec means any function body that
   references an injected name (or another top-level name) dies with
   `NameError` at call time — a bug invisible until the LLM calls the tool.
2. **Never raise for expected failures.** An uncaught exception aborts the
   tool call and surfaces as a broken turn. Catch expected errors and report
   them in the result instead: `result["error"] = "..."` — the LLM can then
   recover or rephrase. (`frappe.throw` is for Script Tasks, where the engine
   handles it; in a tool it is just an exception.)
3. **Security gate applies unchanged.** `frappe.set_user(...)` and
   `frappe.flags.ignore_permissions` are rejected by
   `_check_script_permissions` before exec; the AST validator
   (`one_bpmn/security/script_validator.py`) additionally bans dangerous
   builtins/imports/attributes at save time. Tools run under the initiating
   user's permissions.
4. **No bare `return`** — same as every Server Script (top-level code).
5. **Keep it lean.** No unused imports, no dead assignments; the deterministic
   optimizer (`logix_tools.optimize_script`) strips them, but write clean code
   to begin with.

### The turn-state bridge (`context_docname`) — the wrapper is CORRECT

Because a tool sees only the LLM's kwargs, **the only way to reach the turn's
real data** (user text, chat history, element context, prior stage outputs) is
through per-turn state keyed by the context document:

```python
# Logix – example stage tool (this pattern is the standard, NOT an anti-pattern)
from one_bpmn.agents.turn_state import get_turn, update_turn

turn = get_turn(context_docname)          # the bridge to real per-turn state
user_text = turn.get("user_text", "")
# ... do the work ...
update_turn(context_docname, draft=output)  # hand state to the next tool
result["ok"] = True                          # flat summary for the LLM
```

Thin wrappers that delegate to pre-deployed module code
(`from one_bpmn... import helper` at top level, then straight-line calls) are
likewise **correct** — module functions carry their own `__globals__`, so the
split-namespace problem does not apply to them. Do not "fix" this pattern into
inline logic with helper `def`s; that is the actual bug.

### Worked example — a well-formed Agent Tool

```python
# Count open tasks for a project the LLM names (tool arg: project_name).
project = frappe.db.get_value("Project", {"project_name": project_name}, "name")
if not project:
    result["found"] = False
    result["error"] = f"No project named {project_name}"
else:
    open_tasks = frappe.db.count("Task", {"project": project, "status": "Open"})
    result["found"] = True
    result["project"] = project
    result["open_tasks"] = open_tasks
```

Note: `project_name` is a top-level name because the LLM passed it as an
argument (declared via `spiffworkflow:aiToolParams` on the shape). Errors are
reported in `result`, not raised. Output is a flat dict.

## The Script Task contract (for contrast)

- Workflow variables arrive **both** as top-level names and inside
  `task_data` (a dict copy) — `task_data.get("var", default)` is the safe read.
- `doc`, `context_doctype`, `context_docname`, `result`, `frappe` are injected
  exactly as for tools.
- Single exec namespace: helper `def`s and cross-referencing top-level code
  work fine (though Logix still avoids them for simplicity).
- `frappe.throw(...)` is the correct abort for validation failures — the
  engine logs and handles it.
- Outputs go to `result` and are merged back into the workflow for later
  steps and gateway conditions.

## How Logix detects which contract applies

- The editor (`spiff/src/views/Editor.vue`, `extractProcessContext`) inspects
  the element's parent: inside a `bpmn:AdHocSubProcess` →
  `shape_kind: "agent_tool"`, otherwise `shape_kind: "script_task"`. The value
  rides in `process_context` unchanged to `process_logix_message`.
- The backend normalises: `process_logix_message` re-derives `shape_kind`
  from `parent_type` when present, so a stale or missing client label cannot
  mislabel the contract.
- `classify_intent` routes: `shape_kind == "agent_tool"` →
  `write_agent_tool` (the `tool_writer` sub-agent, specialist path);
  otherwise → `write_script`. Both drafts pass through `review_script`, whose
  prompt knows both contracts and rewrites wrong-contract drafts before save.

## What the reviewer must catch (wrong-contract signatures)

- An **agent tool** reading `task_data` or any workflow variable.
- An **agent tool** containing a helper `def`/`lambda` that references a
  top-level name (NameError under split namespaces).
- An **agent tool** raising for expected failures instead of reporting via
  `result`.
- A **script task** reading undeclared LLM-style kwargs, or writing outputs
  anywhere but `result`.
- Either kind using `frappe.form_dict` / `frappe.response` (never valid).

These are **shape rules, not security rules** — they live in the reviewer
prompt, never in `logix_tools.validate_script`, whose refusal message
("unable to generate a safe script") would mislabel a wrong-shaped script as
unsafe.
