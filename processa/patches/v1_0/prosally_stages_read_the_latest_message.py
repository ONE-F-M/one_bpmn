"""ProsAlly's generate and modify stages add the turn's own message to their prompt.

The chat history they read leaves out the current message. A script already carrying the line is
skipped, and one whose anchor moved is logged and left as it is.
"""

import frappe

# Server Script name pattern, matched with like to avoid the dash in the name -> the line the message follows.
ANCHORS = {
	"ProsAlly%Tool Generate Process": '    _parts.append("Conversation and process description:\\n" + _hist)\n',
	"ProsAlly%Tool Modify Process": '    _parts.append("Modification request from conversation:\\n" + _hist)\n',
}
MESSAGE_LINES = 'if turn.get("user_text"):\n    _parts.append("Latest message: " + turn.get("user_text"))\n'


def execute():
	for pattern, anchor in ANCHORS.items():
		name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
		if not name:
			continue
		doc = frappe.get_doc("Server Script", name)
		if MESSAGE_LINES in doc.script:
			continue
		if doc.script.count(anchor) != 1:
			frappe.log_error(
				title="prosally_stages_read_the_latest_message: anchor not found",
				message=f"{name} does not carry the history line exactly once; the script is left as it is.",
			)
			continue
		doc.script = doc.script.replace(anchor, anchor + MESSAGE_LINES, 1)
		doc.save(ignore_permissions=True)
