# Copyright (c) 2026, kartiksharma9319@gmail.com and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestContingencyTaskCompletion(FrappeTestCase):
	def test_requester_defaults_to_the_session_user(self):
		doc = frappe.new_doc("Contingency Task Completion")
		doc.run_method("before_insert")
		self.assertEqual(doc.process_owner_user, frappe.session.user)

	def test_approver_is_a_required_user(self):
		field = frappe.get_meta("Contingency Task Completion").get_field("reports_to_user")
		self.assertEqual(field.options, "User")
		self.assertTrue(field.reqd)
		self.assertFalse(field.fetch_from)
