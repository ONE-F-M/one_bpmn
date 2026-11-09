# AGENTS.md: the AI agent runtime

Rules for `one_bpmn/agents/`, the engine pieces that run agents, and the two editor assistants, Logix and ProsAlly. The frontend half of both assistants is in [`spiff/AGENTS.md`](../../spiff/AGENTS.md).

## How an agent runs

- An agent is an AI Agent Configuration plus a process map. Its stages are DB Server Scripts called as Agent Tools by an AI Agent Task in that map. Prompts and stage scripts are seeded and changed by patches in `one_bpmn/one_bpmn/patches/`, not edited in Python files.
- Every chat turn goes through one endpoint, `one_bpmn.api.agui.stream_agent_turn`, with the agent's `agent_id` and its fields in the turn `context`. Per-agent context builders (for example `build_prosally_turn_context` in `api/server_script_api.py`) add what a map needs.
- Each stage gets a fresh prompt built from the conversation history; stages share no session state.
- `get_agent_config(agent_id)` in the AI Agent Configuration controller returns an agent's settings and sub-prompt overrides.

## LLM providers (`processa_engine/agent_runtime/`)

Adapters: `llm_gemini.py` (`GeminiAdapter`), `llm_anthropic.py` (`AnthropicAdapter`), `llm_openai.py` (`OpenAIAdapter`), all behind `BaseLLMAdapter` in `llm_base.py`. The data shapes they and the step loop pass around (`ToolSpec`, `StepResult`, `TurnRecord`, `CompletionResult` and others) are in `llm_types.py`.

`llm_factory.py: get_llm_adapter_from_settings(agent_config)` resolves the adapter:

1. The agent's linked AI Provider and its AI Model. The AI Model holds the key and the API model name; a disabled AI Model is refused.
2. Otherwise `default_llm_provider` on Processa Settings, with credentials from the matching AI Provider record.

To add a provider, add an adapter class and its branch in `get_llm_adapter()`.

## Conversations (`ai_agent_conversations/chat_persistence.py`)

- `Chat Conversation`, `Chat Message` and `Chat Participant` are one_bpmn DocTypes.
- Helpers: `create_conversation`, `create_agent_conversation`, `save_user_message`, `save_bot_message`, `load_history` (owner-only), `close_conversation`.
- Per-conversation step state (`get_or_create_state`, `update_state`) lives in the Redis cache, not in a DocType.

## Generated scripts

### Two contracts

The shape a script backs decides how it runs (`shape_kind` in the turn context).

**script_task**: runs inside the SpiffWorkflow engine (`FrappeScriptEngine` in `one_bpmn/processa_engine/engine/`), not inside an HTTP request, in one merged exec namespace.

- Injected: `doc`, `context_doctype`, `context_docname`, `task_data`, `result`, `frappe`. Do not redefine them.
- Read inputs from `doc` and `task_data`; write outputs to `result`, which the engine merges into the task data for later steps and gateways.
- `frappe.form_dict` is always empty and `frappe.response` is ignored.
- No bare `return`: Server Scripts run as top-level code. Branch with `if`/`else` and abort with `frappe.throw()`.
- The Server Script record's `script_type` (`API`, `DocType Event`, `Scheduler Event`, `Permission Query`) decides how the record is stored, not what is injected.

**agent_tool**: backs a shape inside an AI Agent Task's ad-hoc Tools sub-process, run by `_run_server_script` in `shape_tools.py` with split exec globals and locals.

- Injected: the calling model's arguments as top-level names (declared by `spiffworkflow:aiToolParams`), plus `frappe`, `context_doctype`, `context_docname`, `doc`, `result`.
- No workflow variables: reading `task_data` raises NameError.
- Straight-line code only. An inline `def` or `lambda` that reads a top-level name fails under split namespaces; imported functions are fine.
- Report expected failures as `result["error"] = "..."` so the model can recover; do not raise.
- `result` must be a flat, JSON-serializable dict.
- The turn-state bridge (`get_turn(context_docname)`, `update_turn(...)`) is the right way to reach per-turn state; keep those thin wrappers.

### Security validator (`one_bpmn/ai_agent_security/code_checks/script_validator.py`)

`validate_script(code)` gates every generated script and returns `{"valid": bool, "violations": [...]}`.

- Pass 1, AST: blocks imports in `FORBIDDEN_MODULES` (os, sys, subprocess, socket, requests, pickle, ctypes, inspect, pathlib and others).
- Pass 2, patterns: blocks `open()`, `eval()`, `exec()`, `__import__()`, `compile()`, `globals()`, `locals()`, `vars()`, `__builtins__`, MRO traversal, and destructive `frappe.db.sql` (DROP, TRUNCATE, ALTER, CREATE TABLE).
- A rejected script is regenerated with its violations fed back into the writer prompt. The violation list is logged with `frappe.log_error` and never shown to the user.
- Never log a full generated script at INFO level.

## Logix

Logix writes and fixes Server Scripts for Script Tasks and Agent Tools in the editor. `AGENT_ID = "logix_agent"`.

- Stages: an intent classifier routes to a clarifier (asks one question, writes no code), a script writer (`script_task`), a tool writer (`agent_tool`), or a debugger. A reviewer checks the writer's output, then `validate_script` gates it. `classify_intent` returns `next` as `clarify`, `write_script`, `write_agent_tool` or `debug_script`.
- Debug path: "Logix – Build Context" puts `script_text` (a pasted script, else the linked script's code) and `last_error` (a pasted traceback, else the newest `BPMN ScriptTask: "<script>" execution failed` Error Log) on the turn through `ai_agent_registry/definitions/logix/helpers.py:debug_inputs`. The `debug_script` tool returns an explanation and a fixed script; the reviewer judges only the unified diff, and `validate_script` gates the fix. A passing fix replies as a MODIFY with the diff; a failing one explains the issues and offers no code.
- Sub-prompt keys on the AI Agent Configuration: `intent_classifier`, `clarifier`, `script_writer`, `script_reviewer`, `test_writer`, `tool_writer`, `script_debugger`.
- Read tools in `ai_agent_registry/definitions/logix/tools.py` and `definitions/shared/tools.py` (for example `get_server_script_content`, `get_server_script_meta`, `list_api_server_scripts`, `get_doctype_fields`) return strings and never raise: the `tool_envelope` decorator in `definitions/shared/helpers.py` logs the error and returns the error value.
- Script endpoints in `api/server_script_api.py`: `create_server_script` (upsert), `update_server_script`, `check_server_script_exists`. They check Server Script permission or the System Manager role before writing.

## ProsAlly

ProsAlly generates, redraws and modifies BPMN diagrams from natural language. `agent_id = "prosally_agent"`.

- It never changes a diagram without the user's confirmation. A confirmed action comes back as `confirmed_action`, which must be one of the known action intents before anything acts on it.
- `current_xml` (the canvas sent with a modify) is untrusted input; never execute it.
- The stages are DB Server Scripts driven by the ProsAlly process map. The one Python stage is `compile_ir` in `ai_agent_registry/definitions/prosally/tools_pipeline.py`, which turns the model's intermediate representation into BPMN XML.
- Generated XML must satisfy the error-level bpmnlint rules in `spiff/src/bpmn/lint/bpmnlintrc.js`: one start event and one end event, every element connected, and a BPMNShape or BPMNEdge for every element. Existing element ids are never renamed in a modify, and new elements get unique ids.
- Positions are placeholders; the frontend lays the diagram out (see `spiff/AGENTS.md`).
