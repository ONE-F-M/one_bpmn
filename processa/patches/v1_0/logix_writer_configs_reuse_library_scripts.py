"""Logix's script and tool writer configurations get the library-script guidance on their own system prompts."""

import frappe

from processa.patches.v1_0.logix_writer_reuses_library_scripts import GUIDANCE

WRITER_AGENT_IDS = ("logix_script_writer", "logix_tool_writer")


def execute():
	for agent_id in WRITER_AGENT_IDS:
		name = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name")
		if not name:
			continue
		config = frappe.get_doc("AI Agent Configuration", name)
		if GUIDANCE in (config.system_prompt or ""):
			continue
		config.system_prompt = ((config.system_prompt or "").rstrip() + "\n\n" + GUIDANCE).strip()
		config.save(ignore_permissions=True)  # a patch runs as Administrator with no request user to check
