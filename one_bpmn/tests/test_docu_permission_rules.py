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
		self.assertIn("already has a rule", " ".join(verdict["violations"]))

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
