"""Docu Baseline's child-table case asks for a new DocType, so the duplicate check is not what it measures."""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_docu_baseline_cases import CASES

TITLE = "A list of parts with a quantity each becomes a child table"
OLD_PROMPT = (
	"A record for a vehicle service visit: the vehicle, the date, the mechanic, and a list of "
	"the parts used with the quantity of each"
)


def execute():
	prompt = next(c["prompt"] for c in CASES if c["title"] == TITLE)
	for name in frappe.get_all(
		"AI Eval Case", filters={"title": TITLE, "input_user_prompt": OLD_PROMPT}, pluck="name"
	):
		frappe.db.set_value("AI Eval Case", name, "input_user_prompt", prompt)
