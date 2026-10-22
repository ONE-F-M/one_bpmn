# Copyright (c) 2026, one-fm and contributors
# WI-003702: Review Doctypes / Sync must carry Client Scripts alongside Custom
# Fields and Property Setters.
#
# AC2 - the review diff reports Client Script differences.
# AC3 - the generated patch applies Client Scripts, the same way it applies the
#       Custom Fields and Property Setters.
# (AC1, the preliminary message, lives in spiff/src/views/Editor.vue - front end,
# not covered here.)

from __future__ import annotations

import ast

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import onefm_customization_codegen as gen
from one_bpmn.api.production_review import _build_doctype_snapshot, _diff_doctypes

SCRIPT_A = "frappe.ui.form.on('Demo DT', { refresh(frm) {} });"
SCRIPT_B = "frappe.ui.form.on('Demo DT', { refresh(frm) { frm.disable_save(); } });"


def _snap(client_scripts=None, include_key=True):
	dt_snap = {"exists": True, "custom": 0, "custom_fields": {}, "property_setters": {}, "docfields": {}}
	if include_key:
		dt_snap["client_scripts"] = client_scripts or {}
	return {"Demo DT": dt_snap}


def _cs(script=SCRIPT_A, enabled=1):
	return {"name": "Demo DT Form", "dt": "Demo DT", "view": "Form", "enabled": enabled, "script": script}


class TestClientScriptReview(FrappeTestCase):
	def test_a_client_script_missing_on_production_is_a_create(self):
		changes = _diff_doctypes(_snap({"Demo DT Form": _cs()}), _snap({}))

		self.assertEqual(len(changes), 1, msg=f"got {changes}")
		c = changes[0]
		self.assertEqual(c["object_type"], "Client Script")
		self.assertEqual(c["action"], "Create")
		self.assertEqual(c["name"], "Demo DT Form")
		self.assertEqual(c["doctype"], "Demo DT")

	def test_a_changed_client_script_is_an_update_naming_the_key(self):
		changes = _diff_doctypes(
			_snap({"Demo DT Form": _cs(SCRIPT_B)}), _snap({"Demo DT Form": _cs(SCRIPT_A)})
		)

		self.assertEqual(len(changes), 1)
		self.assertEqual(changes[0]["action"], "Update")
		self.assertEqual(changes[0]["detail"], "script")

	def test_identical_client_scripts_are_not_a_change(self):
		same = {"Demo DT Form": _cs()}
		self.assertEqual(_diff_doctypes(_snap(same), _snap(dict(same))), [])

	def test_a_production_without_the_key_reports_no_client_script_drift(self):
		"""Absent must not read as empty (an older Production has no such key)."""
		changes = _diff_doctypes(_snap({"Demo DT Form": _cs()}), _snap(include_key=False))
		self.assertEqual(changes, [])

	def test_client_script_rows_never_claim_a_doctype_json_destination(self):
		from unittest import mock

		with mock.patch("one_bpmn.api.production_review._sync_destination", return_value="x/demo_dt.json"):
			changes = _diff_doctypes(_snap({"Demo DT Form": _cs()}), _snap({}))

		self.assertEqual(changes[0]["object_type"], "Client Script")
		self.assertEqual(changes[0]["destination"], "")

	def test_snapshot_carries_client_scripts_keyed_by_name(self):
		name = f"ZZ WI003702 {frappe.generate_hash(length=6)}"
		frappe.get_doc({
			"doctype": "Client Script", "__newname": name, "name": name, "dt": "ToDo",
			"view": "Form", "enabled": 0, "script": "// wi-003702",
		}).insert(ignore_permissions=True)

		snap = _build_doctype_snapshot(["ToDo"])["ToDo"]

		self.assertIn(name, snap["client_scripts"])
		rec = snap["client_scripts"][name]
		self.assertEqual(rec["script"], "// wi-003702")
		self.assertNotIn("modified", rec)


