# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Docu sets who may use a DocType, and never lets a bad rule through.

The risks worth a test are the quiet ones: a role that does not exist being
written anyway, an update wiping the rules it was not asked to touch, and a
round trip losing a right the builder does not display.
"""
import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.docu_api import apply_doctype, get_doctype_schema
from one_bpmn.security.doctype_validator import validate_doctype_ir

DT = "Docu Permission Rules Probe"


def _ir(**over):
	ir = {
		"doctype_name": DT,
		"module": "ONE BPMN",
		"fields": [{"fieldname": "subject", "fieldtype": "Data", "label": "Subject"}],
	}
	ir.update(over)
	return ir


class TestDocuPermissionRules(FrappeTestCase):
	def tearDown(self):
		if frappe.db.exists("DocType", DT):
			frappe.delete_doc("DocType", DT, force=True, ignore_permissions=True)

	def _apply(self, ir):
		return apply_doctype(json.dumps(ir), confirm=1)

	def _perms(self):
		return get_doctype_schema(DT)["doctype_ir"]["permissions"]

	def test_a_role_that_does_not_exist_is_refused(self):
		verdict = validate_doctype_ir(_ir(permissions=[{"role": "Keeper Of The Seal"}]))
		self.assertFalse(verdict["valid"])
		self.assertIn("Keeper Of The Seal", " ".join(verdict["violations"]))

	def test_the_same_role_twice_at_one_level_is_refused(self):
		rule = {"role": "System Manager", "permlevel": 0, "read": 1}
		verdict = validate_doctype_ir(_ir(permissions=[rule, dict(rule)]))
		self.assertFalse(verdict["valid"])
		self.assertIn("already has this rule", " ".join(verdict["violations"]))

	def test_frappes_own_owner_only_pairing_is_allowed(self):
		"""Note and Kanban Board ship two rules for one role at one level.

		They differ by if_owner: anyone may read, only the owner may edit.
		Rejecting that made the builder unable to save any DocType shaped this
		way — it read the real rules in and then refused to write them back.
		"""
		verdict = validate_doctype_ir(_ir(permissions=[
			{"role": "Desk User", "permlevel": 0, "if_owner": 0, "read": 1},
			{"role": "Desk User", "permlevel": 0, "if_owner": 1, "write": 1, "delete": 1},
		]))
		self.assertTrue(verdict["valid"], verdict["violations"])

	def test_a_real_doctype_can_be_read_and_written_back(self):
		"""The failure the builder actually hit: load an existing DocType's
		rules into the grid, change nothing, and the save is refused."""
		from one_bpmn.tools.tool_for_server_scripts import read_doctype_permissions

		live = read_doctype_permissions("Note")
		self.assertTrue(live, "Note should ship permission rules")
		verdict = validate_doctype_ir(_ir(permissions=live))
		self.assertTrue(verdict["valid"], verdict["violations"])

	def test_the_named_roles_are_written(self):
		self._apply(_ir(permissions=[
			{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
			{"role": "Projects User", "read": 1, "write": 1},
		]))
		got = {p["role"]: p for p in self._perms()}
		self.assertEqual(set(got), {"System Manager", "Projects User"})
		self.assertEqual(got["Projects User"]["write"], 1)
		self.assertEqual(got["Projects User"]["create"], 0)

	def test_an_ir_that_says_nothing_leaves_the_rules_alone(self):
		self._apply(_ir(permissions=[
			{"role": "System Manager", "read": 1, "write": 1},
			{"role": "Projects User", "read": 1},
		]))
		before = self._perms()
		self._apply(_ir())  # a later turn that only changed fields
		self.assertEqual(self._perms(), before)

	def test_a_right_the_builder_hides_survives_a_round_trip(self):
		# 'print' is carried in the IR but has no column in the grid.
		self._apply(_ir(permissions=[{"role": "System Manager", "read": 1, "print": 1}]))
		back = self._perms()
		self.assertEqual(back[0]["print"], 1)
		self._apply(_ir(permissions=back))
		self.assertEqual(self._perms(), back)

	def test_an_empty_list_still_leaves_someone_able_to_open_it(self):
		self._apply(_ir(permissions=[]))
		self.assertEqual([p["role"] for p in self._perms()], ["System Manager"])

	def test_a_child_table_carries_no_rules_of_its_own(self):
		self._apply(_ir(is_child_table=1, permissions=[{"role": "System Manager", "read": 1}]))
		self.assertEqual(self._perms(), [])

	def test_a_standard_doctype_gets_custom_docperm_rows(self):
		"""The path that silently dropped permissions.

		A standard DocType goes through Customize Form, which only handles
		fields, so the rules went nowhere and no error was raised. Its own
		DocPerm rows belong to the app that ships it, so the change has to land
		in Custom DocPerm instead.
		"""
		from one_bpmn.api.docu_api import _apply_standard_doctype_permissions

		self._apply(_ir())
		frappe.db.set_value("DocType", DT, "custom", 0)  # stand in for a shipped DocType
		try:
			_apply_standard_doctype_permissions(DT, [
				{"role": "System Manager", "read": 1, "write": 1},
				{"role": "Projects User", "read": 1},
			])
			rows = frappe.get_all(
				"Custom DocPerm", filters={"parent": DT}, fields=["role", "read", "write"]
			)
			by_role = {r["role"]: r for r in rows}
			self.assertEqual(set(by_role), {"System Manager", "Projects User"})
			self.assertEqual(by_role["Projects User"]["read"], 1)
			self.assertEqual(by_role["Projects User"]["write"], 0)
		finally:
			frappe.db.delete("Custom DocPerm", {"parent": DT})
			frappe.db.set_value("DocType", DT, "custom", 1)
