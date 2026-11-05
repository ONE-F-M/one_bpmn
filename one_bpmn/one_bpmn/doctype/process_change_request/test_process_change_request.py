# Copyright (c) 2026, ONE FM and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestProcessChangeRequest(FrappeTestCase):
	def test_owned_by_one_bpmn(self):
		for doctype in ("Process Change Request", "Pathfinder Log Change Request"):
			with self.subTest(doctype=doctype):
				self.assertEqual(frappe.get_meta(doctype).module, "ONE BPMN")

	def test_ticket_link_does_not_need_helpdesk(self):
		for doctype in ("Process Change Request", "Pathfinder Log Change Request"):
			with self.subTest(doctype=doctype):
				meta = frappe.get_meta(doctype)
				self.assertEqual(meta.get_field("hd_ticket").fieldtype, "Dynamic Link")
				self.assertEqual(meta.get_field("hd_ticket").options, "hd_ticket_doctype")
				self.assertEqual(meta.get_field("hd_ticket_doctype").default, "HD Ticket")
