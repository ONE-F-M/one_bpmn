"""
WI-001751: let the AI Assistant create an AI Agent Configuration through its
tools, then offer evals for it.

Until now agent creation lived only on the modal path: recommend_ai_task_config
returned a ``proposed_config`` the designer confirmed with a "Create agent"
button, which called agent_config_resolver.create_agent_configuration. That path
is a single LLM call with no tool loop, so the assistant could never follow
creation with anything — in particular it could not build the agent's evals,
because create_eval_suite / create_eval_case are tools and tools do not exist on
that surface.

This patch adds ``create_agent_configuration`` as a shape in the assistant's
lumina_tools ad-hoc sub-process, alongside the eval-authoring tools added by
add_assistant_eval_authoring_tools. Creation and eval authoring are then reachable
in one conversation, in that order.

The tool wraps the same whitelisted endpoint the button calls, so the record is
created identically — Chat + Draft, with the caller's permissions, and the
After-Insert trigger starts the AI Agent Creation Process that walks it to Live.
Nothing about creation semantics changes; only who can reach it.

One thing DOES change and is handled in the prompt rather than the code: on the
modal path the designer confirmed the proposal by clicking a button, and a tool
call has no such gate. The prompt section below therefore requires an explicit
confirmation in the conversation before the tool is called, and the tool's own
documentation says it writes a real record immediately.

Sample prompts are deliberately not part of the payload. Evals belong in an
AI Eval Suite with its own cases (the link lives on the suite, WI-001743), not
duplicated onto the configuration as sample prompts.

Diagrams are data, never code (WI-001540) — the shape is spliced into the site's
own copy of the map. Idempotent throughout.
"""

import re

import frappe

MODEL_NAME = "AI Agent Assistant — Chat"
AGENT_ID = "ai_agent_assistant"
ADHOC_ID = "lumina_tools"

CREATE_AGENT_SCRIPT_NAME = "Assistant Tool – Create Agent Configuration"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Server Script — the tool body
# ═══════════════════════════════════════════════════════════════════════════════
# Runs with the CALLING USER's permissions: create_agent_configuration itself
# calls frappe.has_permission(..., "create", throw=True) and inserts without
# ignore_permissions, so the assistant can only create what the designer driving
# it could create by hand.

