# AGENTS.md

This repository holds `one_bpmn` (Processa), a Frappe v15 app for BPMN process modelling and execution: a Python backend with a SpiffWorkflow engine, and a Vue and bpmn-js editor under `spiff/`.

These are the only instructions coding agents read. Folder-specific rules live in nested files:

- [`one_bpmn/agents/AGENTS.md`](one_bpmn/agents/AGENTS.md): the AI agent runtime, Logix and ProsAlly.
- [`spiff/AGENTS.md`](spiff/AGENTS.md): the Vue frontend and the bpmn-js extensions.

House style lives in `frappe-bench/.claude/rules/`: `house-style.md` always, `python-frappe.md` for Python, `vue-js.md` for JavaScript and Vue. The numbered rule set (A1 to F8) is `frappe-bench/.claude/rules/RULES.md`; cite an id when a PR body justifies an exception. Before you say a task is done, re-read your diff against `house-style.md`.

## Stack

- Frappe v15, Python 3.10 or later (`requires-python` in `pyproject.toml`).
- SpiffWorkflow for BPMN execution and serialization.
- Vue 3, Vite, frappe-ui, TailwindCSS and bpmn-js in `spiff/`. Node.js 20, Yarn.
- The editor is served at `/processa` from `one_bpmn/www/processa/`.

## Repository layout

- `one_bpmn/api/`: whitelisted endpoints, one module per domain:
  - `process_map_api.py`: process model and Process CRUD (save, import, list, rename, delete).
  - `deploy.py`: the deploy, disable, activate and deactivate endpoints; the work is in `processa_engine/compiler/`.
  - `instance_api.py`: instance lifecycle and task actions (start, complete, send message, list).
  - `editability.py`: cross-site editability checks and editor lock heartbeats.
  - `server_script_api.py`: Server Script CRUD and the Logix and ProsAlly turn-context builders.
  - `agui.py`: `stream_agent_turn`, the one chat endpoint every agent uses.
  - `canvas_comments.py`, `notification_api.py`, `version_history.py`, `script_version_history.py`, `utils.py`.
- `one_bpmn/one_bpmn/doctype/`: DocType JSON, controllers and tests.
- `one_bpmn/processa_engine/engine/`: the SpiffWorkflow script engine.
- `one_bpmn/processa_engine/`: engine services: `triggers.py` (document events), `timers.py` (timer and stranded-step jobs), `assignment.py`, `task_selector.py`, `call_activities.py` and `audit.py` (workflow state changes), and `compiler/` (deploy checks and the compile step).
- `one_bpmn/one_bpmn/connectors/`: outbound connectors and the agent sandbox client.
- `one_bpmn/agents/`: the AI agent runtime. See its `AGENTS.md`.
- `one_bpmn/security/`: the generated-script validator.
- `one_bpmn/processa_engine/notifications/`: AMP and HTML task emails and their tokens; `one_bpmn/api/email_actions.py` holds the endpoints the emails call. See its `README.md`.
- `one_bpmn/commands/`: bench commands.
- `one_bpmn/overrides/`: overridden Frappe classes, such as the scheduler queue for timer jobs.
- `one_bpmn/templates/`: email and deployment templates.
- `one_bpmn/hooks.py`: app hooks, the universal document-event trigger, scheduler events and fixtures.
- `one_bpmn/tasks.py`: scheduled A2A polling, conversation, memory and model jobs.
- `spiff/`: the Vue frontend. See its `AGENTS.md`.
- `docs/`: operations notes and retros.

## Data model

- `BPMN Process Model`: BPMN XML, the serialized SpiffWorkflow spec, subprocess specs, version, active flag and its parent Process. Only one model per Process is active.
- `BPMN Process Instance`: one execution. Status is `Queued`, `Active`, `Completed`, `Errored`, `Cancelled` or `Suspended`. Treat instance state as business-critical.
- `BPMN Active Task`: a task slot on an instance. Status is `Waiting`, `Completed`, `Errored` or `Cancelled`.
- `BPMN Activity Log`: the audit trail of task transitions.

Do not add a status without checking the DocType JSON and every consumer.

## SpiffWorkflow and the engine

- Keep BPMN XML valid; invalid XML breaks both the editor and the engine.
- Keep serialized specs compatible with existing records. A map edit takes effect on new instances only after `compile_process_model`.
- Treat subprocess, timer, message and signal behaviour as engine logic, not UI data.
- Re-running a step must not repeat its side effects.
- Handle SpiffWorkflow exceptions explicitly; never catch them silently.
- Changes to the engine, the scheduler, timers, signals or permission checks need focused review, because they affect live instances.

## Backend rules

- Every endpoint: `@frappe.whitelist()`, a type on every parameter, a docstring, and a permission check before work (`frappe.has_permission`, `frappe.only_for` or `doc.check_permission()`).
- Use the ORM or `frappe.qb`; no raw SQL.
- Use `frappe.throw(_(...))` for user-facing errors.
- Use `frappe.db.exists()` for existence checks, not try/except.
- Return stable dict and list shapes; the Vue app reads them directly. Change a response shape and its caller in `spiff/src/` together.
- Never return tracebacks, private fields or file paths.
- Name only endpoints that exist; search for `@frappe.whitelist()` before documenting or calling one.
- Ruff enforces tabs, double quotes and a 110-character line.

## Code review focus

Much of this code was generated, so review for what can be deleted: dead code, unused imports and variables, unreachable branches, wrappers that only delegate, one-use abstractions, and comments that restate the code. Prefer a built-in or library call over a hand-written helper.

## Working on an AI agent story

Settle two things before designing anything, because changing either later is a rebuild:

1. **Which kind of agent is it?** `agent_type` on AI Agent Configuration is `Chat` or `Background`. A Chat agent needs a `chat_mode_label`, a conversation loop in its map, and faces the go-live gate. A Background agent is started by a record insert (an `A2A Task` for a delegated worker), reads its brief from that record and writes its answer back to it.
2. **How is it invoked?** A chat surface, an orchestrator delegating over A2A, a record trigger, or a step inside a larger process. This decides the start event and so the map.

Ask for both if the story does not say.

Read the live examples before inventing a pattern. The BA site (see the BA Sync block on Processa Settings) runs working agents for most shapes, including a delegating orchestrator, four delegated specialists and the chat agents. Copy a map that already runs. The layout conventions come from those maps: lane at y=180, 100x80 tasks 130 apart, 50x50 gateways, and a 550x240 ad-hoc Tools sub-process under the agent task.

When copying a map, set `process_name` before `is_active`. A copy inherits its source's Process, and activating it deactivates the map it was copied from.

## Testing

```bash
bench --site <site> run-tests --app one_bpmn --failfast
```

- Tests inherit `frappe.tests.utils.FrappeTestCase`; plain pytest classes report "Ran 0 tests" under `bench run-tests`.
- Shared tests go in `one_bpmn/tests/`; DocType tests sit next to their DocType.
- Keep fixture BPMN XML small. When you touch them, cover sequential flow, gateways, subprocesses, timers, signals, cancellation and restart.
- Assert state transitions, not file existence. Test both the happy path and the validation failure, and assert permission checks on write and delete paths.

## Branches and commits

- One branch per work item, named after it (for example `WI-000768`). The PR targets the branch the work item names.
- Conventional commit subjects with the work item id: `feat(WI-000768): ...`, `fix(WI-000771): ...`. The Semantic Commits check requires this form.
- Keep a branch to its work item. A documentation change touches no CI or runtime file.
- Open PRs only through `scripts/claude-pr.sh`; see `CLAUDE.md`.
