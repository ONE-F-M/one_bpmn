# Copyright (c) 2026, ONE FM and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestProcessCreationRequest(FrappeTestCase):
	def test_owned_by_one_bpmn(self):
		self.assertEqual(frappe.get_meta("Process Creation Request").module, "ONE BPMN")
