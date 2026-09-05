"""ProsAlly learns that some processes cannot be drawn without a crossing line.

The compiler now reports ``non-planar`` when the flow graph has no crossing-free
drawing. Without this, the generator and modifier kept regenerating in search of
a layout that cannot exist, and the confirmer promised a clean canvas it could
not deliver.
"""
import frappe

MARK = "=== TOPOLOGY ==="

TEXTS = {
	"process_generator": (
		"\n\n=== TOPOLOGY ===\n"
		"The compiler checks whether the flow graph can be drawn with no crossing lines. "
		"A [non-planar] problem means no layout can remove the crossing — do not regenerate to chase one. "
		"When a returning flow can join at an existing merge gateway with the same behaviour, join there "
		"rather than at the task after it; that keeps the graph flat more often."
	),
	"modifier": (
		"\n\n=== TOPOLOGY ===\n"
		"Adding a connection can make a process impossible to draw without a crossing line. "
		"If the compiler reports [non-planar], keep the IR and say in one sentence which two paths force "
		"the crossing and that one crossing is the minimum. Prefer joining a new flow at an existing merge "
		"gateway when the behaviour is the same."
	),
	"confirmer": (
		"\n\n=== TOPOLOGY ===\n"
		"If the compiler reported the process as non-planar, say before asking to apply that the change "
		"introduces one unavoidable crossing line."
	),
}


def execute():
	for sub_agent_id, text in TEXTS.items():
		rows = frappe.get_all(
			"AI Agent Sub Prompt",
			filters={"parent": "prosally", "sub_agent_id": sub_agent_id},
			pluck="name",
		)
		for name in rows:
			current = frappe.db.get_value("AI Agent Sub Prompt", name, "prompt_text") or ""
			if MARK in current:
				continue
			frappe.db.set_value(
				"AI Agent Sub Prompt", name, "prompt_text", current.rstrip() + text, update_modified=False
			)
