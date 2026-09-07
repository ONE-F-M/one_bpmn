# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Session state: survives turns, isolated per conversation, no lost updates."""

import threading
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.memory.session_state import (
	STATE_DOCTYPE,
	StaleSessionState,
	clear_state,
	conversations_with,
	get_state,
	get_value,
	read_state,
	set_state,
	update_state,
)
from one_bpmn.utils.chat_persistence import create_conversation


class SessionStateCase(FrappeTestCase):
	def setUp(self):
		self.made = []
		self.conversation = self._conversation()

	def tearDown(self):
		for c in self.made:
			frappe.db.delete("Chat Session State Entry", {"parent": c})
			frappe.db.delete(STATE_DOCTYPE, {"name": c})
			frappe.db.delete("Chat Conversation", {"name": c})
		frappe.db.commit()

	def _conversation(self):
		name = create_conversation(
			agent_mode="Docu", title=f"State {frappe.generate_hash(length=8)}",
			user="Administrator",
		)
		self.made.append(name)
		return name


class TestReadingAndWriting(SessionStateCase):
	def test_an_untouched_conversation_has_empty_state_at_version_zero(self):
		"""Version 0 is not a placeholder — it is what a first writer passes to
		claim the state, so creating and updating are the same call."""
		self.assertEqual(read_state(self.conversation), ({}, 0))

	def test_a_write_returns_the_new_version(self):
		self.assertEqual(set_state(self.conversation, {"doctype": "Site Visit"}), 1)
		self.assertEqual(read_state(self.conversation), ({"doctype": "Site Visit"}, 1))

	def test_values_keep_their_type(self):
		set_state(self.conversation, {
			"name": "Site Visit", "fields": ["a", "b"], "count": 3,
			"ready": True, "nested": {"x": [1, 2]},
		})
		state = get_state(self.conversation)
		self.assertEqual(state["fields"], ["a", "b"])
		self.assertEqual(state["count"], 3)
		self.assertIs(state["ready"], True)
		self.assertEqual(state["nested"], {"x": [1, 2]})

	def test_a_later_turn_does_not_erase_an_earlier_one(self):
		"""The default is merge: a turn that learned one thing must not wipe the
		four things earlier turns learned."""
		set_state(self.conversation, {"a": 1})
		set_state(self.conversation, {"b": 2})
		self.assertEqual(get_state(self.conversation), {"a": 1, "b": 2})

	def test_replacing_wholesale_is_possible_when_asked_for(self):
		set_state(self.conversation, {"a": 1, "b": 2})
		set_state(self.conversation, {"c": 3}, merge=False)
		self.assertEqual(get_state(self.conversation), {"c": 3})

	def test_setting_a_key_to_none_removes_it(self):
		set_state(self.conversation, {"a": 1, "b": 2})
		set_state(self.conversation, {"a": None})
		self.assertEqual(get_state(self.conversation), {"b": 2})

	def test_the_keyword_form_behaves_the_same(self):
		update_state(self.conversation, stage="review", attempts=2)
		self.assertEqual(get_value(self.conversation, "stage"), "review")

	def test_clearing_removes_it_entirely(self):
		set_state(self.conversation, {"a": 1})
		clear_state(self.conversation)
		self.assertEqual(read_state(self.conversation), ({}, 0))


class TestIsolation(SessionStateCase):
	"""The AC's second half: state is absent from other conversations."""

	def test_state_does_not_leak_between_conversations(self):
		other = self._conversation()
		set_state(self.conversation, {"secret": "mine"})
		self.assertEqual(get_state(other), {})

	def test_each_conversation_versions_independently(self):
		other = self._conversation()
		set_state(self.conversation, {"a": 1})
		set_state(self.conversation, {"a": 2})
		set_state(other, {"a": 9})
		self.assertEqual(read_state(self.conversation)[1], 2)
		self.assertEqual(read_state(other)[1], 1)

	def test_clearing_one_leaves_the_other(self):
		other = self._conversation()
		set_state(self.conversation, {"a": 1})
		set_state(other, {"a": 2})
		clear_state(self.conversation)
		self.assertEqual(get_state(other), {"a": 2})


