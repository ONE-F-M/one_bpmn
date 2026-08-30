# Copyright (c) 2026, one-fm and contributors
"""Choosing who a notification service task sends to.

The recipient picker used to be built from a fieldtype filter over the raw
schema, which was wrong in both directions at once: it offered every Data and
Link field on the doctype — Place of Birth, Passport Number — while being
structurally incapable of offering ``owner``, because the standard columns are
real columns on every table but are absent from ``meta.fields``. On a doctype
with no user or email field of its own, ``owner`` is the only possible
recipient, so the one field that worked was the one field you could not pick.

These tests pin both halves: what the picker offers, and that a chosen user
field actually delivers. The second half matters as much as the first — a
recipient that resolves to nothing is worse than one that was never offered,
because the run reports success and no email arrives.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.utils import get_recipient_docfields
from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import (
	_emails_from_doc_field,
)


class TestRecipientFieldPicker(FrappeTestCase):
	def _names(self, doctype, search_text=""):
		return [r["fieldname"] for r in get_recipient_docfields(doctype, search_text)]

	def test_owner_is_offered_on_every_doctype(self):
		"""The whole point. ``owner`` is on every table and was previously
		unreachable, so a doctype holding no user field of its own had no
		selectable recipient at all."""
		for doctype in ("ToDo", "User", "Note"):
			with self.subTest(doctype=doctype):
				self.assertIn("owner", self._names(doctype))

	def test_owner_is_listed_first(self):
		"""On many doctypes it is the only workable answer, so it should not be
		somewhere down a scrolling list."""
		self.assertEqual(self._names("ToDo")[0], "owner")

	def test_modified_by_is_offered_too(self):
		self.assertIn("modified_by", self._names("ToDo"))

	def test_user_link_fields_are_offered(self):
		"""A Link to User names a person, so it names a recipient."""
		names = self._names("ToDo")
		self.assertIn("allocated_to", names)
		self.assertIn("assigned_by", names)

	def test_email_fields_are_offered(self):
		self.assertIn("email", self._names("User"))

	def test_fields_that_cannot_hold_a_recipient_are_not_offered(self):
		"""The noise half of the complaint. A Link to some other doctype is a
		key, not a person — offering it buried the fields that work."""
		names = self._names("ToDo")
		self.assertNotIn("reference_type", names)
		self.assertNotIn("description", names)
		self.assertNotIn("status", names)

	def test_a_field_that_merely_mentions_email_is_not_a_recipient(self):
		"""``email_signature`` matches on name but holds prose, not an address.
		The name is only trusted for short field types for this reason."""
		self.assertNotIn("email_signature", self._names("User"))

	def test_custom_fields_are_offered(self):
		"""The blind spot in the old implementation, and the reason it could not
		simply be given a better filter: it read the DocField table, where
		Custom Fields do not live. A site that adds an email field by
		customisation could never pick it."""
		field = frappe.get_doc({
			"doctype": "Custom Field",
			"dt": "ToDo",
			"fieldname": "custom_test_notify_email",
			"label": "Notify Email",
			"fieldtype": "Data",
			"options": "Email",
		}).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc(
			"Custom Field", field.name, force=True, ignore_permissions=True
		))
		frappe.clear_cache(doctype="ToDo")

		self.assertIn("custom_test_notify_email", self._names("ToDo"))

	def test_each_field_says_which_kind_it_is(self):
		"""A user field is resolved to that user's address at send time and an
		email field is used as-is. The picker shows the difference so ``owner``
		reads as a deliberate choice rather than a mistake."""
		by_name = {r["fieldname"]: r for r in get_recipient_docfields("ToDo")}
		self.assertEqual(by_name["owner"]["kind"], "user")
		self.assertEqual(by_name["allocated_to"]["kind"], "user")
		self.assertEqual(by_name["sender"]["kind"], "email")

	def test_search_filters_on_name_and_label(self):
		self.assertEqual(self._names("ToDo", "owner"), ["owner"])
		self.assertNotIn("owner", self._names("ToDo", "allocated"))

	def test_an_unusable_doctype_is_empty_not_an_error(self):
		"""The picker asks before the modeller has necessarily chosen a doctype,
		so a blank or bad name must come back empty rather than throwing."""
		self.assertEqual(get_recipient_docfields(""), [])
		self.assertEqual(get_recipient_docfields("No Such DocType At All"), [])


class TestRecipientResolution(FrappeTestCase):
	"""What the dispatcher does with the field value it was given."""

	def test_an_address_is_used_as_is(self):
		self.assertEqual(_emails_from_doc_field("a@b.com"), ["a@b.com"])

	def test_a_user_id_resolves_to_that_users_email(self):
		"""The bug that made ``owner`` unusable even once it was pickable.
		Administrator's id has no "@", so the old "@"-only test dropped it and
		the task logged "no recipients resolved" while looking correctly set up.
		"""
		expected = frappe.db.get_value("User", "Administrator", "email")
		self.assertTrue(expected, "Administrator has no email on this site")
		self.assertEqual(_emails_from_doc_field("Administrator"), [expected])

	def test_several_addresses_in_one_field(self):
		self.assertEqual(
			_emails_from_doc_field("a@b.com, c@d.com"), ["a@b.com", "c@d.com"]
		)

	def test_users_and_addresses_can_mix(self):
		admin = frappe.db.get_value("User", "Administrator", "email")
		self.assertEqual(
			_emails_from_doc_field("Administrator, a@b.com"), [admin, "a@b.com"]
		)

	def test_a_value_that_is_neither_yields_nothing(self):
		"""A Link to some other doctype resolves to no user and no address. It is
		skipped rather than sent to, and must not raise."""
		self.assertEqual(_emails_from_doc_field("Some Nationality"), [])

	def test_empty_values_yield_nothing(self):
		for value in (None, "", "   ", 0):
			with self.subTest(value=value):
				self.assertEqual(_emails_from_doc_field(value), [])
