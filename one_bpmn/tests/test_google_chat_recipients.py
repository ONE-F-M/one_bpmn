# Copyright (c) 2026, one-fm and contributors
"""Who a Google Chat direct message goes to.

A DM used to name one address typed into the map, which meant a process could
only notify whoever was known when it was drawn. The recipient can now come off
the document the process is running on — a field, or a row of a child table —
the same three ways a User Task already picks an assignee.

Most of these are about the ways it can resolve to nobody, because that is
silent: a DM nobody receives looks exactly like a DM that was sent.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import (
	chat_user_id,
	dispatch_google_chat,
	google_chat_recipients,
)


def _instance(doctype="", docname=""):
	return frappe._dict(context_doctype=doctype, context_docname=docname, name="_test-instance")


class TestUserBasis(FrappeTestCase):
	"""The original behaviour, which has to keep working untouched."""

	def test_a_single_address_is_the_recipient(self):
		got, problem = google_chat_recipients(_instance(), {"gchatEmail": "someone@one-fm.com"})
		self.assertEqual(got, ["someone@one-fm.com"])
		self.assertFalse(problem)

	def test_a_map_drawn_before_this_still_works(self):
		"""An older map has no basis at all, and must not start failing."""
		got, _ = google_chat_recipients(_instance(), {"gchatEmail": "old@one-fm.com"})
		self.assertEqual(got, ["old@one-fm.com"])

	def test_several_addresses_can_be_named(self):
		got, _ = google_chat_recipients(
			_instance(), {"gchatRecipientBasis": "User", "gchatEmail": "a@one-fm.com, b@one-fm.com"}
		)
		self.assertEqual(got, ["a@one-fm.com", "b@one-fm.com"])

	def test_the_same_person_twice_is_messaged_once(self):
		got, _ = google_chat_recipients(
			_instance(), {"gchatEmail": "a@one-fm.com,a@one-fm.com"}
		)
		self.assertEqual(got, ["a@one-fm.com"])

	def test_naming_nobody_says_so(self):
		got, problem = google_chat_recipients(_instance(), {"gchatEmail": "  "})
		self.assertEqual(got, [])
		self.assertIn("gchatEmail is empty", problem)

	def test_a_basis_that_does_not_exist_is_refused(self):
		got, problem = google_chat_recipients(_instance(), {"gchatRecipientBasis": "Roles"})
		self.assertEqual(got, [])
		self.assertIn("not User, DocField or Table Field", problem)


class TestDocFieldBasis(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.user = frappe.db.get_value("User", {"enabled": 1, "user_type": "System User"}, "name")
		self.todo = frappe.get_doc({
			"doctype": "ToDo", "description": "_Test gchat recipient",
			"allocated_to": self.user,
		}).insert(ignore_permissions=True)

	def _cfg(self, field):
		return {"gchatRecipientBasis": "DocField", "gchatDocField": field}

	def test_a_user_linked_field_becomes_that_user_address(self):
		got, problem = google_chat_recipients(
			_instance("ToDo", self.todo.name), self._cfg("allocated_to")
		)
		self.assertFalse(problem)
		self.assertEqual(got, [frappe.db.get_value("User", self.user, "email") or self.user])

	def test_owner_is_available_like_any_other_field(self):
		"""owner is a real column on every table and is often the only
		recipient a doctype has."""
		got, _ = google_chat_recipients(_instance("ToDo", self.todo.name), self._cfg("owner"))
		self.assertEqual(got, [frappe.db.get_value("User", "Administrator", "email") or "Administrator"])

	def test_an_empty_field_is_reported_rather_than_sent_to_nobody(self):
		got, problem = google_chat_recipients(
			_instance("ToDo", self.todo.name), self._cfg("reference_name")
		)
		self.assertEqual(got, [])
		self.assertIn("has nothing in", problem)

	def test_naming_no_field_says_so(self):
		got, problem = google_chat_recipients(_instance("ToDo", self.todo.name), self._cfg(""))
		self.assertEqual(got, [])
		self.assertIn("gchatDocField is empty", problem)

	def test_without_a_context_document_there_is_nothing_to_read(self):
		got, problem = google_chat_recipients(_instance(), self._cfg("allocated_to"))
		self.assertEqual(got, [])
		self.assertIn("needs a context document", problem)

	def test_a_document_that_has_gone_is_reported_not_raised(self):
		"""A process outliving its document must log, not explode mid-run."""
		got, problem = google_chat_recipients(
			_instance("ToDo", "no-such-todo"), self._cfg("allocated_to")
		)
		self.assertEqual(got, [])
		self.assertIn("Could not read", problem)


class TestTableFieldBasis(FrappeTestCase):
	"""Rows of a child table, which is where a list of people actually lives."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.users = frappe.get_all(
			"User", filters={"enabled": 1, "user_type": "System User"}, pluck="name", limit=2
		)

	def _doc(self, rows, table_field="custom_watchers", row_field="user"):
		return frappe._dict({table_field: [frappe._dict({row_field: u}) for u in rows]})

	def _resolve(self, doc, cfg):
		original = frappe.get_doc
		frappe.get_doc = lambda *a, **k: doc
		try:
			return google_chat_recipients(_instance("ToDo", "_test"), cfg)
		finally:
			frappe.get_doc = original

	def test_every_row_contributes_a_recipient(self):
		got, problem = self._resolve(
			self._doc(self.users),
			{"gchatRecipientBasis": "Table Field", "gchatTableField": "custom_watchers"},
		)
		self.assertFalse(problem)
		self.assertEqual(len(got), len(self.users))

	def test_the_row_field_can_be_named(self):
		got, _ = self._resolve(
			self._doc(self.users[:1], row_field="approver"),
			{"gchatRecipientBasis": "Table Field", "gchatTableField": "custom_watchers",
			 "gchatTableUserField": "approver"},
		)
		self.assertEqual(len(got), 1)

	def test_the_same_user_in_two_rows_is_messaged_once(self):
		first = self.users[0]
		got, _ = self._resolve(
			self._doc([first, first]),
			{"gchatRecipientBasis": "Table Field", "gchatTableField": "custom_watchers"},
		)
		self.assertEqual(len(got), 1)

	def test_an_empty_table_is_reported(self):
		got, problem = self._resolve(
			self._doc([]),
			{"gchatRecipientBasis": "Table Field", "gchatTableField": "custom_watchers"},
		)
		self.assertEqual(got, [])
		self.assertIn("no rows in", problem)

	def test_rows_that_name_nobody_are_reported(self):
		got, problem = self._resolve(
			frappe._dict(custom_watchers=[frappe._dict(note="not a user")]),
			{"gchatRecipientBasis": "Table Field", "gchatTableField": "custom_watchers"},
		)
		self.assertEqual(got, [])
		self.assertIn("names a user", problem)

	def test_naming_no_table_says_so(self):
		got, problem = self._resolve(
			self._doc(self.users), {"gchatRecipientBasis": "Table Field", "gchatTableField": ""}
		)
		self.assertEqual(got, [])
		self.assertIn("gchatTableField is empty", problem)