class TestOptimisticLocking(SessionStateCase):
	"""The AC's first half: a version prevents a SILENT lost update."""

	def test_a_write_against_the_version_you_read_succeeds(self):
		_, version = read_state(self.conversation)
		self.assertEqual(set_state(self.conversation, {"a": 1}, expected_version=version), 1)

	def test_a_write_against_a_stale_version_is_refused(self):
		set_state(self.conversation, {"a": 1})           # version 1
		stale = 0
		with self.assertRaises(StaleSessionState):
			set_state(self.conversation, {"b": 2}, expected_version=stale)

	def test_the_refused_write_changes_nothing(self):
		"""Refusing is only useful if it is also atomic."""
		set_state(self.conversation, {"a": 1})
		with self.assertRaises(StaleSessionState):
			set_state(self.conversation, {"a": 99}, expected_version=0)
		self.assertEqual(get_state(self.conversation), {"a": 1})
		self.assertEqual(read_state(self.conversation)[1], 1)

	def test_two_turns_racing_on_the_same_version_do_not_lose_one_silently(self):
		"""The scenario the AC names. Both turns read version 0 and both write:
		exactly one must win, and the loser must be TOLD rather than quietly
		overwriting the winner."""
		_, version = read_state(self.conversation)

		first = set_state(self.conversation, {"turn": "A"}, expected_version=version)
		with self.assertRaises(StaleSessionState):
			set_state(self.conversation, {"turn": "B"}, expected_version=version)

		self.assertEqual(first, 1)
		self.assertEqual(get_state(self.conversation), {"turn": "A"})

	def test_the_loser_can_re_read_and_apply_its_change(self):
		"""Which is the point of failing loudly: the caller has somewhere to go."""
		_, stale = read_state(self.conversation)
		set_state(self.conversation, {"turn": "A"}, expected_version=stale)

		try:
			set_state(self.conversation, {"turn": "B"}, expected_version=stale)
		except StaleSessionState:
			_, fresh = read_state(self.conversation)
			set_state(self.conversation, {"turn": "B"}, expected_version=fresh)

		self.assertEqual(get_state(self.conversation), {"turn": "B"})
		self.assertEqual(read_state(self.conversation)[1], 2)

	def test_omitting_the_version_skips_the_check(self):
		set_state(self.conversation, {"a": 1})
		self.assertEqual(set_state(self.conversation, {"b": 2}), 2)

	def test_frappes_own_timestamp_check_surfaces_as_the_same_error(self):
		"""A caller passing no version is still protected — by Frappe's modified
		check — and should not have to handle a second exception type to find
		that out."""
		set_state(self.conversation, {"a": 1})
		doc = frappe.get_doc(STATE_DOCTYPE, self.conversation)
		set_state(self.conversation, {"b": 2})          # someone else moves it on
		doc.append("entries", {"key": "c", "value": "3"})
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)


class TestQueryability(SessionStateCase):
	"""Rows rather than a blob: this query is the reason for the shape."""

	def test_conversations_can_be_found_by_a_key_they_hold(self):
		other = self._conversation()
		set_state(self.conversation, {"awaiting_approval": True})
		set_state(other, {"something_else": 1})

		found = conversations_with("awaiting_approval")
		self.assertIn(self.conversation, found)
		self.assertNotIn(other, found)

	def test_they_can_be_found_by_key_and_value(self):
		other = self._conversation()
		set_state(self.conversation, {"stage": "review"})
		set_state(other, {"stage": "draft"})

		self.assertEqual(conversations_with("stage", "review"), [self.conversation])


class TestDurability(SessionStateCase):
	def test_state_survives_a_new_process_instance(self):
		"""The reason this doctype exists rather than using process variables: a
		resumed conversation gets a BRAND NEW instance, so anything scoped to the
		old one is gone. State keyed to the conversation is not."""
		set_state(self.conversation, {"doctype": "Site Visit", "fields": ["a"]})

		for inst in frappe.get_all(
			"BPMN Process Instance",
			filters={"context_doctype": "Chat Conversation", "context_docname": self.conversation},
			pluck="name",
		):
			frappe.db.set_value("BPMN Process Instance", inst, "status", "Completed",
			                    update_modified=False)

		self.assertEqual(get_state(self.conversation)["doctype"], "Site Visit")

	def test_one_state_per_conversation_even_under_concurrent_creation(self):
		"""Named after its conversation, so the primary key is the mutex — the
		lesson the conversation store learned the hard way."""
		errors = []
		site, sites_path = frappe.local.site, frappe.local.sites_path
		conversation = self.conversation

		def worker(n):
			try:
				frappe.init(site=site, sites_path=sites_path, force=True)
				frappe.connect()
				frappe.set_user("Administrator")
				set_state(conversation, {f"k{n}": n})
				frappe.db.commit()
			except StaleSessionState:
				pass  # a legitimate outcome under contention
			except Exception as e:
				errors.append(repr(e))
			finally:
				frappe.destroy()

		threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
		for t in threads:
			t.start()
		for t in threads:
			t.join()
		frappe.init(site=site, sites_path=sites_path, force=True)
		frappe.connect()
		frappe.set_user("Administrator")

		self.assertEqual(errors, [], "a worker raised while writing state")
		self.assertEqual(frappe.db.count(STATE_DOCTYPE, {"conversation": conversation}), 1)


class TestValidation(SessionStateCase):
	def test_a_duplicate_key_is_rejected(self):
		"""A reader builds a dict, so a duplicate would resolve by row order
		rather than by what anyone wrote."""
		set_state(self.conversation, {"a": 1})
		doc = frappe.get_doc(STATE_DOCTYPE, self.conversation)
		doc.append("entries", {"key": "a", "value": "2"})
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_a_conversation_is_required(self):
		with self.assertRaises(Exception):
			set_state("", {"a": 1})

	def test_values_must_be_a_dict(self):
		with self.assertRaises(Exception):
			set_state(self.conversation, [("a", 1)])

	def test_an_unserialisable_value_is_kept_as_text_rather_than_failing(self):
		"""Losing the type of one key beats failing the agent turn recording it."""
		set_state(self.conversation, {"when": object()})
		self.assertIsInstance(get_value(self.conversation, "when"), str)


class TestRetentionRemovesState(SessionStateCase):
	def test_deleting_a_conversation_takes_its_state_with_it(self):
		from one_bpmn.agents.memory import retention

		set_state(self.conversation, {"a": 1})
		with patch("frappe.enqueue"):
			retention._delete(self.conversation)
		frappe.db.commit()

		self.assertFalse(frappe.db.exists(STATE_DOCTYPE, self.conversation))
		self.assertEqual(
			frappe.db.count("Chat Session State Entry", {"parent": self.conversation}), 0,
			"child rows were orphaned",
		)
