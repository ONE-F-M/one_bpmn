"""Docu's baseline suite gains a help text case and a case that edits an existing child table.

The child table case runs on a custom DocType of its own, so no standard table is changed. Idempotent by suite and case title.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_docu_baseline_cases import (
	AGENT_ID,
	DESIGN_TRACE,
	IN_ORDER,
	_judge,
	_regex,
	_suite,
	upsert_case,
)

TABLE_PROBE = "Docu Eval Table Probe"
TABLE_PROBE_CHILD = f"{TABLE_PROBE} Item"

CASES = [
	{
		"title": "Help text under a field is its description and not its label",
		"prompt": (
			"Create a Site Note DocType with a Contract Number field and show the help text "
			"'Use the number on the signed contract' under it."
		),
		"trace": DESIGN_TRACE,
		"assertions": [
			IN_ORDER,
			_regex(r'"description": "Use the number on the signed contract"'),
			_judge(
				"In the DocType definition after the reply, the Contract Number field carries the help text "
				"in its description and its label is still Contract Number. Score 5 when both hold, 1 when "
				"the help text is in the label or is missing."
			),
		],
	},
	{
		"title": "A column added to an existing child table keeps the columns it has",
		"prompt": "Add a Supplier column to the Items table.",
		"context": {"doctype": TABLE_PROBE},
		"trace": DESIGN_TRACE,
		"assertions": [
			IN_ORDER,
			_regex(rf'"options": "{TABLE_PROBE_CHILD}"'),
			_regex(r'"fieldname": "supplier"'),
			_regex(r'"fieldname": "part"'),
			_judge(
				"The definition after the reply keeps the Items table pointing at its existing child DocType "
				"and lists a new Supplier column besides the existing part and qty columns. Score 5 when all "
				"hold, 1 when the table was renamed, recreated or lost a column."
			),
		],
	},
]


def execute():
	agent, process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": AGENT_ID}, ["name", "process_model"]
	) or (None, None)
	if not agent or not process_model:
		return

	ensure_table_probe()
	suite = _suite(agent, process_model)
	for spec in CASES:
		upsert_case(suite, process_model, spec)


def ensure_table_probe() -> None:
	if frappe.db.exists("DocType", TABLE_PROBE):
		return
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": TABLE_PROBE_CHILD,
			"module": "ONE BPMN",
			"custom": 1,
			"istable": 1,
			"fields": [
				{"fieldname": "part", "fieldtype": "Data", "label": "Part", "in_list_view": 1},
				{"fieldname": "qty", "fieldtype": "Int", "label": "Qty", "in_list_view": 1},
			],
		}
	).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": TABLE_PROBE,
			"module": "ONE BPMN",
			"custom": 1,
			"fields": [
				{"fieldname": "title", "fieldtype": "Data", "label": "Title"},
				{"fieldname": "items", "fieldtype": "Table", "label": "Items", "options": TABLE_PROBE_CHILD},
			],
			"permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1}],
		}
	).insert(ignore_permissions=True)
