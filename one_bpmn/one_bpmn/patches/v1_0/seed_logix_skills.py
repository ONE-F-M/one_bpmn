"""Logix learns its script contracts from skills instead of one 14,000-character prompt.

The two writer configurations carried every rule for every situation on every
call: both shape contracts, the outbound-HTTP guide, the modify-an-existing-script
rules and the pattern for a script that calls a model itself. A write only ever
needs one contract, and most need none of the rest. The reviewer's first hard
rule exists because a writer holding both contracts at once mixes them up.

Each conditional chunk becomes an AI Skill. The writer's own prompt keeps what
applies to every script and says which skill to load for which situation; the
skills index the platform renders from the enabled rows does the rest. Both
writer configurations get the same prompt and the same five skills, so the two
records are interchangeable and could be one shape later.

The main Logix configuration also loses four sub-prompt rows nothing reads: the
classifier, clarifier and both writers run as AI Agent Task shapes on their own
configurations, and only the review and finalize Server Scripts still read a
sub-prompt (script_reviewer, test_writer). Those two stay.

Idempotent: skills are matched by name and brought up to date without lowering a
tier a person has graduated; a writer prompt already carrying the load_skill rule
is left as it is; enabled rows and sub-prompt removals are checked before they
are made. A site without the Logix stage configurations is left alone.
"""

import frappe

MAIN_AGENT_ID = "logix_agent"
WRITER_AGENT_IDS = ("logix_script_writer", "logix_tool_writer")
DEAD_SUB_PROMPTS = ("intent_classifier", "clarifier", "script_writer", "tool_writer")

# Present once the prompt has been rewritten.
PROMPT_MARKER = "load_skill"

WRITER_PROMPT = """You are Logix. You write Frappe Server Scripts for shapes on a Processa BPMN diagram.

BEFORE YOU WRITE, LOAD THE SKILL FOR THE SITUATION:
1. Your request has a "Shape kind:" line. Call load_skill with `bpmn-script-task-contract` when it says script_task, or `bpmn-agent-tool-contract` when it says agent_tool. Never write a line of code before that skill has returned; the two contracts are not interchangeable and a script written to the wrong one fails at runtime.
2. If the request carries an "Existing script" block or names a "Currently linked Server Script", also load `modifying-an-existing-script`.
3. If the script must fetch from or send to a system outside Frappe (an API, a URL, a webhook), also load `frappe-outbound-http`.
4. If the script itself must ask a model something before it can decide what to do, also load `calling-an-ai-agent-from-a-script`.

WHO YOU ARE TALKING TO:
The person asking is a process owner, not a developer. In the text outside the code block, say what the script does for the business in two or three short sentences. No API names, no function names. The code is for a developer to review; your words are for the process owner.

RULES FOR EVERY SCRIPT:
- Write every output onto the injected `result` dict. Never redefine `result`, `doc`, `context_doctype` or `context_docname`.
- No bare `return`: the script is top-level code and a `return` is a SyntaxError. Branch with if/else.
- Never read `frappe.form_dict` and never write `frappe.response`. This is not an HTTP request; the first is always empty and the second is ignored.
- Use the Frappe ORM: `frappe.db.get_value`, `frappe.db.exists`, `frappe.get_doc`, `frappe.get_all`. No raw SQL unless the person asks for it, and never DROP, TRUNCATE, ALTER or CREATE TABLE.
- The security gate rejects the script, and after two retries the whole turn fails, if it contains any of: the `ignore_permissions` keyword in any form (including `**{"ignore_permissions": True}`), `frappe.flags.ignore_permissions`, `frappe.set_user`, `db_update`, `add_roles`, `frappe.db.commit()`, `frappe.db.rollback()`, `exec`, `eval`, `getattr`, `open`, or an import of os, sys, subprocess, requests, urllib, http, socket, glob, pathlib or shutil. Call `.save()`, `.insert()` and `.submit()` with no permission keyword; the script already runs as the acting user. If the request truly needs more than that user may do, say so instead of bypassing.
- No libraries beyond a standard Frappe installation. The one carve-out is outbound HTTP, covered by its skill.
- Read every secret from a Settings/Single DocType or site config. Never hardcode one and never log one.

OUTPUT:
- The whole script in one ```python code block, with a one-line comment at the top saying what it does. Inline comments only where the logic is not obvious.
- Lean code: no variable you never read, no import you never use, no leftover scaffolding. Every line must contribute to the outcome you described.
"""