CREATE_AGENT_CONFIGURATION_SCRIPT = '''# Tool: create an AI Agent Configuration through the same endpoint the editor's
# "Create agent" button uses. Chat + Draft; the After-Insert trigger starts the
# AI Agent Creation Process, which takes the agent to Live.
#
# WI-001655: the agent picks an ai_model from the AI Model catalog and its
# provider is DERIVED from that model's credentials link. Passing a provider
# directly is the pre-WI-001655 shape and leaves ai_model empty, which the
# creation process's Validate step rejects — so the checks below mirror
# agent_provisioning.VALIDATION_RULES rather than let a new agent land straight
# in Needs Attention.
_name = (task_data.get("agent_name") or "").strip()
_label = (task_data.get("chat_mode_label") or "").strip()
_model = (task_data.get("ai_model") or "").strip()
_process_map = (task_data.get("process_model") or "").strip()
_system_prompt = (task_data.get("system_prompt") or "").strip()
_description = (task_data.get("description") or "").strip()

_credentials = None
if _model and frappe.db.exists("AI Model", _model):
    _credentials = frappe.db.get_value("AI Model", _model, "ai_provider_credentials")

if not _name:
    result["error"] = "No agent_name given."
elif not _label and not _process_map:
    result["error"] = (
        "No chat_mode_label given - required unless the agent is mapped to a "
        "process (pass process_model for a process-embedded agent)."
    )
elif _process_map and not frappe.db.exists("BPMN Process Model", _process_map):
    result["error"] = "Unknown BPMN Process Model: " + _process_map
elif not _model:
    result["error"] = "No ai_model given - pass the exact name of an AI Model catalog record."
elif not frappe.db.exists("AI Model", _model):
    result["error"] = "Unknown AI Model: " + _model
elif not _credentials:
    result["error"] = (
        "AI Model '" + _model + "' links no AI Provider Credentials, so no provider can be "
        "derived from it. Pick a model that has credentials."
    )
elif not frappe.db.get_value("AI Provider Credentials", _credentials, "enabled"):
    result["error"] = (
        "AI Model '" + _model + "' derives credentials '" + _credentials + "', which are "
        "disabled. Pick a model whose credentials are enabled."
    )
elif not (_system_prompt or _description):
    result["error"] = (
        "Give either a system_prompt or a description - the creation process needs one of "
        "them (it generates the prompt from the description when the prompt is empty)."
    )
else:
    from one_bpmn.agents.agent_config_resolver import create_agent_configuration

    # sample_prompts is intentionally omitted: evals live in an AI Eval Suite
    # with its own cases, not duplicated onto the configuration.
    _payload = {
        "agent_name": _name,
        "chat_mode_label": _label,
        "ai_model": _model,
        # WI-001997: the designer-chosen map the agent belongs to — usually
        # the process open in the editor. Nothing clones or overwrites it.
        "process_model": _process_map,
        "system_prompt": _system_prompt,
        "description": _description,
    }
    _framework = (task_data.get("agent_framework") or "").strip()
    if _framework:
        _payload["agent_framework"] = _framework

    try:
        _created = create_agent_configuration(_payload)
        # "agent_configuration" rather than "name": execute_shape strips any
        # result key that collides with an argument the LLM supplied, and the
        # next tool call needs this value to attach an eval suite.
        result["agent_configuration"] = _created.get("name")
        result["agent_id"] = _created.get("agent_id")
        result["derived_provider"] = _credentials
        result["creation_instance"] = _created.get("creation_instance") or ""
        if not _created.get("creation_instance"):
            result["warning"] = (
                "Created, but the AI Agent Creation Process did not start "
                "(the creation model may be inactive) - the agent will stay Draft."
            )
    except Exception as _exc:
        result["error"] = "Could not create the agent configuration: " + str(_exc)
'''


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Diagram: the tool shape
# ═══════════════════════════════════════════════════════════════════════════════
_XML_TOOL_ANCHOR = "<bpmn:completionCondition"

_TOOL_SHAPE = {
	"id": "create_agent_configuration",
	"name": "Create Agent Configuration",
	"script": CREATE_AGENT_SCRIPT_NAME,
	"documentation": (
		"Create a new AI Agent Configuration. This WRITES A REAL RECORD immediately and "
		"starts the process that takes the agent Live, so only call it once the designer has "
		"explicitly confirmed the details. Returns the configuration's record name — pass that "
		"to list_eval_suites / create_eval_suite when adding the agent's evals afterwards."
	),
	"params": {
		"properties": {
			"agent_name": {
				"type": "string",
				"description": "Display name, e.g. 'Leave Application Summarizer'. Must not already exist.",
			},
			"chat_mode_label": {
				"type": "string",
				"description": (
					"Label the agent appears under in the chat picker. Must differ from every "
					"label already taken (they are listed in the prerequisites). ONLY for agents "
					"that should appear in chat — omit it for an agent mapped to an ordinary "
					"business process, which never chats."
				),
			},
			"process_model": {
				"type": "string",
				"description": (
					"Exact name of the BPMN Process Model this agent is mapped to — usually the "
					"process currently open in the editor. Ask the designer which process the "
					"agent belongs to and propose the open one as the default; never invent a "
					"model name. Omit only for a chat-only agent with no process."
				),
			},
			"ai_model": {
				"type": "string",
				"description": (
					"Exact name of an AI Model catalog record (they are listed in the "
					"prerequisites). The agent's provider is derived from that model's "
					"credentials link, so do not pass a provider. Never invent a model name."
				),
			},
			"system_prompt": {
				"type": "string",
				"description": (
					"The agent's own instructions — what it does and how it should behave. "
					"May be omitted if description is given: the creation process then "
					"generates the prompt from the description."
				),
			},
			"description": {
				"type": "string",
				"description": (
					"What the agent does. Required when system_prompt is omitted, since it "
					"is what the prompt is generated from."
				),
			},
			"agent_framework": {
				"type": "string",
				"enum": ["Direct API", "Google ADK", "LangGraph", "Anthropic"],
				"description": "Execution framework. Omit for the Direct API default.",
			},
		},
		"required": ["agent_name", "ai_model"],
	},
	# Free slot on the lumina_tools grid (x 700-1400, y 290-850); the eval tools
	# took 750/910/1070 on the y=730 row.
	"bounds": (1230, 730),
}


