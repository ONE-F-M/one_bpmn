"""ProsAlly's generate reply lists the lanes it drew and any named lane it missed; the modify reply lists what changed.

Edits the two site scripts in place. A script already carrying the call is skipped, and one whose
anchors are not each found exactly once is logged and left as it is.
"""

import frappe

# Server Script name pattern, matched with like to avoid the dash in the name -> (helper, reply anchor, call).
STAGES = {
	"ProsAlly%Tool Generate Process": (
		"describe_lanes",
		'" Review it on the canvas."',
		' + describe_lanes(chat_history, turn.get("user_text", ""), ir_dict)',
	),
	"ProsAlly%Tool Modify Process": (
		"describe_changes",
		'"have been preserved. Review the changes on the canvas."\n            )',
		" + describe_changes(current_xml, merged_xml)",
	),
}
IMPORT_ANCHOR = "from one_bpmn.agents.prosally_helpers import complete_sub_prompt, "


def execute():
	for pattern, (helper, anchor, call) in STAGES.items():
		name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
		if not name:
			continue
		doc = frappe.get_doc("Server Script", name)
		if call in doc.script:
			continue
		script = with_reply_call(doc.script, helper, anchor, call)
		if script is None:
			frappe.log_error(
				title="prosally_replies_say_what_was_drawn: anchors not found",
				message=f"{name} does not carry each anchor exactly once; the script is left as it is.",
			)
			continue
		doc.script = script
		doc.save(ignore_permissions=True)


def with_reply_call(script: str, helper: str, anchor: str, call: str) -> str | None:
	"""The script importing helper and appending call to its reply, or None if an anchor moved."""
	if script.count(IMPORT_ANCHOR) != 1:
		return None
	if script.count(anchor) != 1:
		return None
	script = script.replace(IMPORT_ANCHOR, f"{IMPORT_ANCHOR}{helper}, ", 1)
	return script.replace(anchor, anchor + call, 1)
