"""Docu's baseline suite gains the edit command cases: add a field, hide a section on a checkbox, remove fields, change a field's type, and a vague edit that is asked about.

The edits apply to a probe DocType that keeps the result between runs, so each check also accepts the reply a repeat run gives. Idempotent by suite and case title.
"""

import frappe

from processa.patches.v1_0.seed_docu_baseline_cases import (
	AGENT_ID,
	CLARIFY_TRACE,
	DESIGNS_NOTHING,
	IN_ORDER,
	PROPERTY_TRACE,
	_regex,
	_suite,
	upsert_case,
)

EDIT_PROBE = "Docu Eval Edit Probe"
ON_EDIT_PROBE = {"doctype": EDIT_PROBE}
NO_GREETING = _regex(r"^(?![\s\S]*I build DocTypes)")

CASES = [
	{
		"title": "An add-a-field command adds the field to the form directly",
		"prompt": "Add a Phone field after the Office Address field.",
		"context": ON_EDIT_PROBE,
		"trace": PROPERTY_TRACE,
		"assertions": [
			IN_ORDER,
			DESIGNS_NOTHING,
			NO_GREETING,
			_regex(r"Added Phone|Phone is already on the form"),
		],
	},
	{
		"title": "Hiding a section when a checkbox is ticked sets a display condition on the section",
		"prompt": "Hide the Office Details section when Is Remote is ticked.",
		"context": ON_EDIT_PROBE,
		"trace": PROPERTY_TRACE,
		"assertions": [
			IN_ORDER,
			DESIGNS_NOTHING,
			NO_GREETING,
			_regex(r"Office Details[\s\S]*eval:!doc\.is_remote"),
		],
	},
	{
		"title": "A remove-fields command removes each named field",
		"prompt": "Remove the Fax and Telex fields from this form.",
		"context": ON_EDIT_PROBE,
		"trace": PROPERTY_TRACE,
		"assertions": [
			IN_ORDER,
			DESIGNS_NOTHING,
			NO_GREETING,
			_regex(r"Removed Fax|fax is not on the form"),
			_regex(r"Removed Telex|telex is not on the form"),
		],
	},
	{
		"title": "Changing a checkbox to a dropdown changes the field's type",
		"prompt": "Change the Done checkbox to a dropdown.",
		"context": ON_EDIT_PROBE,
		"trace": PROPERTY_TRACE,
		"assertions": [
			IN_ORDER,
			DESIGNS_NOTHING,
			NO_GREETING,
			_regex(r"Changed Done from Check to Select|Done is already a Select field"),
		],
	},
	{
		"title": "An edit that names nothing is asked about, not greeted",
		"prompt": "Change it.",
		"context": ON_EDIT_PROBE,
		"trace": CLARIFY_TRACE,
		"assertions": [IN_ORDER, DESIGNS_NOTHING, NO_GREETING],
	},
]


def execute():
	agent, process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": AGENT_ID}, ["name", "process_model"]
	) or (None, None)
	if not agent or not process_model:
		return

	_ensure_edit_probe()
	suite = _suite(agent, process_model)
	for spec in CASES:
		upsert_case(suite, process_model, spec)


def _ensure_edit_probe() -> None:
	"""A custom DocType with a checkbox, a section, two fields to remove and a checkbox to retype."""
	if frappe.db.exists("DocType", EDIT_PROBE):
		return
	frappe.get_doc(
		{
			"doctype": "DocType",
			"name": EDIT_PROBE,
			"module": "Processa Engine",
			"custom": 1,
			"fields": [
				{"fieldname": "title", "fieldtype": "Data", "label": "Title"},
				{"fieldname": "is_remote", "fieldtype": "Check", "label": "Is Remote"},
				{"fieldname": "office_section", "fieldtype": "Section Break", "label": "Office Details"},
				{"fieldname": "office_address", "fieldtype": "Data", "label": "Office Address"},
				{"fieldname": "fax", "fieldtype": "Data", "label": "Fax"},
				{"fieldname": "telex", "fieldtype": "Data", "label": "Telex"},
				{"fieldname": "done", "fieldtype": "Check", "label": "Done"},
			],
			"permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1}],
		}
	).insert(ignore_permissions=True)
