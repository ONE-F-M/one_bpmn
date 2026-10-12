"""ProsAlly and LuCrusher Save Response word a failed turn by its error code instead of always blaming the AI provider.

The reply line that chat_agents_post_failed_turn_error added is swapped for a call to
server_script_api.turn_failure_text, so a budget stop or a turn cap reads as what it is.
Scripts are found by api_method. Idempotent: the edit applies only once.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import SAVE_RESPONSE, apply_edit

OLD_LINE = '    _agent_text = "The AI provider rejected the request: " + _reason + ". Please try again in a few minutes."\n'
NEW_LINES = (
	"    from one_bpmn.api.server_script_api import turn_failure_text\n"
	"    _agent_text = turn_failure_text(_failed, _reason)\n"
)


def execute():
	for api_method in SAVE_RESPONSE:
		name = frappe.db.get_value("Server Script", {"api_method": api_method}, "name")
		if not name:
			continue
		doc = frappe.get_doc("Server Script", name)
		edited = apply_edit(doc.script or "", OLD_LINE, NEW_LINES)
		if edited is None:
			frappe.log_error(
				title="chat_agents_name_the_failure_reason: line not found",
				message=f"{name} has no single provider error line; the script is left as-is.",
			)
			continue
		if edited != doc.script:
			doc.script = edited
			doc.save(ignore_permissions=True)
