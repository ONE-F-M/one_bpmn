# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Session administration: inspectable in Processa, without Desk."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.tests.conversation_fixtures import drop_conversations
from one_bpmn.agents.memory.compaction_triggers import _clear_inflight as clear_inflight
from one_bpmn.agents.memory.conversation_store import AGENT_MEMORY_MODE
from one_bpmn.agents.memory.session_state import set_state
from one_bpmn.api.sessions_api import (
	agent_compaction_summary,
	compact_now,
	conversation_detail,
	get_retention,
	list_conversations,
	save_retention,
)
from one_bpmn.utils.chat_persistence import create_conversation, save_bot_message, save_user_message


class SessionsApiCase(FrappeTestCase):
	def setUp(self):
		self.made = []
		self.agents = []
		frappe.set_user("Administrator")

	def tearDown(self):
		for conv in self.made:
			clear_inflight(conv)
		drop_conversations(self.made)
		# Inserting an AI Agent Configuration fires the agent-creation map, which
		# COMMITS — so the row and the instance it spawns survive the rollback.
		frappe.flags.in_migrate = True
		try:
			for cfg in self.agents:
				for inst in frappe.get_all("BPMN Process Instance",
				                           filters={"context_docname": cfg.name}, pluck="name"):
					frappe.delete_doc("BPMN Process Instance", inst, force=True,
					                  ignore_permissions=True, delete_permanently=True)
				frappe.delete_doc("AI Agent Configuration", cfg.name, force=True,
				                  ignore_permissions=True, delete_permanently=True)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
		finally:
			frappe.flags.in_migrate = False
		frappe.set_user("Administrator")

	def _conversation(self, mode="Docu", messages=2, title=None):
		name = create_conversation(
			agent_mode=mode, title=title or f"Sess {frappe.generate_hash(length=8)}",
			user="Administrator",
		)
		self.made.append(name)
		with patch("frappe.enqueue"):
			for i in range(messages):
				save_user_message(name, f"u{i}")
				save_bot_message(name, f"b{i}")
		frappe.db.commit()
		return name

	def _summary(self, conversation, text, minutes_ago=0, supersedes=None):
		doc = frappe.get_doc({
			"doctype": "Chat Conversation Summary",
			"conversation": conversation,
			"summary": text,
			"covered_count": 2,
			"covered_upto": add_to_date(now_datetime(), minutes=-minutes_ago),
			"model": "test-model",
			"supersedes": supersedes,
		}).insert(ignore_permissions=True)
		frappe.db.commit()
		return doc.name

	# ── listing ─────────────────────────────────────────────────────────
	def test_a_conversation_appears_with_its_counts(self):
		conv = self._conversation(messages=3)
		found = next(c for c in list_conversations(limit=200)["conversations"] if c["name"] == conv)
		self.assertEqual(found["messages"], 6)
		self.assertEqual(found["summaries"], 0)
		self.assertFalse(found["has_state"])

	def test_a_fresh_conversation_reads_as_active(self):
		conv = self._conversation()
		found = next(c for c in list_conversations(limit=200)["conversations"] if c["name"] == conv)
		self.assertEqual(found["status"], "Active")

	def test_an_archived_conversation_reads_as_archived(self):
		conv = self._conversation()
		frappe.db.set_value("Chat Conversation", conv, "status", "Archived")
		frappe.db.commit()
		found = next(c for c in list_conversations(limit=200)["conversations"] if c["name"] == conv)
		self.assertEqual(found["status"], "Archived")

	def test_agent_memory_threads_are_not_listed(self):
		"""They are an agent's working state, not somebody's conversation, and
		they would swamp the list — there are hundreds of them."""
		conv = self._conversation(mode=AGENT_MEMORY_MODE)
		names = [c["name"] for c in list_conversations(limit=200)["conversations"]]
		self.assertNotIn(conv, names)

	def test_it_can_be_filtered_by_agent(self):
		mine = self._conversation(mode="Docu")
		other = self._conversation(mode="Logix")
		names = [c["name"] for c in list_conversations(agent="Docu", limit=200)["conversations"]]
		self.assertIn(mine, names)
		self.assertNotIn(other, names)

	def test_it_can_be_filtered_by_title(self):
		conv = self._conversation(title="Findable Marker 42")
		names = [c["name"] for c in list_conversations(search="Findable Marker", limit=200)["conversations"]]
		self.assertEqual(names, [conv])

	# ── one conversation ────────────────────────────────────────────────
	def test_detail_reports_the_stored_state(self):
		conv = self._conversation()
		set_state(conv, {"module": "Operations", "stage": "review"})
		d = conversation_detail(conv)
		self.assertEqual(d["state"]["module"], "Operations")
		self.assertEqual(d["state_version"], 1)

	def test_detail_reports_summaries_newest_first(self):
		"""The newest is the one actually in use; showing them in any other order
		invites reading a superseded summary and concluding the agent is wrong."""
		conv = self._conversation()
		older = self._summary(conv, "the older one", minutes_ago=10)
		newer = self._summary(conv, "the newer one", minutes_ago=0, supersedes=older)
		d = conversation_detail(conv)
		self.assertEqual([s["name"] for s in d["summaries"]], [newer, older])
		self.assertEqual(d["summaries"][0]["summary"], "the newer one")

	def test_an_unknown_conversation_is_refused_clearly(self):
		with self.assertRaises(frappe.ValidationError):
			conversation_detail("does-not-exist")

	# ── retention ───────────────────────────────────────────────────────
	def test_retention_round_trips(self):
		before = get_retention()
		try:
			out = save_retention(45, "Archive")
			self.assertEqual(out["ttl_days"], 45)
			self.assertEqual(out["archive_action"], "Archive")
			self.assertTrue(out["enabled"])
		finally:
			save_retention(before["ttl_days"], before["archive_action"])

	def test_zero_switches_retention_off(self):
		before = get_retention()
		try:
			out = save_retention(0, "Archive")
			self.assertFalse(out["enabled"])
		finally:
			save_retention(before["ttl_days"], before["archive_action"])

	def test_a_negative_period_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			save_retention(-1, "Archive")

	def test_an_unknown_action_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			save_retention(30, "Incinerate")

	def test_it_reports_what_the_next_sweep_would_touch(self):
		"""Nobody should switch Delete on without seeing the size of it first."""
		before = get_retention()
		try:
			out = save_retention(30, "Delete")
			self.assertIn("would_affect", out)
			self.assertIsInstance(out["would_affect"], int)
		finally:
			save_retention(before["ttl_days"], before["archive_action"])

	# ── compaction ──────────────────────────────────────────────────────
	def _compacting_agent(self, keep_tail=2):
		"""An enabled agent whose conversations the triggers will act on."""
		suffix = frappe.generate_hash(length=6)
		cfg = frappe.get_doc({
			"doctype": "AI Agent Configuration",
			"agent_id": f"_test_sessions_{suffix}",
			"agent_name": f"_test_sessions_{suffix}",
			"chat_mode_label": f"_Test Sessions {suffix}",
			"enabled": 1,
			"compaction_enabled": 1,
			"compaction_keep_tail": keep_tail,
		}).insert(ignore_permissions=True, ignore_mandatory=True)
		self.agents.append(cfg)
		return cfg

	def test_compact_now_queues_rather_than_running(self):
		"""A settings screen must not block on a model call."""
		cfg = self._compacting_agent()
		conv = self._conversation(mode=cfg.chat_mode_label, messages=8)
		with patch("one_bpmn.agents.memory.compaction.compact_conversation") as ran, \
		     patch("frappe.enqueue") as queued:
			out = compact_now(conv)
		self.assertTrue(out["queued"])
		ran.assert_not_called()
		self.assertTrue(queued.called)

	def test_it_says_so_when_the_agent_does_not_compact(self):
		"""A button that silently does nothing is the complaint that started this
		whole epic; "nothing happened, for one of three reasons" is barely better."""
		conv = self._conversation(messages=8)
		out = compact_now(conv)
		self.assertFalse(out["queued"])
		self.assertIn("switched off", out["reason"])

	def test_it_says_so_when_there_is_no_history_above_the_tail(self):
		cfg = self._compacting_agent(keep_tail=20)
		conv = self._conversation(mode=cfg.chat_mode_label, messages=2)
		out = compact_now(conv)
		self.assertFalse(out["queued"])
		self.assertIn("tail", out["reason"])

	def test_it_says_so_when_one_is_already_queued(self):
		cfg = self._compacting_agent()
		conv = self._conversation(mode=cfg.chat_mode_label, messages=8)
		with patch("frappe.enqueue"):
			self.assertTrue(compact_now(conv)["queued"])
			out = compact_now(conv)
		self.assertFalse(out["queued"])
		self.assertIn("already queued", out["reason"])

	# ── the agent overview ──────────────────────────────────────────────
	def test_the_agent_overview_lists_chat_agents(self):
		rows = agent_compaction_summary()
		self.assertTrue(rows)
		for r in rows:
			self.assertTrue(r["chat_mode_label"])
			self.assertIn("compaction_enabled", r)


class TestSessionsApiPermission(FrappeTestCase):
	def test_a_non_manager_is_refused(self):
		"""The listing exposes conversation titles and summary text across every
		user's chats, so it is gated harder than the rest of the editor."""
		user = f"_sess_probe_{frappe.generate_hash(length=6)}@example.com"
		doc = frappe.get_doc({
			"doctype": "User", "email": user, "first_name": "Probe",
			"send_welcome_email": 0, "enabled": 1,
		})
		doc.flags.no_welcome_mail = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		try:
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				list_conversations()
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("User", user, force=True, ignore_permissions=True)
			frappe.db.commit()
