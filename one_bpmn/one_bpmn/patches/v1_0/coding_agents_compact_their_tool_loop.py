"""The sandbox coding agents compact their tool loop once a call's prompt passes 50,000 tokens. Idempotent."""

import frappe

AGENTS = ("Dev Agent", "Frontend Agent", "Mobile App Agent", "Connector Agent")
THRESHOLD = 50000
KEEP_TURNS = 8


def execute():
	for agent in AGENTS:
		if frappe.db.get_value("AI Agent Configuration", agent, "loop_compaction_threshold") == 0:
			frappe.db.set_value(
				"AI Agent Configuration",
				agent,
				{"loop_compaction_threshold": THRESHOLD, "loop_compaction_keep_turns": KEEP_TURNS},
			)
