# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Retention sweep, and concurrency proof for message append ordering."""

import threading
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.agents.memory.conversation_store import (
	AGENT_MEMORY_MODE,
	get_conversation_store,
)
from one_bpmn.agents.memory.retention import (
	ARCHIVED_STATUS,
	expired_conversations,
	last_activity,
	retention_config,
	sweep_expired_conversations,
)
from one_bpmn.utils.chat_persistence import (
	create_conversation,
	save_bot_message,
	save_user_message,
)


def settings(ttl, action="Archive"):
	"""Patch the two Processa Settings values the sweep reads."""
	def _get(doctype, field):
		return {"conversation_ttl_days": ttl, "archive_action": action}.get(field)
	return patch("frappe.db.get_single_value", side_effect=_get)


class RetentionCase(FrappeTestCase):
	def setUp(self):
		self.made = []

	def tearDown(self):
		for c in self.made:
			frappe.db.delete("Chat Message", {"conversation": c})
			frappe.db.delete("Chat Conversation", {"name": c})
		frappe.db.commit()

	def _conversation(self, mode="Docu", idle_days=0, messages=2):
		name = create_conversation(
			agent_mode=mode, title=f"Retention {frappe.generate_hash(length=8)}",
			user="Administrator",
		)
		self.made.append(name)
		with patch("frappe.enqueue"):
			for i in range(messages):
				save_user_message(name, f"u{i}")
				save_bot_message(name, f"b{i}")
		if idle_days:
			when = add_to_date(now_datetime(), days=-idle_days)
			frappe.db.sql("UPDATE `tabChat Message` SET creation=%s WHERE conversation=%s", (when, name))
			frappe.db.sql("UPDATE `tabChat Conversation` SET modified=%s, creation=%s WHERE name=%s",
			              (when, when, name))
		frappe.db.commit()
		return name


class TestRetentionConfig(RetentionCase):
	def test_disabled_by_default(self):
		with settings(0):
			self.assertIsNone(retention_config())

	def test_a_ttl_enables_it(self):
		with settings(30, "Delete"):
			self.assertEqual(retention_config(), {"ttl_days": 30, "action": "Delete"})

	def test_unreadable_settings_disable_rather_than_guess(self):
		with patch("frappe.db.get_single_value", side_effect=RuntimeError("boom")):
			self.assertIsNone(retention_config())

	def test_a_disabled_sweep_touches_nothing(self):
		conv = self._conversation(idle_days=400)
		with settings(0):
			out = sweep_expired_conversations()
		self.assertEqual(out["swept"], 0)
		self.assertEqual(frappe.db.get_value("Chat Conversation", conv, "status"), "Open")


class TestWhatCountsAsIdle(RetentionCase):
	def test_idle_is_measured_from_the_newest_message(self):
		conv = self._conversation(idle_days=100)
		self.assertLess(last_activity(conv), add_to_date(now_datetime(), days=-90))

	def test_a_conversation_with_no_messages_falls_back_to_its_creation(self):
		"""Otherwise an empty shell would never age out."""
		conv = self._conversation(idle_days=100, messages=0)
		self.assertIsNotNone(last_activity(conv))
		with settings(30):
			self.assertIn(conv, expired_conversations(30))

	def test_a_recent_message_keeps_a_stale_looking_row_alive(self):
		"""`modified` is a status change or a title edit; a message is activity.
		A row that looks old by one measure must not be swept if the other says
		somebody spoke in it recently."""
		conv = self._conversation(idle_days=100)
		frappe.db.sql("UPDATE `tabChat Message` SET creation=%s WHERE conversation=%s",
		              (now_datetime(), conv))
		frappe.db.commit()
		self.assertNotIn(conv, expired_conversations(30))

	def test_a_fresh_conversation_is_left_alone(self):
		conv = self._conversation(idle_days=0)
		self.assertNotIn(conv, expired_conversations(30))


class TestAgentMemoryIsNeverSwept(RetentionCase):
	"""An agent's memory thread is a running agent's working state, not a
	conversation somebody had. Deleting one silently removes what the agent
	remembers, and nobody would connect that to a retention setting."""

	def test_an_agent_memory_thread_is_excluded_however_idle(self):
		conv = self._conversation(mode=AGENT_MEMORY_MODE, idle_days=999)
		self.assertNotIn(conv, expired_conversations(1))

	def test_it_survives_a_delete_sweep(self):
		conv = self._conversation(mode=AGENT_MEMORY_MODE, idle_days=999)
		with settings(30, "Delete"):
			sweep_expired_conversations()
		self.assertTrue(frappe.db.exists("Chat Conversation", conv))


class TestArchive(RetentionCase):
	def test_it_marks_the_conversation_and_keeps_everything(self):
		conv = self._conversation(idle_days=100)
		# 4 messages written by the fixture
		with settings(30, "Archive"):
			out = sweep_expired_conversations()
		self.assertGreaterEqual(out["swept"], 1)
		self.assertEqual(frappe.db.get_value("Chat Conversation", conv, "status"), ARCHIVED_STATUS)
		self.assertEqual(frappe.db.count("Chat Message", {"conversation": conv}), 4)

	def test_an_archived_conversation_is_not_swept_again(self):
		"""Otherwise every sweep re-processes the whole archive forever."""
		conv = self._conversation(idle_days=100)
		with settings(30, "Archive"):
			sweep_expired_conversations()
			self.assertNotIn(conv, expired_conversations(30))