def _escape_attr(value: str) -> str:
	return (
		value.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&#34;")
	)


def _shape_element(shape: dict) -> str:
	"""The scriptTask element on its own, so an already-present shape whose
	argument schema has since changed can be compared and replaced."""
	params = _escape_attr(frappe.as_json(shape["params"], indent=None))
	return (
		f'<bpmn:scriptTask id="{shape["id"]}" name="{shape["name"]}" '
		f'spiffworkflow:serverScript="{shape["script"]}" '
		f'spiffworkflow:scriptType="Server Script" '
		f'spiffworkflow:scriptName="{shape["script"]}" '
		f'spiffworkflow:aiToolParams="{params}">\n'
		f'        <bpmn:documentation>{_escape_attr(shape["documentation"])}</bpmn:documentation>\n'
		f'        <bpmn:script>{shape["script"]}</bpmn:script>\n'
		f"      </bpmn:scriptTask>"
	)


def _shape_xml(shape: dict) -> str:
	return _shape_element(shape) + "\n      "


def _di_xml(shape_id: str, x: int, y: int) -> str:
	return (
		f'\n      <bpmndi:BPMNShape id="{shape_id}_di" bpmnElement="{shape_id}">\n'
		f'        <dc:Bounds x="{x}" y="{y}" width="100" height="80" />\n'
		f"      </bpmndi:BPMNShape>"
	)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Prompt steering