class TestCredentialSource(FrappeTestCase):
	"""The key moved off site_config.json, where it could not be seen or rotated."""

	def test_an_empty_setting_sends_nothing(self):
		"""Without a key the dispatcher must give up before it reaches Google."""
		from unittest.mock import patch

		settings = frappe.get_cached_doc("Processa Settings")
		with patch.object(settings, "get_password", return_value=""), patch(
			"frappe.get_cached_doc", return_value=settings
		), patch("requests.post") as post:
			dispatch_google_chat(
				_instance(),
				None,
				{"gchatType": "space", "gchatSpaceId": "spaces/x", "gchatMessage": "hi"},
				"_test",
			)
		post.assert_not_called()


class TestChatUserId(FrappeTestCase):
	"""Turning an address into the id Chat will actually accept."""

	MOD = "one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers"
	DIRECTORY = {"abraham adekunle": ["110011284155291104346"]}
	EMAIL = "a.adekunle@one-fm.com"

	def setUp(self):
		frappe.cache().delete_value(f"gchat_user_id::{self.EMAIL}")

	def _resolve(self, directory_id="", names=None, full_name=None):
		"""Run a lookup with both sources stubbed, and report whether names were read."""
		from unittest.mock import patch

		with patch(f"{self.MOD}._directory_user_id", return_value=directory_id), patch(
			f"{self.MOD}._chat_dm_directory",
			return_value=self.DIRECTORY if names is None else names,
		) as scan, patch("frappe.db.get_value", return_value=full_name):
			return chat_user_id(self.EMAIL, {}), scan

	def test_the_directory_answers_before_any_name_is_read(self):
		got, scan = self._resolve(directory_id="999")
		self.assertEqual(got, "999")
		scan.assert_not_called()

	def test_without_a_directory_the_name_still_finds_them(self):
		got, _ = self._resolve(full_name="Abraham  Adekunle")
		self.assertEqual(got, "110011284155291104346")

	def test_a_middle_nameless_user_still_matches(self):
		"""full_name joins three parts, so no middle name leaves a double space."""
		got, _ = self._resolve(full_name="Abraham  Adekunle")
		self.assertEqual(got, "110011284155291104346")

	def test_two_people_of_one_name_resolve_to_nobody(self):
		"""Refusing beats guessing: a DM to the wrong colleague cannot be recalled."""
		got, _ = self._resolve(names={"abraham adekunle": ["1", "2"]}, full_name="Abraham Adekunle")
		self.assertEqual(got, "")

	def test_the_second_lookup_does_not_scan_again(self):
		"""The scan costs one request per person in the domain."""
		self._resolve(full_name="Abraham  Adekunle")
		_, scan = self._resolve(full_name="Abraham  Adekunle")
		scan.assert_not_called()
