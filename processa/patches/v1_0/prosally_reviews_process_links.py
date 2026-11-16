"""ProsAlly answers a request to review the links between its map and related maps from get_process_links.

Edits the live Classify Intent Server Script by anchor so the review skips the intent classifier, which sent such
requests to the compare reply. Script text that already has its marker is left alone.
"""

import frappe

from processa.patches.v1_0.prosally_relayouts_and_compares import SCRIPT, apply_edits

SCRIPT_EDITS = (
	(
		"from processa.agents.turn_state import get_turn, update_turn\n",
		"from processa.agents.turn_state import get_turn, update_turn\n"
		"from processa.agents.process_links import asks_for_links_review, links_review_output\n",
	),
	(
		"\nelse:\n    _cfg = prosally_config()\n",
		'\nelif asks_for_links_review(turn.get("user_text") or ""):\n'
		"    _output = links_review_output(context_docname)\n"
		'    update_turn(context_docname, intent="LINKS_REVIEW", confirmed=False, output=_output, done=True)\n'
		'    result["intent"] = "LINKS_REVIEW"\n'
		'    result["next"] = "finalize"\n'
		"else:\n    _cfg = prosally_config()\n",
	),
)
SCRIPT_MARKER = "links_review_output"


def execute():
	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		if not frappe.db.exists("Server Script", SCRIPT):
			return
		doc = frappe.get_doc("Server Script", SCRIPT)
		if SCRIPT_MARKER in (doc.script or ""):
			return
		edited = apply_edits(doc.script or "", SCRIPT_EDITS)
		if edited is None:
			frappe.log_error(
				title="prosally_reviews_process_links: anchor not found",
				message="The Classify Intent script does not contain every expected anchor.",
			)
			return
		doc.script = edited
		doc.save(ignore_permissions=True)
	finally:
		frappe.set_user(original_user)
