# Copyright (c) 2026, one-fm and contributors
"""Docu applies column changes to an existing custom child table and leaves standard ones alone."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.api.docu_api import apply_doctype, preview_doctype
from one_bpmn.one_bpmn.patches.v1_0 import inline_docu_tool_scripts

PARENT = "Docu Child Change Probe"
CHILD = f"{PARENT} Rows Item"
STANDARD_CHILD = "Has Role"


def _ir(columns, options=CHILD):
	return json.dumps(
		{
			"doctype_name": PARENT,
			"fields": [
				{"fieldname": "title", "fieldtype": "Data", "label": "Title"},
				{"fieldname": "rows", "fieldtype": "Table", "label": "Rows", "options": options, "child_fields": columns},
			],
		}
	)


NOTE = {"fieldname": "note", "fieldtype": "Data", "label": "Note"}
AMOUNT = {"fieldname": "amount", "fieldtype": "Data", "label": "Amount"}
RELABELLED = [{**NOTE, "label": "Remark"}, AMOUNT, {"fieldname": "apply", "fieldtype": "Check", "label": "Apply"}]


class TestChildTableChanges(FrappeTestCase):
	def setUp(self):
		apply_doctype(_ir([NOTE, AMOUNT]), confirm=1)
		frappe.get_doc({"doctype": PARENT, "title": "t", "rows": [{"note": "kept", "amount": "5"}]}).insert()

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in (PARENT, CHILD):
			frappe.delete_doc("DocType", name, force=True, ignore_permissions=True)
		frappe.db.commit()

	def test_relabel_and_added_check_column_keep_existing_rows(self):
		apply_doctype(_ir(RELABELLED), confirm=1)
		meta = frappe.get_meta(CHILD, cached=False)
		self.assertEqual(meta.get_field("note").label, "Remark")
		self.assertEqual(meta.get_field("apply").fieldtype, "Check")
		self.assertEqual(frappe.db.get_value(CHILD, {"parenttype": PARENT}, "note"), "kept")

	def test_preview_lists_each_child_change(self):
		out = preview_doctype(_ir(RELABELLED))
		self.assertEqual(out["child_changes"][0]["table"], CHILD)
		self.assertEqual(
			out["child_changes"][0]["lines"], ["Adds column Apply.", "Renames column Note to Remark."]
		)

	def test_removing_a_column_needs_confirmation(self):
		with self.assertRaises(frappe.ValidationError):
			apply_doctype(_ir([NOTE]), confirm=0)
		self.assertTrue(frappe.get_meta(CHILD, cached=False).get_field("amount"))

	def test_a_standard_child_is_unchanged_and_the_user_is_told(self):
		columns = [{"fieldname": "role", "fieldtype": "Link", "label": "Renamed Role", "options": "Role"}]
		result = apply_doctype(_ir(columns, options=STANDARD_CHILD), confirm=1)
		self.assertNotEqual(frappe.get_meta(STANDARD_CHILD, cached=False).get_field("role").label, "Renamed Role")
		self.assertIn("Has Role is a standard table, so Docu cannot change its columns.", result["notes"])

	def test_a_user_who_may_not_change_forms_changes_nothing(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			apply_doctype(_ir(RELABELLED), confirm=1)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.get_meta(CHILD, cached=False).get_field("note").label, "Note")


class TestReplyWarnsAboutStandardTable(FrappeTestCase):
	CONVERSATION = "_test_docu_standard_child_warning"

	def tearDown(self):
		clear_turn(self.CONVERSATION)

	def test_the_reply_text_carries_the_warning(self):
		warning = "Has Role is a standard table, so Docu cannot change its columns."
		set_turn(
			self.CONVERSATION,
			{
				"intent": "CREATE",
				"schema_safe": True,
				"final_text": "Done.",
				"final_ir": {"doctype_name": PARENT},
				"warnings": [warning],
			},
		)
		exec(inline_docu_tool_scripts.FINALIZE, {"context_docname": self.CONVERSATION, "result": {}})
		self.assertEqual(get_turn(self.CONVERSATION)["output"]["response"], f"Done.\n\n{warning}")
