# Copyright (c) 2026, ONE FM and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestProcessChangeRequest(FrappeTestCase):
	def test_owned_by_one_bpmn(self):
		self.assertEqual(frappe.get_meta("Process Change Request").module, "ONE BPMN")

	def test_ticket_link_does_not_need_helpdesk(self):
		meta = frappe.get_meta("Process Change Request")
		self.assertEqual(meta.get_field("hd_ticket").fieldtype, "Dynamic Link")
		self.assertEqual(meta.get_field("hd_ticket").options, "hd_ticket_doctype")
		self.assertEqual(meta.get_field("hd_ticket_doctype").default, "HD Ticket")

	def test_process_implementation_has_no_change_request_table(self):
		self.assertIsNone(frappe.get_meta("Process Implementation").get_field("change_requests"))
