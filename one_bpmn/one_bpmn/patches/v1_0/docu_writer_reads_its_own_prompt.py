"""Docu's Tool Write Schema reads the writer prompt from the "Docu - Schema Writer" record.

The script still read the schema_writer sub-prompt on Docu Agent, which seed_docu_skills removed,
so the writer ran with an empty system prompt. It now takes that record's system_prompt and appends
the form design rules skill, since this call has no load_skill tool. Idempotent: the edit applies once.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import apply_edit

API_METHOD = "docu_tool_write_schema"
ANCHOR = '_system = (_subs.get("schema_writer") or {}).get("prompt") or ""'
REPLACEMENT = (
	'_system = ((get_agent_config("docu_schema_writer") or {}).get("system_prompt") or "")'
	' + "\\n\\n# The form design rules\\n"'
	' + (frappe.db.get_value("AI Skill", "doctype-form-design-rules", "body") or "")'
)


def execute():
	name = frappe.db.get_value("Server Script", {"api_method": API_METHOD}, "name")
	if not name:
		return
	doc = frappe.get_doc("Server Script", name)
	edited = apply_edit(doc.script or "", ANCHOR, REPLACEMENT)
	if edited is None:
		frappe.log_error(
			title="docu_writer_reads_its_own_prompt: anchor not found",
			message=f"{name} has no single '{ANCHOR}' line; the script is left as-is.",
		)
		return
	if edited != doc.script:
		doc.script = edited
		doc.save(ignore_permissions=True)