class TestClientScriptModule(FrappeTestCase):
	RECORDS = [
		{"name": "B Script", "dt": "Employee", "view": "Form", "enabled": 1, "script": "// b",
		 "modified": "2026-01-01", "owner": "Administrator"},
		{"name": "A Script", "dt": "Employee", "view": "List", "enabled": 0, "script": "// a \"q\"\n"},
	]

	def _emitted(self):
		src = gen.render_client_script_module("Employee", self.RECORDS)
		scope = {}
		exec(compile(src, "<generated>", "exec"), scope)
		return src, scope["get_employee_client_scripts"]()

	def test_getter_name(self):
		self.assertEqual(gen.getter_name("Employee", "client_script"), "get_employee_client_scripts")
		self.assertEqual(gen.getter_name("Employee", "custom_field"), "get_employee_custom_fields")
		self.assertEqual(gen.getter_name("Employee", "property_setter"), "get_employee_properties")

	def test_module_path(self):
		self.assertEqual(
			gen.module_path("one_fm", "Employee", "client_script"), "one_fm/custom/client_script/employee.py"
		)

	def test_module_is_importable_pruned_and_sorted(self):
		_, result = self._emitted()
		self.assertEqual([r["name"] for r in result], ["A Script", "B Script"])
		for rec in result:
			self.assertEqual(set(rec), {"name", "dt", "view", "enabled", "script"})
		self.assertEqual(result[0]["script"], '// a "q"\n')


class TestPatchAppliesClientScripts(FrappeTestCase):
	def test_patch_calls_the_client_script_getter(self):
		src = gen.render_patch("one_fm", "My Map", ["Interview"], "abc123", ["Interview", "Employee"])
		ast.parse(src)

		self.assertEqual(src.count("def execute():"), 1)
		self.assertIn("from one_fm.custom.client_script.employee import get_employee_client_scripts", src)
		self.assertIn("add_client_script(get_employee_client_scripts())", src)
		self.assertIn("add_client_script(get_interview_client_scripts())", src)
		# Existing behaviour is kept alongside.
		self.assertIn("create_custom_fields(get_interview_custom_fields(), update=True)", src)
		self.assertIn("add_property_setter(get_interview_properties())", src)

	def test_patch_for_client_scripts_only_is_valid_and_has_no_custom_field_calls(self):
		src = gen.render_patch("one_fm", "My Map", [], "abc123", ["Employee"])
		ast.parse(src)

		self.assertIn("add_client_script(get_employee_client_scripts())", src)
		self.assertNotIn("create_custom_fields", src)
		self.assertNotIn("add_property_setter", src)

	def test_patch_without_client_scripts_is_unchanged_in_shape(self):
		src = gen.render_patch("one_fm", "My Map", ["Interview"], "abc123")
		ast.parse(src)

		self.assertNotIn("add_client_script", src)
		self.assertNotIn("import frappe\n", src)

	def test_the_generated_upsert_creates_then_updates(self):
		name = f"ZZ WI003702 patch {frappe.generate_hash(length=6)}"
		src = gen.render_patch("one_fm", "My Map", [], "abc123", ["ToDo"])
		# Run only the helper, not the module (its import of one_fm data is not here).
		scope = {"frappe": frappe}
		helper = gen._CLIENT_SCRIPT_HELPER
		exec(compile(helper, "<helper>", "exec"), scope)
		self.assertIn(helper, src)

		rec = {"name": name, "dt": "ToDo", "view": "Form", "enabled": 0, "script": "// one"}
		scope["add_client_script"]([rec])
		self.assertEqual(frappe.db.get_value("Client Script", name, "script"), "// one")

		scope["add_client_script"]([{**rec, "script": "// two"}])
		self.assertEqual(frappe.db.get_value("Client Script", name, "script"), "// two")
		self.assertEqual(frappe.db.count("Client Script", {"name": name}), 1)