# ═══════════════════════════════════════════════════════════════════════════════
# Appended to the configuration's system_prompt rather than regenerated from
# api/ai_assistant.py::_build_system_prompt: the live prompt on a site is richer
# than that builder, so rebuilding it would lose text.
_PROMPT_MARKER = "CREATING AN AGENT THROUGH YOUR TOOLS:"
# Sections are appended, so this one lands after the eval-authoring section rather
# than before it. An early draft said "follow AUTHORING EVAL SUITES AND CASES
# below", which is the wrong direction; repair it in place where it already shipped
# instead of leaving the model a false pointer.
# WI-001655 made the MODEL the agent's pick, with the provider derived from that
# model's credentials link. An earlier draft of this section told the assistant to
# supply a provider — which leaves ai_model empty and fails the creation process's
# Validate step — so repair that wording too where it already shipped.
_STALE_PHRASES = {
	"follow AUTHORING EVAL SUITES AND CASES below":
		"follow the AUTHORING EVAL SUITES AND CASES rules in this prompt",
	(
		"It needs an agent name, a chat mode label that is not already taken, the exact name "
		"of an enabled AI Provider Credentials record, and the agent's own system prompt.\n"
		"  - Gather every one of those in conversation first. Ask for what is missing rather "
		"than guessing, and never invent a provider name."
	): (
		"It needs an agent name, a chat mode label that is not already taken, and an exact "
		"name from the AI Model catalog listed in the prerequisites. Give it a system prompt, "
		"or a description for the creation process to generate the prompt from.\n"
		"  - The agent's PROVIDER is derived from the model's credentials link — pick a model, "
		"never a provider, and never invent a model name.\n"
		"  - Gather every one of those in conversation first, asking for what is missing "
		"rather than guessing."
	),
	# WI-001997: the map is a designer-chosen link at creation, and the chat
	# mode label became conditional on it — repair the shipped bullet in place.
	(
		"It needs an agent name, a chat mode label that is not already taken, and an exact "
		"name from the AI Model catalog listed in the prerequisites. Give it a system prompt, "
		"or a description for the creation process to generate the prompt from."
	): (
		"It needs an agent name, an exact name from the AI Model catalog listed in the "
		"prerequisites, and the BPMN process map the agent belongs to — ask which process the "
		"agent is mapped to (process_model) and propose the process currently open in the "
		"editor as the default. Add a chat mode label (not already taken) ONLY when the agent "
		"should appear in chat; an agent mapped to an ordinary business process needs no "
		"label. Give it a system prompt, or a description for the creation process to "
		"generate the prompt from."
	),
}
_PROMPT_SECTION = """

CREATING AN AGENT THROUGH YOUR TOOLS:
  - You can create an AI Agent Configuration yourself with create_agent_configuration. It needs an agent name, an exact name from the AI Model catalog listed in the prerequisites, and the BPMN process map the agent belongs to — ask which process the agent is mapped to (process_model) and propose the process currently open in the editor as the default. Add a chat mode label (not already taken) ONLY when the agent should appear in chat; an agent mapped to an ordinary business process needs no label. Give it a system prompt, or a description for the creation process to generate the prompt from.
  - The agent's PROVIDER is derived from the model's credentials link — pick a model, never a provider, and never invent a model name.
  - Gather every one of those in conversation first, asking for what is missing rather than guessing.
  - CONFIRM BEFORE CREATING. Summarise the agent you are about to create and wait for the designer to agree. The tool writes a real record and starts the process that takes the agent Live — there is no confirmation step after you call it.
  - CREATE THE AGENT FIRST, THEN ASK ABOUT EVALS. Do not gather eval cases before the agent exists: the suite has to point at the agent's record name, which only exists once created.
  - Immediately after create_agent_configuration succeeds, tell the designer the agent was created and ASK whether they want evals for it. If they do, follow the AUTHORING EVAL SUITES AND CASES rules in this prompt, passing the record name the tool returned.
  - Do not put eval cases on the configuration as sample prompts. Evals live in an AI Eval Suite with its own cases; the link to the agent lives on the suite.
  - When a task dialog is open and the designer wants the new agent linked to the shape, say the agent was created and that they can select it in the Linked AI Agent Configuration field — you cannot edit the shape yourself."""


# ═══════════════════════════════════════════════════════════════════════════════
# Patch steps
# ═══════════════════════════════════════════════════════════════════════════════

def _ensure_script() -> None:
	"""Create the tool's Server Script, or refresh a stale body in place."""
	if frappe.db.exists("Server Script", CREATE_AGENT_SCRIPT_NAME):
		doc = frappe.get_doc("Server Script", CREATE_AGENT_SCRIPT_NAME)
		if (doc.script or "").strip() != CREATE_AGENT_CONFIGURATION_SCRIPT.strip():
			doc.script = CREATE_AGENT_CONFIGURATION_SCRIPT
			doc.save(ignore_permissions=True)
		return
	frappe.get_doc({
		"doctype": "Server Script",
		"name": CREATE_AGENT_SCRIPT_NAME,
		"script_type": "API",
		"api_method": "assistant_tool_create_agent_configuration",
		"script": CREATE_AGENT_CONFIGURATION_SCRIPT,
		"disabled": 0,
	}).insert(ignore_permissions=True)


