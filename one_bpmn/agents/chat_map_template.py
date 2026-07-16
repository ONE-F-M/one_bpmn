# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Chat-map template (WI-001540).

The agent-creation process clones a single reusable chat process map for
every new chat agent, so nobody hand-authors BPMN XML. The template is a
generalization of the working Lumina General Chat map with two
config-driven spots filled at clone time:

  * the start-event condition ``agent_mode=="{{ CHAT_MODE_LABEL }}"`` —
    generated from the agent's chat mode label, never hand-typed, so the
    map only wakes for its own conversations;
  * the AI Agent task's ``aiSystemPrompt`` — injected from the agent's
    configuration, keeping AI Agent Configuration the single source of truth.

The tool shapes drawn in the template's ad-hoc subprocess define the
cloned agent's toolkit (the map is the tool grant).
"""

import os

import frappe
from frappe.utils import escape_html

_TEMPLATE_PATH = os.path.join(
	os.path.dirname(__file__), "..", "one_bpmn", "templates", "chat_agent_map_template.bpmn"
)


def _read_template() -> str:
	with open(os.path.normpath(_TEMPLATE_PATH)) as fh:
		return fh.read()


def render_chat_map_xml(chat_mode_label: str, system_prompt: str) -> str:
	"""Return deployable BPMN XML for a chat agent with this label + prompt.

	Both values are XML-attribute-escaped: the label lands inside a
	<bpmn:condition> string literal and the prompt inside the
	aiSystemPrompt="" attribute, so quotes/newlines must not break the XML.
	"""
	if not chat_mode_label:
		frappe.throw(frappe._("A chat mode label is required to build the chat map."))
	xml = _read_template()
	xml = xml.replace("{{ CHAT_MODE_LABEL }}", escape_html(chat_mode_label))
	# aiSystemPrompt is an XML attribute value; escape quotes/entities/newlines.
	prompt_attr = (
		escape_html(system_prompt or "")
		.replace("\r\n", "&#10;")
		.replace("\n", "&#10;")
		.replace("\r", "&#10;")
	)
	xml = xml.replace("{{ SYSTEM_PROMPT }}", prompt_attr)
	return xml


def clone_chat_map_for_agent(config_name: str) -> str:
	"""Clone the template into a new BPMN Process Model for the given
	AI Agent Configuration and return the new model's name.

	Idempotent: if the configuration already links a process model, that
	model is refreshed in place rather than duplicated.
	"""
	config = frappe.get_doc("AI Agent Configuration", config_name)
	label = config.chat_mode_label or config.agent_id
	xml = render_chat_map_xml(label, config.system_prompt or "")

	model_name = config.process_model or f"{config.agent_name} — Chat"
	if frappe.db.exists("BPMN Process Model", model_name):
		model = frappe.get_doc("BPMN Process Model", model_name)
		model.bpmn_xml = xml
		model.save(ignore_permissions=True)
	else:
		model = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"__newname": model_name,
			"bpmn_xml": xml,
		})
		model.insert(ignore_permissions=True)

	if config.process_model != model.name:
		config.db_set("process_model", model.name, update_modified=False)
	return model.name
