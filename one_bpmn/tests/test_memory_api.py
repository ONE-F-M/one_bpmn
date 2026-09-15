# The memory browser endpoints: who may read which rows, what Retire does and
# undoes, and that reading somebody else's memories is recorded.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from one_bpmn.agents.memory import tools as T
from one_bpmn.agents.memory.permissions import ai_memory_has_permission
from one_bpmn.api import memory_api as API


# set_user on FrappeTestCase is a context manager, not a setter: calling it
# bare builds a generator that is never entered and the session user never
# changes, so a permission test would pass while testing nothing.
def _user(prefix: str) -> str:
	email = f"{prefix}_{frappe.generate_hash(length=6)}@example.com"
	frappe.get_doc({"doctype": "User", "email": email, "first_name": prefix}).insert(ignore_permissions=True)
	return email


class TestMemoryBrowser(FrappeTestCase):
	def setUp(self):
		self.agent = f"BR_{frappe.generate_hash(length=8)}"
		self.alice = _user("alice")
		self.bob = _user("bob")
		self.shared = T.memory_write("Agent", self.agent, "the office closes at two on Thursdays", ignore_permissions=True)
		self.hers = T.memory_write(
			"Agent", {"agent_element": self.agent, "user": self.alice}, "her leave needs a certificate", ignore_permissions=True
		)

	def _names(self, **kw):
		return {m["name"] for m in API.list_memories(agent_element=self.agent, page_length=100, **kw)["memories"]}

	# ── who sees what ────────────────────────────────────────────────────
	def test_a_person_sees_their_own_and_the_shared_ones(self):
		with self.set_user(self.alice):
			found = self._names()
		self.assertIn(self.hers["name"], found)
		self.assertIn(self.shared["name"], found)

	def test_a_person_never_sees_somebody_elses(self):
		with self.set_user(self.bob):
			found = self._names()
		self.assertIn(self.shared["name"], found)
		self.assertNotIn(self.hers["name"], found)

	def test_a_system_manager_sees_everybody(self):
		found = self._names()  # the test runs as Administrator
		self.assertIn(self.hers["name"], found)
		self.assertTrue(API.list_memories(agent_element=self.agent)["can_see_everyone"])

	def test_the_permission_hook_agrees_with_the_listing(self):
		mine = frappe.get_doc("AI Memory", self.hers["name"])
		self.assertTrue(ai_memory_has_permission(mine, "read", user=self.alice))
		self.assertFalse(ai_memory_has_permission(mine, "read", user=self.bob))
		self.assertTrue(ai_memory_has_permission(frappe.get_doc("AI Memory", self.shared["name"]), "read", user=self.bob))

	def test_a_shared_memory_may_be_read_by_anyone_and_changed_by_nobody(self):
		"""It belongs to the agent and to everyone using it, so one person
		retiring it would take it away from the whole team."""
		shared = frappe.get_doc("AI Memory", self.shared["name"])
		self.assertTrue(ai_memory_has_permission(shared, "read", user=self.bob))
		self.assertFalse(ai_memory_has_permission(shared, "write", user=self.bob))
		with self.set_user(self.bob), self.assertRaises(frappe.PermissionError):
			API.retire_memory(self.shared["name"])

	def test_a_person_may_retire_their_own(self):
		with self.set_user(self.alice):
			API.retire_memory(self.hers["name"])
		self.assertIsNotNone(frappe.db.get_value("AI Memory", self.hers["name"], "expires_on"))

	def test_reading_one_memory_refuses_somebody_elses(self):
		with self.set_user(self.bob), self.assertRaises(frappe.PermissionError):
			API.get_memory(self.hers["name"])

	# ── retired rows ─────────────────────────────────────────────────────
	def test_retired_memories_are_hidden_until_asked_for(self):
		API.retire_memory(self.shared["name"])
		self.assertNotIn(self.shared["name"], self._names())
		self.assertIn(self.shared["name"], self._names(include_retired=1))

	def test_retire_keeps_the_row_and_says_why(self):
		API.retire_memory(self.shared["name"])
		row = frappe.db.get_value("AI Memory", self.shared["name"], ["expires_on", "metadata"], as_dict=True)
		self.assertIsNotNone(row.expires_on)
		self.assertLessEqual(row.expires_on, now_datetime())
		self.assertEqual((T._json_loads(row.metadata) or {}).get("retired", {}).get("by"), frappe.session.user)
		self.assertTrue(frappe.db.exists("AI Memory", self.shared["name"]))

	def test_retire_stops_it_being_recalled(self):
		API.retire_memory(self.shared["name"])
		found = [r["name"] for r in T.memory_search("Agent", self.agent, "office closes Thursdays", ignore_permissions=True)]
		self.assertNotIn(self.shared["name"], found)

	def test_retiring_twice_is_not_an_error(self):
		API.retire_memory(self.shared["name"])
		self.assertTrue(API.retire_memory(self.shared["name"])["already"])

	def test_restore_puts_it_back(self):
		API.retire_memory(self.shared["name"])
		API.restore_memory(self.shared["name"])
		self.assertIsNone(frappe.db.get_value("AI Memory", self.shared["name"], "expires_on"))
		self.assertIn(self.shared["name"], self._names())

	# ── the rest of the listing ──────────────────────────────────────────
	def test_the_row_carries_what_the_table_shows(self):
		row = next(m for m in API.list_memories(agent_element=self.agent)["memories"] if m["name"] == self.hers["name"])
		self.assertEqual(row["scope_key"], self.agent)
		self.assertEqual(row["owner_label"], self.alice)
		self.assertFalse(row["retired"])

	def test_a_shared_row_is_labelled_shared(self):
		row = next(m for m in API.list_memories(agent_element=self.agent)["memories"] if m["name"] == self.shared["name"])
		self.assertEqual(row["owner_label"], "Shared")

	def test_filtering_to_one_person(self):
		self.assertEqual(self._names(user=self.alice), {self.hers["name"]})
		self.assertEqual(self._names(user="Shared"), {self.shared["name"]})

	def test_search_matches_content(self):
		self.assertEqual(self._names(search="certificate"), {self.hers["name"]})

	def test_the_page_length_is_capped(self):
		self.assertEqual(API.list_memories(page_length=10_000)["page_length"], API.MAX_PAGE_LENGTH)

	# ── the audit ────────────────────────────────────────────────────────
	def test_reading_somebody_elses_memories_is_recorded(self):
		before = frappe.db.count("Access Log", {"export_from": "AI Memory"})
		# Administrator listing Alice's rows is a disclosure and is logged.
		API.list_memories(agent_element=self.agent, page_length=100)
		self.assertGreater(frappe.db.count("Access Log", {"export_from": "AI Memory"}), before)

	def test_reading_only_your_own_is_not_recorded(self):
		before = frappe.db.count("Access Log", {"export_from": "AI Memory"})
		with self.set_user(self.alice):
			API.list_memories(agent_element=self.agent, user=self.alice, page_length=100)
		self.assertEqual(frappe.db.count("Access Log", {"export_from": "AI Memory"}), before)
