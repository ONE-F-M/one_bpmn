# Copyright (c) 2026, one-fm and contributors
# WI-001968: per-user per-agent throttling, automatic conversation freeze, and
# reviewer-gated release.
#
# The tests that matter most are the ones about who can undo a lock. A freeze
# the frozen user can lift themselves contains nobody, so that path is tested
# explicitly, including for a System Manager.

from __future__ import annotations

import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.conversation_locks import my_lock_status, release_lock, reviewer_roles
from one_bpmn.one_bpmn.doctype.ai_conversation_lock.ai_conversation_lock import active_lock
from one_bpmn.security import rate_limit as RL

PREFIX = "ZZ-wi1968"
PROBER = "zz-wi1968-prober@example.com"
REVIEWER = "zz-wi1968-reviewer@example.com"


class TestRateLimitAndLock(FrappeTestCase):
	def setUp(self):
		self._cleanup()
		self.agent = self._agent()
		self._settings(rate_limit_enabled=1, rate_limit_messages=3, rate_limit_window_seconds=60,
		               lock_after_blocks=3, lock_block_window_seconds=3600)
		self._flush_window()

	def tearDown(self):
		self._cleanup()
		frappe.set_user("Administrator")
		frappe.db.commit()

	def _cleanup(self):
		frappe.set_user("Administrator")
		frappe.db.delete("AI Conversation Lock", {"user": ("like", "zz-wi1968%")})
		# Every event this suite can produce, including the injection rows that
		# stand in for blocked attempts — leaving those behind makes the freeze
		# threshold fire in the next test for reasons that test never set up.
		frappe.db.delete(
			"AI Security Event", {"stage": ("in", ["rate-limit", "conversation-lock", "injection"])}
		)
		frappe.db.delete("AI Security Event", {"owner": ("like", "zz-wi1968%")})
		frappe.db.delete("AI Agent Configuration", {"agent_name": ("like", f"{PREFIX}%")})

	def _agent(self):
		name = f"{PREFIX} agent"
		if frappe.db.exists("AI Agent Configuration", name):
			return name
		return frappe.get_doc({
			"doctype": "AI Agent Configuration", "agent_name": name,
			"agent_id": "zz_wi1968_agent", "agent_type": "Background",
			"agent_framework": "Direct API", "enabled": 1,
		}).insert(ignore_permissions=True).name

	def _user(self, email, roles=()):
		if not frappe.db.exists("User", email):
			doc = frappe.get_doc({
				"doctype": "User", "email": email, "first_name": email.split("@")[0],
				"send_welcome_email": 0,
			}).insert(ignore_permissions=True)
		else:
			doc = frappe.get_doc("User", email)
		for role in roles:
			if not frappe.db.exists("Role", role):
				frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
			if role not in [r.role for r in doc.roles]:
				doc.append("roles", {"role": role})
		doc.save(ignore_permissions=True)
		return email

	def _settings(self, **values):
		for k, v in values.items():
			frappe.db.set_single_value("Processa Settings", k, v)
		frappe.clear_document_cache("Processa Settings", "Processa Settings")

	def _flush_window(self):
		try:
			frappe.cache().delete(RL._window_key(PROBER, "zz_wi1968_agent"))
		except Exception:
			pass

	def _enforce(self, user=PROBER, conversation=None):
		RL.enforce(user=user, agent=self.agent, agent_label="zz_wi1968_agent", conversation=conversation)

	# ------------------------------------------------------------------
	# The sliding window
	# ------------------------------------------------------------------
	def test_messages_under_the_limit_pass(self):
		for _ in range(3):
			self._enforce()  # limit is 3

	def test_exceeding_the_limit_is_refused(self):
		self._settings(lock_after_blocks=0)  # isolate the throttle from the freeze
		for _ in range(3):
			self._enforce()
		with self.assertRaises(RL.RateLimited):
			self._enforce()

	def test_the_refusal_is_recorded_as_a_block(self):
		self._settings(lock_after_blocks=0)
		for _ in range(3):
			self._enforce()
		with self.assertRaises(RL.RateLimited):
			self._enforce()

		evt = frappe.get_all(
			"AI Security Event", filters={"stage": "rate-limit"},
			fields=["action", "boundary", "classifier", "detail", "agent_configuration"],
			order_by="creation desc", limit=1,
		)
		self.assertTrue(evt, "the refusal should be in the security log")
		self.assertEqual(evt[0].action, "Block")
		self.assertEqual(evt[0].boundary, "input")
		self.assertEqual(evt[0].agent_configuration, self.agent)
		self.assertIn("limit 3", evt[0].detail)

	def test_the_window_slides_rather_than_resetting(self):
		"""Old attempts age out, so a quiet user is not punished for yesterday."""
		self._settings(rate_limit_window_seconds=1, lock_after_blocks=0)
		self._flush_window()
		for _ in range(3):
			self._enforce()
		time.sleep(1.2)  # everything in the window is now older than it
		self._enforce()  # must not raise

	def test_the_limit_is_per_user(self):
		self._settings(lock_after_blocks=0)
		other = "zz-wi1968-other@example.com"
		for _ in range(3):
			self._enforce()
		with self.assertRaises(RL.RateLimited):
			self._enforce()
		# A different user has their own window.
		RL.enforce(user=other, agent=self.agent, agent_label="zz_wi1968_agent", conversation=None)

	def test_the_limit_is_per_agent(self):
		self._settings(lock_after_blocks=0)
		for _ in range(3):
			self._enforce()
		with self.assertRaises(RL.RateLimited):
			self._enforce()
		# Same user, different agent — separate window.
		RL.enforce(user=PROBER, agent=self.agent, agent_label="zz_wi1968_other_agent", conversation=None)

	def test_a_zero_limit_disables_the_throttle(self):
		self._settings(rate_limit_messages=0, lock_after_blocks=0)
		for _ in range(10):
			self._enforce()

	def test_disabling_rate_limiting_skips_both_controls(self):
		self._settings(rate_limit_enabled=0)
		for _ in range(10):
			self._enforce()

	# ------------------------------------------------------------------
	# The freeze
	# ------------------------------------------------------------------
	def _record_blocks(self, n, severity="High"):
		"""Blocked attempts as the counter reads them: High/Critical injection hits."""
		from one_bpmn.security.events import record_event

		for i in range(n):
			record_event(
				boundary="input", stage="injection", action="Flag", severity=severity,
				agent_configuration=self.agent, conversation="CONV-1",
				classifier="probe", detail=f"probe {i}",
			)

	def test_accumulated_blocks_freeze_the_conversation(self):
		frappe.set_user(PROBER if frappe.db.exists("User", PROBER) else "Administrator")
		frappe.set_user("Administrator")
		self._user(PROBER)

		# Events are attributed by owner, so record them AS the prober.
		frappe.set_user(PROBER)
		self._record_blocks(3)
		frappe.set_user("Administrator")

		self.assertEqual(RL.blocked_attempts(PROBER, self.agent, 3600), 3)

		with self.assertRaises(RL.RateLimited):
			self._enforce(conversation="CONV-1")

		lock = active_lock(PROBER, self.agent, "CONV-1")
		self.assertIsNotNone(lock, "the conversation should be frozen")
		doc = frappe.get_doc("AI Conversation Lock", lock)
		self.assertEqual(doc.status, "Locked")
		self.assertEqual(doc.reason, "Repeated Blocked Attempts")
		self.assertGreaterEqual(doc.blocked_count, 3)

	def test_a_frozen_conversation_refuses_every_further_message(self):
		self._user(PROBER)
		RL.raise_lock(PROBER, self.agent, "CONV-1", reason="Manual", blocked_count=9)
		for _ in range(3):
			with self.assertRaises(RL.RateLimited):
				self._enforce(conversation="CONV-1")

	def test_a_freeze_follows_the_user_into_a_new_conversation(self):
		"""Otherwise a prober just opens a new chat and carries on."""
		self._user(PROBER)
		RL.raise_lock(PROBER, self.agent, "CONV-1", reason="Manual", blocked_count=9)
		with self.assertRaises(RL.RateLimited):
			self._enforce(conversation="CONV-BRAND-NEW")

	def test_freezing_is_idempotent(self):
		self._user(PROBER)
		first = RL.raise_lock(PROBER, self.agent, "CONV-1", reason="Manual", blocked_count=3)
		second = RL.raise_lock(PROBER, self.agent, "CONV-1", reason="Manual", blocked_count=4)
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("AI Conversation Lock", {"user": PROBER, "status": "Locked"}), 1)

	def test_the_lockout_is_logged(self):
		self._user(PROBER)
		frappe.set_user(PROBER)
		self._record_blocks(3)
		frappe.set_user("Administrator")
		with self.assertRaises(RL.RateLimited):
			self._enforce(conversation="CONV-1")

		events = frappe.get_all(
			"AI Security Event", filters={"stage": "conversation-lock"},
			fields=["action", "severity", "classifier", "detail"], order_by="creation desc",
		)
		self.assertTrue(events, "the lockout must be recorded")
		self.assertTrue(any(e.classifier == "lockout" for e in events))
		self.assertTrue(any(e.action == "Block" for e in events))

	def test_a_zero_threshold_disables_the_freeze(self):
		self._settings(lock_after_blocks=0)
		self._user(PROBER)
		frappe.set_user(PROBER)
		self._record_blocks(5)
		frappe.set_user("Administrator")
		self._enforce(conversation="CONV-1")
		self.assertIsNone(active_lock(PROBER, self.agent, "CONV-1"))

	def test_old_blocks_age_out_of_the_window(self):
		self._settings(lock_block_window_seconds=1)
		self._user(PROBER)
		frappe.set_user(PROBER)
		self._record_blocks(3)
		frappe.set_user("Administrator")
		time.sleep(1.2)
		self.assertEqual(RL.blocked_attempts(PROBER, self.agent, 1), 0)

	# ------------------------------------------------------------------
	# Release — the part that has to be right
	# ------------------------------------------------------------------
	def test_release_requires_a_reviewer_role(self):
		self._user(PROBER)
		plain = self._user("zz-wi1968-plain@example.com")
		lock = RL.raise_lock(PROBER, self.agent, "CONV-1", reason="Manual", blocked_count=3)

		frappe.set_user(plain)
		with self.assertRaises(frappe.PermissionError):
			release_lock(lock, notes="let me out")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("AI Conversation Lock", lock, "status"), "Locked")

	def test_a_reviewer_can_release(self):
		self._user(PROBER)
		reviewer = self._user(REVIEWER, roles=["AI Security Reviewer"])
		lock = RL.raise_lock(PROBER, self.agent, "CONV-1", reason="Manual", blocked_count=3)

		frappe.set_user(reviewer)
		result = release_lock(lock, notes="false positive, confirmed with the user")
		frappe.set_user("Administrator")

		self.assertEqual(result["status"], "Released")
		doc = frappe.get_doc("AI Conversation Lock", lock)
		self.assertEqual(doc.status, "Released")
		self.assertEqual(doc.released_by, reviewer)
		self.assertTrue(doc.released_at)
		self.assertIn("false positive", doc.release_notes)

	def test_the_locked_user_cannot_release_their_own_lock(self):
		"""Even holding every role. A control you can lift on yourself is not one."""
		prober = self._user(PROBER, roles=["AI Security Reviewer", "System Manager"])
		lock = RL.raise_lock(prober, self.agent, "CONV-1", reason="Manual", blocked_count=3)

		frappe.set_user(prober)
		with self.assertRaises(frappe.PermissionError):
			release_lock(lock, notes="I'm fine, honestly")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("AI Conversation Lock", lock, "status"), "Locked")

	def test_release_demands_a_reason(self):
		self._user(PROBER)
		reviewer = self._user(REVIEWER, roles=["AI Security Reviewer"])
		lock = RL.raise_lock(PROBER, self.agent, "CONV-1", reason="Manual", blocked_count=3)

		frappe.set_user(reviewer)
		with self.assertRaises(frappe.ValidationError):
			release_lock(lock, notes="   ")
		frappe.set_user("Administrator")

	def test_releasing_lets_the_user_talk_again(self):
		self._user(PROBER)
		reviewer = self._user(REVIEWER, roles=["AI Security Reviewer"])
		lock = RL.raise_lock(PROBER, self.agent, "CONV-1", reason="Manual", blocked_count=3)

		with self.assertRaises(RL.RateLimited):
			self._enforce(conversation="CONV-1")

		frappe.set_user(reviewer)
		release_lock(lock, notes="reviewed")
		frappe.set_user("Administrator")

		self._settings(lock_after_blocks=0)  # the old strikes are still on file
		self._flush_window()
		self._enforce(conversation="CONV-1")  # must not raise

	def test_the_release_is_logged(self):
		self._user(PROBER)
		reviewer = self._user(REVIEWER, roles=["AI Security Reviewer"])
		lock = RL.raise_lock(PROBER, self.agent, "CONV-1", reason="Manual", blocked_count=3)
		frappe.set_user(reviewer)
		release_lock(lock, notes="reviewed and cleared")
		frappe.set_user("Administrator")

		evt = frappe.get_all(
			"AI Security Event", filters={"stage": "conversation-lock", "classifier": "lock-released"},
			fields=["detail"], order_by="creation desc", limit=1,
		)
		self.assertTrue(evt)
		self.assertIn(reviewer, evt[0].detail)

	def test_releasing_twice_is_harmless(self):
		self._user(PROBER)
		reviewer = self._user(REVIEWER, roles=["AI Security Reviewer"])
		lock = RL.raise_lock(PROBER, self.agent, "CONV-1", reason="Manual", blocked_count=3)
		frappe.set_user(reviewer)
		release_lock(lock, notes="reviewed")
		again = release_lock(lock, notes="reviewed")
		frappe.set_user("Administrator")
		self.assertTrue(again.get("already"))

	def test_system_manager_is_always_a_reviewer(self):
		self.assertIn("System Manager", reviewer_roles())

	def test_a_lock_cannot_be_deleted(self):
		self._user(PROBER)
		lock = RL.raise_lock(PROBER, self.agent, "CONV-1", reason="Manual", blocked_count=3)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("AI Conversation Lock", lock, force=True, ignore_permissions=True)

	def test_a_user_can_see_that_they_are_locked(self):
		self._user(PROBER)
		RL.raise_lock(PROBER, self.agent, None, reason="Manual", blocked_count=3)
		frappe.set_user(PROBER)
		status = my_lock_status()
		frappe.set_user("Administrator")
		self.assertTrue(status["locked"])
		self.assertEqual(status["reason"], "Manual")

	# ------------------------------------------------------------------
	# Failure posture
	# ------------------------------------------------------------------
	def test_a_broken_cache_lets_the_turn_through(self):
		"""Abuse protection must not become an outage when Redis blips."""
		self._settings(lock_after_blocks=0)
		with patch.object(RL, "record_and_count", return_value=-1):
			for _ in range(10):
				self._enforce()

	def test_unreadable_settings_fall_back_to_defaults(self):
		with patch("frappe.get_cached_doc", side_effect=RuntimeError("no settings")):
			cfg = RL.settings()
		self.assertEqual(cfg["rate_limit_messages"], 20)
		self.assertEqual(cfg["lock_after_blocks"], 3)

	def test_a_failed_block_count_raises_no_freeze(self):
		with patch("frappe.db.count", side_effect=RuntimeError("db down")):
			self.assertEqual(RL.blocked_attempts(PROBER, self.agent, 3600), 0)

	def test_an_existing_lock_still_bites_when_everything_else_is_broken(self):
		"""The one thing that must not fail open."""
		self._user(PROBER)
		RL.raise_lock(PROBER, self.agent, "CONV-1", reason="Manual", blocked_count=3)
		with patch.object(RL, "settings", side_effect=RuntimeError("settings gone")):
			with self.assertRaises(RL.RateLimited):
				self._enforce(conversation="CONV-1")
