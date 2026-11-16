"""Docu's scripts, prompt and map default to the Processa Engine module."""

import frappe

OLD = "ONE BPMN"
NEW = "Processa Engine"
MODEL_NAME = "Docu \u2013 DocType Agent"
AGENT_NAME = "Docu \u2013 Schema Writer"
SCRIPT_NAMES = ("Docu \u2013 Tool Review Schema", "Docu \u2013 Tool Write Schema")


def execute():
	for script_name in SCRIPT_NAMES:
		code = frappe.db.get_value("Server Script", script_name, "script")
		if code and f'"{OLD}"' in code:
			frappe.db.set_value(
				"Server Script",
				script_name,
				"script",
				code.replace(f'"{OLD}"', f'"{NEW}"'),
				update_modified=False,
			)

	prompt = frappe.db.get_value("AI Agent Configuration", AGENT_NAME, "system_prompt")
	if prompt and OLD in prompt:
		frappe.db.set_value(
			"AI Agent Configuration",
			AGENT_NAME,
			"system_prompt",
			prompt.replace(OLD, NEW),
			update_modified=False,
		)

	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml")
	if xml and OLD in xml:
		frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml.replace(OLD, NEW))

		from processa.api.deploy import compile_process_model

		compile_process_model(MODEL_NAME)