class TestDelete(RetentionCase):
	def test_it_removes_the_conversation_and_its_messages(self):
		conv = self._conversation(idle_days=100)
		with settings(30, "Delete"):
			out = sweep_expired_conversations()
		self.assertFalse(frappe.db.exists("Chat Conversation", conv))
		self.assertEqual(frappe.db.count("Chat Message", {"conversation": conv}), 0)
		self.assertGreaterEqual(out["messages_deleted"], 4)

	def test_it_reports_what_it_removed(self):
		"""The AC asks for the action to be logged; a retention policy that acts
		silently cannot be audited."""
		self._conversation(idle_days=100)
		with settings(30, "Delete"):
			out = sweep_expired_conversations()
		self.assertEqual(out["action"], "Delete")
		self.assertEqual(out["ttl_days"], 30)
		self.assertGreater(out["messages_deleted"], 0)


class TestSweepIsResilient(RetentionCase):
	def test_one_bad_conversation_does_not_stop_the_rest(self):
		good = self._conversation(idle_days=100)
		bad = self._conversation(idle_days=100)

		real = frappe.db.set_value

		def explode(doctype, name, *a, **kw):
			if name == bad:
				raise RuntimeError("boom")
			return real(doctype, name, *a, **kw)

		with settings(30, "Archive"), patch("frappe.db.set_value", side_effect=explode):
			out = sweep_expired_conversations()

		self.assertEqual(out["failed"], 1)
		self.assertEqual(frappe.db.get_value("Chat Conversation", good, "status"), ARCHIVED_STATUS)

	def test_a_pass_is_bounded(self):
		"""A retention policy that acts on ten thousand rows in one go is
		indistinguishable from an accident."""
		for _ in range(3):
			self._conversation(idle_days=100)
		self.assertLessEqual(len(expired_conversations(30, limit=2)), 2)


class TestAppendOrderingUnderConcurrency(RetentionCase):
	"""The AC's second half: prove appends stay ordered under parallel workers.

	The store assigns each message a sequence number and ``_load_raw`` sorts by
	it, so the question is whether two threads appending at once can produce
	duplicate or out-of-order sequence numbers — which would make the thread the
	model reads back non-deterministic.
	"""

	WORKERS = 8
	PER_WORKER = 5

	def _parallel_append(self, instance, bpmn_id):
		errors = []
		# frappe.local is thread-local, so a worker thread starts with no site
		# bound at all — it has to init before it can connect.
		site = frappe.local.site
		sites_path = frappe.local.sites_path

		def worker(n):
			try:
				frappe.init(site=site, sites_path=sites_path, force=True)
				frappe.connect()
				frappe.set_user("Administrator")
				store = get_conversation_store("document_store")
				for i in range(self.PER_WORKER):
					store.append(instance, bpmn_id, {"role": "user", "content": f"w{n}-m{i}"})
				frappe.db.commit()
			except Exception as e:  # surfaced by the assertions below
				errors.append(repr(e))
			finally:
				frappe.destroy()

		threads = [threading.Thread(target=worker, args=(n,)) for n in range(self.WORKERS)]
		for t in threads:
			t.start()
		for t in threads:
			t.join()
		# The threads called frappe.destroy(); rebind this one before asserting.
		frappe.init(site=site, sites_path=sites_path, force=True)
		frappe.connect()
		frappe.set_user("Administrator")
		return errors

	def test_parallel_appends_do_not_lose_messages(self):
		instance = f"_probe-{frappe.generate_hash(length=8)}"
		bpmn_id = "agent"
		errors = self._parallel_append(instance, bpmn_id)
		self.assertEqual(errors, [], "a worker raised while appending")

		title = f"one_bpmn:{instance}:{bpmn_id}"
		conv = frappe.db.get_value("Chat Conversation", {"title": title}, "name")
		self.made.append(conv)
		self.assertEqual(
			frappe.db.count("Chat Message", {"conversation": conv}),
			self.WORKERS * self.PER_WORKER,
			"messages were lost under parallel append",
		)

	def test_the_thread_reads_back_in_a_deterministic_order(self):
		instance = f"_probe-{frappe.generate_hash(length=8)}"
		bpmn_id = "agent"
		self._parallel_append(instance, bpmn_id)

		title = f"one_bpmn:{instance}:{bpmn_id}"
		conv = frappe.db.get_value("Chat Conversation", {"title": title}, "name")
		self.made.append(conv)

		store = get_conversation_store("document_store")
		reads = [[m["content"] for m in store.load(instance, bpmn_id)] for _ in range(5)]
		for other in reads[1:]:
			self.assertEqual(reads[0], other, "the same thread read back in a different order")

	def test_each_worker_sees_its_own_messages_in_order(self):
		"""Global interleaving is expected and fine — but a single worker's
		messages must never appear out of the order it wrote them."""
		instance = f"_probe-{frappe.generate_hash(length=8)}"
		bpmn_id = "agent"
		self._parallel_append(instance, bpmn_id)

		title = f"one_bpmn:{instance}:{bpmn_id}"
		conv = frappe.db.get_value("Chat Conversation", {"title": title}, "name")
		self.made.append(conv)

		store = get_conversation_store("document_store")
		order = [m["content"] for m in store.load(instance, bpmn_id)]
		for n in range(self.WORKERS):
			mine = [c for c in order if c.startswith(f"w{n}-")]
			self.assertEqual(mine, sorted(mine, key=lambda c: int(c.split("-m")[1])),
			                 f"worker {n} read back out of order")
