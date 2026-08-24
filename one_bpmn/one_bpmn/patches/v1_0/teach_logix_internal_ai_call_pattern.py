import frappe

_SCRIPT_TASK_BULLETS_OLD = """- `result` — an empty dict, ALREADY defined. Write every output onto it (`result["key"] = value`). The engine merges `result` back into the workflow so later steps and gateways can read those keys.
- `frappe` — the usual Frappe ORM."""

_SCRIPT_TASK_BULLETS_NEW = """- `result` — an empty dict, ALREADY defined. Write every output onto it (`result["key"] = value`). The engine merges `result` back into the workflow so later steps and gateways can read those keys.
- `frappe` — the usual Frappe ORM.
- `instance` — the BPMN Process Instance controller. Only needed for the internal-AI-call pattern below; ignore it otherwise.
- `bpmn_id` — this shape's own id (a string). Only needed for the internal-AI-call pattern below."""

_SCRIPT_TASK_AI_CALL_SECTION = """
**Making your OWN internal AI Agent call — tracked as a real AI Agent Run (script_task)**
Sometimes a script_task must call an LLM as part of its own logic — not because some other AI Agent Task activated this shape, but because THIS script needs an answer from a model before deciding what to do next (e.g. classify something, then branch on the result). Call the shared dispatcher via `execute_shape(instance, bpmn_id, task_cfg, kwargs)` — `instance` and `bpmn_id` are already injected (see the variable list above). This is automatically tracked as a real, observable AI Agent Run, exactly like a real AI Agent Task shape on the diagram — no extra wiring needed.

```python
from one_bpmn.agents.shape_tools import execute_shape
import json

_task_cfg = {
    "serviceType": "ai_agent",
    "aiAgentConfig": "<name of an existing AI Agent Configuration>",
    "aiUserPrompt": "{{ prompt_text }}",
    "aiBackend": "direct_api",
    "aiResponseFormat": "text",
    "aiTimeout": 30,
    "aiMaxRetries": 2,
}
_raw = execute_shape(instance, bpmn_id, _task_cfg, {"prompt_text": "Summarise: " + str(doc.description or "")})
_reply = json.loads(_raw).get(bpmn_id + "_output", "") or ""
result["summary"] = _reply
```

Rules for this pattern:
- NEVER put dynamic or user-supplied text directly inside the `aiUserPrompt` string itself. Always pass it through the last argument (a plain dict) and reference it with a bare `{{ variable_name }}` placeholder — Jinja substitutes the VALUE verbatim and never re-parses it as more template syntax. Embedding raw text as the template string is unsafe if that text ever contains `{{ }}`.
- `aiAgentConfig` must name a REAL, existing `AI Agent Configuration` record. If you are not certain of the exact name, use a lookup tool first — never invent one.
- The reply comes back namespaced under `bpmn_id + "_output"` (also `_error_code` / `_error_message` on failure, `_token_usage`). Always read that exact key, not a bare `"output"`.
- Reach for this pattern ONLY when the LLM call must be wrapped in surrounding deterministic logic (validate the answer, branch on it, retry it, combine it with other data). If the user just wants "an AI step in the process" with no such wrapping, tell them a real AI Agent Task shape on the diagram is simpler and needs no script at all.
"""

_AGENT_TOOL_BULLETS_OLD = """- `doc` — that context document, already loaded (may be an empty stub — never assume fields exist).
- `result` — an empty dict. Write every output onto it."""

_AGENT_TOOL_BULLETS_NEW = """- `doc` — that context document, already loaded (may be an empty stub — never assume fields exist).
- `result` — an empty dict. Write every output onto it.
- `instance` — the BPMN Process Instance controller. Only needed for the internal-AI-call pattern below; ignore it otherwise.
- `bpmn_id` — this tool's own shape id (a string). Only needed for the internal-AI-call pattern below."""

_AGENT_TOOL_AI_CALL_SECTION = """
**Making your OWN internal AI Agent call — tracked as a real AI Agent Run (agent_tool)**
A tool can itself call an LLM as part of its own logic — not the agent's tool-calling loop, but a SECOND, nested AI call this tool's own code makes before it returns (e.g. score or rewrite the caller's argument before answering). Call the shared dispatcher via `execute_shape(instance, bpmn_id, task_cfg, kwargs)` — `instance` and `bpmn_id` are already injected. This is automatically tracked as a real, observable AI Agent Run, and its result is also auto-saved to this turn's state under `bpmn_id + "_result"` — no extra code needed to pass it to a later stage tool.

```python
from one_bpmn.agents.shape_tools import execute_shape
import json

_task_cfg = {
    "serviceType": "ai_agent",
    "aiAgentConfig": "<name of an existing AI Agent Configuration>",
    "aiUserPrompt": "{{ prompt_text }}",
    "aiBackend": "direct_api",
    "aiResponseFormat": "text",
    "aiTimeout": 30,
    "aiMaxRetries": 2,
}
_raw = execute_shape(instance, bpmn_id, _task_cfg, {"prompt_text": "Rewrite politely: " + str(draft_text)})
_reply = json.loads(_raw).get(bpmn_id + "_output", "") or ""
result["rewritten"] = _reply
```

Rules for this pattern:
- NEVER put dynamic or caller-supplied text directly inside the `aiUserPrompt` string itself. Pass it through the last argument (a plain dict) and reference it with a bare `{{ variable_name }}` placeholder — Jinja substitutes the VALUE verbatim and never re-parses it as more template syntax.
- `aiAgentConfig` must name a REAL, existing `AI Agent Configuration` record — use a lookup tool first if unsure; never invent one.
- The reply comes back namespaced under `bpmn_id + "_output"` (also `_error_code` / `_error_message` on failure). Always read that exact key.
- Reach for this ONLY when the LLM call needs surrounding deterministic logic this tool's own code provides. A tool that just relays a plain prompt to a model with nothing else going on is usually better modelled as a real AI Agent Task the outer agent can call directly, not a script wrapping another script.
"""


def execute():
	_patch(
		"Logix – Script Writer",
		_SCRIPT_TASK_BULLETS_OLD,
		_SCRIPT_TASK_BULLETS_NEW,
		insert_before="**Worked example — agent_tool",
		insert_text=_SCRIPT_TASK_AI_CALL_SECTION,
	)
	_patch(
		"Logix – Tool Writer (Agent Tools)",
		_AGENT_TOOL_BULLETS_OLD,
		_AGENT_TOOL_BULLETS_NEW,
		insert_before="**Worked example — a well-formed agent tool",
		insert_text=_AGENT_TOOL_AI_CALL_SECTION,
	)


def _patch(config_name, bullets_old, bullets_new, insert_before, insert_text):
	doc = frappe.get_doc("AI Agent Configuration", config_name)
	prompt = doc.system_prompt

	if insert_text.strip() in prompt:
		return  # already applied

	if bullets_old not in prompt:
		frappe.throw(f"Bullet list anchor not found in '{config_name}' — prompt may have changed.")
	prompt = prompt.replace(bullets_old, bullets_new, 1)

	if insert_before not in prompt:
		frappe.throw(f"Insertion anchor '{insert_before}' not found in '{config_name}' — prompt may have changed.")
	prompt = prompt.replace(insert_before, insert_text.strip() + "\n\n" + insert_before, 1)

	doc.system_prompt = prompt
	doc.save(ignore_permissions=True)
	frappe.db.commit()
