# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
import frappe
from frappe.tests.utils import FrappeTestCase


class TestChatMessageFields(FrappeTestCase):
	def test_is_reply_is_not_a_field(self):
		fieldnames = [df.fieldname for df in frappe.get_meta("Chat Message").fields]
		self.assertNotIn("is_reply", fieldnames)

	def test_is_reply_column_is_dropped(self):
		self.assertFalse(frappe.db.has_column("Chat Message", "is_reply"))