def _update_process_model() -> None:
	"""Splice the shape into lumina_tools, then recompile."""
	if not frappe.db.exists("BPMN Process Model", MODEL_NAME):
		frappe.log_error(
			title="add_assistant_agent_creation_tool: assistant map missing",
			message=f"No BPMN Process Model '{MODEL_NAME}' on this site; the tool script was "
					"created but no shape was added. Import the assistant map and re-run.",
		)
		return

	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	needs_shape = f'id="{_TOOL_SHAPE["id"]}"' not in xml
	needs_di = f'bpmnElement="{_TOOL_SHAPE["id"]}"' not in xml

	# An already-present shape may carry a stale argument schema — the contract
	# moved from ai_provider_credentials to ai_model (WI-001655). Refresh it in
	# place rather than leave the LLM calling the tool with arguments the script
	# no longer reads.
	stale = None
	if not needs_shape:
		found = re.search(
			rf'<bpmn:scriptTask id="{_TOOL_SHAPE["id"]}".*?</bpmn:scriptTask>', xml, re.S
		)
		if found and found.group(0) != _shape_element(_TOOL_SHAPE):
			stale = found

	if not needs_shape and not needs_di and not stale:
		return

	# Anchor on the sub-process that actually holds the assistant's tools, not
	# some other ad-hoc sub-process, or the tool lands in the wrong toolbox.
	adhoc = re.search(
		rf'<bpmn:adHocSubProcess id="{ADHOC_ID}".*?</bpmn:adHocSubProcess>', xml, re.S
	)
	if not adhoc or _XML_TOOL_ANCHOR not in adhoc.group(0):
		frappe.log_error(
			title="add_assistant_agent_creation_tool: diagram anchors not found",
			message=f"'{MODEL_NAME}' has no '{ADHOC_ID}' ad-hoc sub-process with a "
					"completionCondition; add the shape manually.",
		)
		return

	if needs_shape:
		patched = adhoc.group(0).replace(
			_XML_TOOL_ANCHOR, _shape_xml(_TOOL_SHAPE) + _XML_TOOL_ANCHOR, 1
		)
		xml = xml[: adhoc.start()] + patched + xml[adhoc.end():]
	elif stale:
		# Swap the element in place; the ad-hoc sub-process and DI are untouched.
		xml = xml[: stale.start()] + _shape_element(_TOOL_SHAPE) + xml[stale.end():]

	if needs_di:
		plane_close = xml.rfind("</bpmndi:BPMNPlane>")
		if plane_close == -1:
			frappe.log_error(
				title="add_assistant_agent_creation_tool: no BPMNPlane to extend",
				message=f"'{MODEL_NAME}' has no </bpmndi:BPMNPlane>; the shape was added "
						"without diagram bounds and will not render on the canvas.",
			)
		else:
			di = _di_xml(_TOOL_SHAPE["id"], *_TOOL_SHAPE["bounds"])
			xml = xml[:plane_close] + di + "\n      " + xml[plane_close:]

	# db_set skips the editability gate — a trusted content migration, the same
	# rationale as compile_process_model's skip_editability_check.
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml)

	# Recompile so serialized_spec embeds the new tool in aiToolShapes. New
	# conversations pick it up; running instances keep their old spec.
	from one_bpmn.api.compilation import compile_process_model

	try:
		compile_process_model(MODEL_NAME)
	except Exception:
		frappe.log_error(
			title="add_assistant_agent_creation_tool: recompile failed",
			message=frappe.get_traceback(),
		)


def _steer_prompt() -> None:
	"""Tell the assistant it can create agents, and in what order."""
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""

	if _PROMPT_MARKER in prompt:
		repaired = prompt
		for stale, fixed in _STALE_PHRASES.items():
			repaired = repaired.replace(stale, fixed)
		if repaired == prompt:
			return
		updated = repaired
	else:
		updated = prompt.rstrip() + _PROMPT_SECTION

	frappe.db.set_value(
		"AI Agent Configuration", name, "system_prompt", updated, update_modified=False
	)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")


def execute():
	_ensure_script()
	_update_process_model()
	_steer_prompt()
	frappe.db.commit()
