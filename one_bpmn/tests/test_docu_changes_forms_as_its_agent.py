# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Docu changes forms as its own agent user, for anyone the Docu Agent admits."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.docu_api import (
	DOCU_AGENT,
	_docu_user,
	apply_doctype,
	build_docu_turn_context,
	can_change_forms,
)

DT = "Docu Agent Identity Probe"
PROBE_USER = "docu.identity.probe@example.com"
ROLE = "Process Owner"


class TestDocuChangesFormsAsItsAgent(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("AI Agent Configuration", DOCU_AGENT):
			self.skipTest("no Docu Agent configuration on this site")
		if _docu_user() == "Administrator":
			self.skipTest("the Docu Agent has no user provisioned")
		frappe.set_user("Administrator")
		if not frappe.db.exists("User", PROBE_USER):
			frappe.get_doc(
				{"doctype": "User", "email": PROBE_USER, "first_name": "Docu Probe", "send_welcome_email": 0}
			).insert()
		frappe.get_doc("User", PROBE_USER).add_roles(ROLE)
		self.addCleanup(self._clean)

	def _clean(self):
		frappe.set_user("Administrator")
		if frappe.db.exists("DocType", DT):
			frappe.delete_doc("DocType", DT, force=True)
		frappe.db.delete("AI Agent Allowed Role", {"parent": DOCU_AGENT, "role": ROLE})
		frappe.delete_doc("User", PROBE_USER, force=True)
		frappe.db.commit()

	def _admit_role(self):
		config = frappe.get_doc("AI Agent Configuration", DOCU_AGENT)
		config.append("allowed_roles", {"role": ROLE})
		config.db_update_all()

	def _apply(self):
		ir = {
			"doctype_name": DT,
			"module": "ONE BPMN",
			"fields": [{"fieldname": "subject", "fieldtype": "Data", "label": "Subject"}],
		}
		return apply_doctype(json.dumps(ir), confirm=1)

	def test_an_admitted_person_without_system_manager_creates_the_form_as_the_agent(self):
		self._admit_role()
		frappe.set_user(PROBE_USER)

		self._apply()

		self.assertEqual(frappe.db.get_value("DocType", DT, "owner"), _docu_user())
		self.assertEqual(frappe.session.user, PROBE_USER)

	def test_a_person_the_agent_does_not_admit_is_refused(self):
		frappe.set_user(PROBE_USER)

		self.assertFalse(can_change_forms())
		self.assertRaises(frappe.PermissionError, self._apply)
		self.assertFalse(frappe.db.exists("DocType", DT))

	def test_the_turn_context_carries_the_schema_for_a_person_who_cannot_read_doctypes(self):
		frappe.set_user(PROBE_USER)

		context = build_docu_turn_context({"doctype": "Note"})

		self.assertIn("CURRENT DOCTYPE ('Note')", context["dialog_context"])

	def test_the_patch_gives_the_docu_user_system_manager(self):
		from one_bpmn.one_bpmn.patches.v1_0.docu_agent_holds_system_manager import execute

		frappe.set_user("Administrator")
		execute()

		self.assertIn("System Manager", frappe.get_roles(_docu_user()))
