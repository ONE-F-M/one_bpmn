"""Switch compaction on for the chat agents, so older turns reach the model as a summary.

The platform's history step sends the summary of anything beyond the message
window, but no live agent had compaction on, so no summary ever existed.
"""

import frappe

CHAT_AGENTS = ("prosally", "logix", "Docu Agent", "lucrusher")


def execute():
	for name in frappe.get_all(
		"AI Agent Configuration",
		filters={"name": ["in", CHAT_AGENTS], "compaction_enabled": 0},
		pluck="name",
	):
		frappe.db.set_value("AI Agent Configuration", name, "compaction_enabled", 1, update_modified=False)
