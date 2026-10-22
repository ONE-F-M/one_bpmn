# Copyright (c) 2026, one-fm and contributors
"""Docu creates and updates the List View Client Script on a DocType, behind a safety gate."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.docu_api import apply_list_view_script, get_list_view_script
from one_bpmn.security.client_script_validator import MAX_SCRIPT_LENGTH, validate_list_view_script

DOCTYPE = "Note"
SCRIPT = 'frappe.listview_settings["Note"] = { add_fields: ["public"], hide_name_column: true };'
NEXT_SCRIPT = 'frappe.listview_settings["Note"] = { add_fields: ["public", "seen_by"] };'
NO_ROLE_USER = "docu-list-script-probe@example.com"


class TestValidateListViewScript(FrappeTestCase):
	def test_a_script_for_the_named_list_passes(self):
		self.assertEqual(validate_list_view_script(DOCTYPE, SCRIPT), [])

	def test_an_ordinary_function_in_a_setting_passes(self):
		script = 'frappe.listview_settings["Note"] = { get_indicator: function(doc) { return [__("Open"), "blue"]; } };'
		self.assertEqual(validate_list_view_script(DOCTYPE, script), [])
		self.assertTrue(validate_list_view_script(DOCTYPE, script + "\nnew Function('1')"))

	def test_an_empty_script_is_refused(self):
		self.assertEqual(len(validate_list_view_script(DOCTYPE, "  ")), 1)

	def test_a_script_for_another_doctype_is_refused(self):
		problems = validate_list_view_script(DOCTYPE, 'frappe.listview_settings["ToDo"] = {};')
		self.assertIn("only change the list of Note", problems[0])

	def test_a_script_that_sets_no_list_settings_is_refused(self):
		self.assertIn("must set frappe.listview_settings", validate_list_view_script(DOCTYPE, "var x = 1;")[0])

	def test_network_and_code_loading_are_refused(self):
		for unsafe in (
			'fetch("/api/method/x")',
			"eval('1')",
			'document.cookie = "a"',
			'window.location = "/x"',
			'var s = "https://evil.example/x.js"',
		):
			script = SCRIPT + "\n" + unsafe
			self.assertTrue(validate_list_view_script(DOCTYPE, script), unsafe)

	def test_an_oversized_script_is_refused(self):
		padded = SCRIPT + "\n// " + "x" * MAX_SCRIPT_LENGTH
		self.assertIn(str(MAX_SCRIPT_LENGTH), validate_list_view_script(DOCTYPE, padded)[0])


class TestApplyListViewScript(FrappeTestCase):
	def setUp(self):
		frappe.db.savepoint("docu_list_script")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="docu_list_script")

	def test_a_new_script_is_created_as_a_list_script(self):
		result = apply_list_view_script(DOCTYPE, SCRIPT)
		self.assertEqual(result["action"], "created")
		row = frappe.db.get_value("Client Script", result["name"], ["dt", "view", "script", "enabled"], as_dict=True)
		self.assertEqual((row.dt, row.view, row.script, row.enabled), (DOCTYPE, "List", SCRIPT, 1))

	def test_a_second_apply_updates_the_same_script(self):
		first = apply_list_view_script(DOCTYPE, SCRIPT)
		second = apply_list_view_script(DOCTYPE, NEXT_SCRIPT)
		self.assertEqual(second["action"], "updated")
		self.assertEqual(second["name"], first["name"])
		self.assertEqual(get_list_view_script(DOCTYPE)["script"], NEXT_SCRIPT)

	def test_an_unsafe_script_writes_nothing(self):
		with self.assertRaises(frappe.ValidationError):
			apply_list_view_script(DOCTYPE, SCRIPT + '\nfetch("/x")')
		self.assertFalse(frappe.db.exists("Client Script", {"dt": DOCTYPE, "view": "List"}))

	def test_an_unknown_doctype_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			apply_list_view_script("No Such DocType", SCRIPT)

	def test_a_user_without_the_role_cannot_apply_or_read(self):
		if not frappe.db.exists("User", NO_ROLE_USER):
			frappe.get_doc({"doctype": "User", "email": NO_ROLE_USER, "first_name": "Probe", "send_welcome_email": 0}).insert(
				ignore_permissions=True
			)
		frappe.set_user(NO_ROLE_USER)
		with self.assertRaises(frappe.PermissionError):
			apply_list_view_script(DOCTYPE, SCRIPT)
		with self.assertRaises(frappe.PermissionError):
			get_list_view_script(DOCTYPE)

	def test_a_doctype_with_no_script_reads_back_empty(self):
		self.assertEqual(get_list_view_script(DOCTYPE), {"name": None, "script": "", "enabled": 0})
