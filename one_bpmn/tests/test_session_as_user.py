# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The session a user switch borrows has to come back whole.

``frappe.set_user`` rewrites ``session.sid`` and empties ``session.data``, and
end-of-request persistence then writes that gutted dict back under the browser's
real cookie sid — so every following request dies with "User None is disabled".
A restore that puts the user back and nothing else is what caused that, which is
why these assert the sid and the data, not just the user.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.utils.session import as_user


class TestAsUser(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# What a resumed browser session looks like: a hashed sid, and a data dict
		# carrying the user.
		frappe.session.sid = "sid_under_test"
		frappe.session.data = frappe._dict({"user": "Administrator", "lang": "en"})

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_session_survives_a_switch(self):
		with as_user("Guest"):
			self.assertEqual(frappe.session.user, "Guest")

		self.assertEqual(frappe.session.user, "Administrator")
		self.assertEqual(frappe.session.sid, "sid_under_test")
		self.assertEqual(frappe.session.data.user, "Administrator")

	def test_session_survives_a_raising_block(self):
		with self.assertRaises(ValueError):
			with as_user("Guest"):
				raise ValueError("the block failed")

		self.assertEqual(frappe.session.user, "Administrator")
		self.assertEqual(frappe.session.sid, "sid_under_test")
		self.assertEqual(frappe.session.data.user, "Administrator")

	def test_no_user_and_same_user_leave_the_session_alone(self):
		for target in (None, "", "Administrator"):
			with as_user(target):
				self.assertEqual(frappe.session.user, "Administrator")
			self.assertEqual(frappe.session.sid, "sid_under_test")
			self.assertEqual(frappe.session.data.user, "Administrator")