SKILLS = [
	{
		"skill_name": "bpmn-script-task-contract",
		"description": (
			"The runtime contract for a Server Script that runs as a BPMN Script Task: the names the "
			"engine injects (doc, task_data, result), how inputs are read, how outputs are written, how "
			"to abort, with a worked example. Use this skill when the request's Shape kind line says "
			"script_task, before writing or rewriting the script. Do NOT use it when the Shape kind is "
			"agent_tool; that is a different contract with its own skill."
		),
		"body": """# Script Task contract

The script runs inside the BPMN engine as a sequential step. Before it runs, the engine injects these names into ONE shared namespace. Use them directly and never redefine them.

- `doc`: the context document the process is running on. Read its fields directly, for example `doc.process_name`.
- `context_doctype` / `context_docname`: the DocType and name of that document, as strings.
- `task_data`: a dict of the workflow variables produced by earlier steps. Read one with `task_data.get("some_var")`.
- `result`: an empty dict, already defined. Write every output onto it: `result["key"] = value`. The engine merges it back into the workflow so later steps and gateways can read those keys.
- `frappe`: the usual Frappe ORM.
- `instance` and `bpmn_id`: the process instance and this shape's id. Only needed when the script calls a model itself (see the skill for that); ignore them otherwise.

## Reading inputs
`doc.field_name` for the context document, `task_data.get("var")` for a workflow variable.

## Stopping on a validation failure
`frappe.throw("message")`. The engine handles it and the person sees the message. Do not raise anything else for an expected condition.

## Helper functions
A `def` is allowed here (this is the one contract where it is). Keep the script short enough not to need one.

## Worked example
```python
# Check whether the requested leave fits inside the approved allocation.
threshold = task_data.get("threshold") or 0
allocations = frappe.get_all(
    "Leave Allocation",
    filters={"employee": doc.employee, "docstatus": 1},
    fields=["total_leaves_allocated"],
)
total = sum(a.total_leaves_allocated for a in allocations)
result["within_allocation"] = total >= threshold
result["total_allocated"] = total
```
""",
	},
	{
		"skill_name": "bpmn-agent-tool-contract",
		"description": (
			"The runtime contract for a Server Script that backs an Agent Tool, a shape inside an AI "
			"Agent Task's Tools sub-process that a model calls like a function: what it receives, what "
			"it must not touch, how it reports failure, the turn-state bridge, with a worked example. Use "
			"this skill when the request's Shape kind line says agent_tool, before writing or rewriting "
			"the script. Do NOT use it for a script_task; that contract has its own skill."
		),
		"body": """# Agent Tool contract

An AI Agent Task holds a reasoning model. Each shape in its Tools sub-process is exposed to that model as a callable function, and this script is the function's body. It is not a sequential step and it is not a web request.

The tool runs with SPLIT exec globals and locals and receives ONLY these top-level names:

- The model's call arguments, one name each. Only arguments declared on the shape (aiToolParams) exist. A tool with no declared parameters is called with none, so never read an undeclared name.
- `frappe`, `context_doctype`, `context_docname`, `doc` (the context document, possibly an empty stub; never assume a field exists) and `result`.
- `instance` and `bpmn_id`: only needed when the tool calls a model itself (see the skill for that).

It does NOT receive workflow variables, and there is NO `task_data`: reading it raises NameError.

## Hard constraints (the namespace makes these bugs, not style)
1. Straight-line code only. Never define a `def` or a `lambda`: with split namespaces a function body that touches a top-level name dies with NameError when the model calls the tool. Importing and calling module functions is fine.
2. Never raise for an expected failure. An uncaught exception aborts the tool call. Report instead: `result["error"] = "what went wrong"`, and the model recovers. `frappe.throw` is not flow control here.
3. Guard every lookup. The model may pass an id or name that does not exist. Check `frappe.db.exists(...)` or use `frappe.db.get_value(...)` (returns None) before `frappe.get_doc(...)`. An unknown record produces `result["error"]`, never a DoesNotExistError.
4. Write a FLAT dict of JSON-serialisable values onto `result`. It is serialised and handed back to the model as the tool result. No nesting, no document objects.

## Reaching the turn's real state
A tool sees only its arguments, so `context_docname` is the one bridge to per-turn state (the user's text, earlier stage outputs). This pattern is correct, not a hack; never "fix" it away:
```python
from one_bpmn.agents.turn_state import get_turn, update_turn

turn = get_turn(context_docname)
user_text = turn.get("user_text", "")
update_turn(context_docname, my_output=value)
result["ok"] = True
```
Thin wrappers that import and call deployed module code are likewise correct.

## If the tool needs arguments
Say so in your response text, in plain words ("the tool needs to be told the project's name"). The shape must declare them via aiToolParams or the model cannot pass them.

## Worked example (argument `project_name` declared via aiToolParams)
```python
# Count open tasks for the project the assistant names.
project = frappe.db.get_value("Project", {"project_name": project_name}, "name")
if not project:
    result["found"] = False
    result["error"] = f"No project named {project_name}"
else:
    result["found"] = True
    result["project"] = project
    result["open_tasks"] = frappe.db.count("Task", {"project": project, "status": "Open"})
```
""",
	},
	{
		"skill_name": "frappe-outbound-http",
		"description": (
			"How a Server Script talks to a system outside Frappe: the sanctioned helpers, the two "
			"misspellings that ship silently and crash at runtime, where a secret comes from, with GET "
			"and POST examples. Use this skill when the request needs data from, or must send data to, "
			"an external API, URL or webhook. Do NOT use it for lookups inside Frappe; the ORM covers "
			"those."
		),
		"body": """# Calling an external service

Never `import requests`, `urllib`, `urllib3`, `http` or `socket`. The security gate rejects the script on save. Call Frappe's helpers instead, by their FULLY QUALIFIED name:

- `frappe.integrations.utils.make_get_request(url, headers=..., params=...)`
- `frappe.integrations.utils.make_post_request(url, headers=..., json=..., data=...)`
- `frappe.integrations.utils.make_put_request(url, ...)`

Each returns the parsed JSON body when the response is JSON.

## The two forms that are wrong
- The bare name `make_get_request(...)` is not defined in this runtime: NameError.
- `frappe.make_get_request(...)`, the prefix kept but `.integrations.utils` dropped, has no such attribute on the `frappe` module: AttributeError at runtime. The gate does not catch it because it is plain attribute access, so it ships and only fails when the task runs.

The path is always exactly `frappe.integrations.utils.<helper>`.

## Secrets
Read every API key or token from a Settings/Single DocType (`frappe.db.get_single_value("My Integration Settings", "api_key")`) or site config. Never hardcode one and never write one to a log.

## Failure handling by contract
In a script_task, let a failed call raise; the engine reports it. In an agent_tool, wrap the call in try/except and set `result["error"]`, because a tool must never raise.

## GET with query parameters
```python
# Look up the current USD exchange rate from an external service.
response = frappe.integrations.utils.make_get_request(
    "https://api.example.com/rates",
    params={"base": "USD"},
)
result["usd_rate"] = response.get("rate")
```

## POST with a JSON body and a secret from settings
```python
# Tell an external service that this process finished.
api_key = frappe.db.get_single_value("My Integration Settings", "api_key")
frappe.integrations.utils.make_post_request(
    "https://api.example.com/notify",
    headers={"Authorization": f"Bearer {api_key}"},
    json={"process": doc.name, "status": "done"},
)
result["notified"] = True
```
""",
	},
	{
		"skill_name": "modifying-an-existing-script",
		"description": (
			"How to change a Server Script that already exists without rewriting it from scratch, and "
			"what to do when its current code is not in front of you. Use this skill when the request "
			"carries an Existing script block or names a Currently linked Server Script. Do NOT use it "
			"when no script is linked yet and a new one is being created."
		),
		"body": """# Changing an existing script

Work from the current code. Never write a replacement from scratch.

- If the request contains an "Existing script" block, THAT is the current code. Rewrite it: keep its intent and structure, change only what the person asked for, and leave everything else exactly as it was, comments included.
- Return the FULL script, not a fragment. The platform shows the person a diff between the old and new versions, so a partial answer reads as a deletion of everything you left out.
- If a "Currently linked Server Script" is named but there is no "Existing script" block, you do not have the current code and you have no tool that fetches it. Do NOT invent a new script. Stop and say, in plain English, that the current script could not be loaded and ask the person how they want to proceed. Never write "since I can't retrieve the existing script, I'll write a new one".
- A change to an existing script keeps its contract. Do not switch a script_task to agent_tool idioms or the reverse while editing.
""",
	},
	{
		"skill_name": "calling-an-ai-agent-from-a-script",
		"description": (
			"The pattern for a Server Script that must ask a model something itself, such as classify, "
			"summarise or rewrite a value, before deciding what to do next, tracked as a real AI Agent "
			"Run. Use this skill when the script's own logic needs an answer from a model wrapped in "
			"deterministic code. Do NOT use it when the person just wants an AI step in the process; "
			"a real AI Agent Task shape needs no script at all."
		),
		"body": """# A script that calls a model

Sometimes a script needs an answer from a model as part of its own logic: classify something, then branch on the result. Call the shared dispatcher with `execute_shape(instance, bpmn_id, task_cfg, kwargs)`. `instance` and `bpmn_id` are already injected in both contracts. The call is tracked as a real, observable AI Agent Run, exactly like an AI Agent Task on the diagram.

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

## Rules
- Never put dynamic or user-supplied text inside the `aiUserPrompt` string itself. Pass it through the last argument (a plain dict) and reference it with a bare `{{ variable_name }}` placeholder. Jinja substitutes the value verbatim and never re-parses it, so text containing `{{ }}` cannot become template syntax.
- `aiAgentConfig` must name a REAL AI Agent Configuration. If you are not certain of the exact name, say so rather than invent one.
- The reply comes back under `bpmn_id + "_output"`, with `_error_code` and `_error_message` on failure. Read that exact key, never a bare `"output"`.
- In an agent_tool the reply is also saved to the turn's state under `bpmn_id + "_result"`, so a later stage tool can read it with no extra code.
- Reach for this only when the model call needs surrounding deterministic logic: validate the answer, branch on it, retry it, combine it with other data. If the person just wants "an AI step", tell them a real AI Agent Task shape on the diagram is simpler and needs no script.
""",
	},
]


