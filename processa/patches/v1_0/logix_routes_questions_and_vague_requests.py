"""Logix answers a question about the linked script and asks back on a request that points at nothing.

The classifier learns both cases, the orchestrator stops treating a question as a reason to call
clarify, and the writer answers a question in words. Idempotent: each rule is appended once.
"""

import frappe

RULES = {
	"logix_intent_classifier": (
		"\n\nTwo more rules, which override the leanings above:\n"
		"- A question about the linked script that asks for no change (\"what does this script do\", "
		"\"why did it fail\") is MODIFY. The writer answers it in words and leaves the code alone.\n"
		"- A request that points at something with this, that or it (\"adapt this logic\", \"fix it\") "
		"while no script is linked and nothing else in the request says what is meant is DISAMBIGUATE: "
		"there is nothing for it to point at."
	),
	"logix_agent": (
		"\n\nA question from the person is never a reason to call clarify. When next is write_script, "
		"call write_script even for a question: it answers questions in plain words."
	),
	"logix_script_writer": (
		"\n\nQUESTIONS:\nWhen the person asks about the linked script (what it does, why it failed) and "
		"asks for no change, answer in two or three plain sentences and write no code block. Do not "
		"rewrite the script."
	),
}


def execute():
	for agent_id, rule in RULES.items():
		name, prompt = frappe.db.get_value(
			"AI Agent Configuration", {"agent_id": agent_id}, ["name", "system_prompt"]
		) or (None, None)
		if not name or rule.strip() in (prompt or ""):
			continue
		frappe.db.set_value("AI Agent Configuration", name, "system_prompt", (prompt or "").rstrip() + rule)