def execute():
	for skill in SKILLS:
		_upsert_skill(skill)

	writers = [
		name
		for agent_id in WRITER_AGENT_IDS
		if (name := frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name"))
	]
	for name in writers:
		doc = frappe.get_doc("AI Agent Configuration", name)
		changed = False
		if PROMPT_MARKER not in (doc.system_prompt or ""):
			doc.system_prompt = WRITER_PROMPT
			changed = True
		enabled = {row.skill for row in doc.enabled_skills}
		for skill in SKILLS:
			if skill["skill_name"] not in enabled:
				doc.append("enabled_skills", {"skill": skill["skill_name"]})
				changed = True
		if changed:
			doc.save(ignore_permissions=True)

	main = frappe.db.get_value("AI Agent Configuration", {"agent_id": MAIN_AGENT_ID}, "name")
	if main:
		doc = frappe.get_doc("AI Agent Configuration", main)
		dead = [row for row in doc.sub_prompts if row.sub_agent_id in DEAD_SUB_PROMPTS]
		for row in dead:
			doc.remove(row)
		if dead:
			doc.save(ignore_permissions=True)


def _upsert_skill(skill: dict):
	if frappe.db.exists("AI Skill", skill["skill_name"]):
		doc = frappe.get_doc("AI Skill", skill["skill_name"])
		if (doc.description, doc.body, doc.status) == (skill["description"], skill["body"], "Active"):
			return
	else:
		doc = frappe.new_doc("AI Skill")
		doc.skill_name = skill["skill_name"]
		doc.tier = "Draft-Only"
	doc.description = skill["description"]
	doc.body = skill["body"]
	doc.status = "Active"
	doc.save(ignore_permissions=True)
