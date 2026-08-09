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
		"""Override the rate-limit settings for this test ONLY.

		Deliberately does NOT write to Processa Settings. These tests used to set
		the live singleton and restore it in tearDown, so any interrupted run
		left the real site throttled at a test's values — which is exactly what
		happened: a user hit "limit 1" in normal use. Patching the reader keeps
		the blast radius inside the test.
		"""
		from one_bpmn.security import rate_limit as _RL

		current = dict(_RL._DEFAULTS)
		current.update(getattr(self, "_override", {}))
		current.update(values)
		self._override = current

		if getattr(self, "_settings_patch", None) is None:
			self._settings_patch = patch.object(_RL, "settings", lambda: dict(self._override))
			self._settings_patch.start()
			self.addCleanup(self._stop_settings_patch)

	def _stop_settings_patch(self):
		if getattr(self, "_settings_patch", None) is not None:
			self._settings_patch.stop()
			self._settings_patch = None
		self._override = {}

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
		# _settings() patches RL.settings for isolation, so reach past it to the
		# real implementation — this test is about that function's own behaviour.
		self._stop_settings_patch()
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


class TestPerTurnEnforcement(FrappeTestCase):
	"""The gate has to fire on EVERY message, not just the first of a chat.

	Map-driven chat agents run one long-lived BPMN instance: invoke_agent opens
	it and every later message resumes it, so a gate at the API entry point sees
	message #1 and nothing after. Found in testing — 15 runs on one instance,
	one trip through invoke_agent. These pin the Chat Message boundary, which is
	the one that actually fires per turn.
	"""

	def setUp(self):
		frappe.set_user("Administrator")
		self.agent = frappe.get_doc({
			"doctype": "AI Agent Configuration", "agent_name": f"{PREFIX} turn agent",
			"agent_id": "zz_wi1968_turn", "agent_type": "Chat", "agent_framework": "Direct API",
			"chat_mode_label": f"{PREFIX} Turn", "enabled": 1,
		}).insert(ignore_permissions=True).name
		self.conv = frappe.get_doc({
			"doctype": "Chat Conversation", "agent_mode": f"{PREFIX} Turn", "title": f"{PREFIX} chat",
		}).insert(ignore_permissions=True).name
		self._settings(rate_limit_enabled=1, rate_limit_messages=3,
		               rate_limit_window_seconds=60, lock_after_blocks=0)
		self._flush()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("Chat Message", {"conversation": self.conv})
		frappe.db.delete("Chat Conversation", {"name": self.conv})
		frappe.db.delete("AI Agent Configuration", {"agent_name": ("like", f"{PREFIX}%")})
		frappe.db.delete("AI Security Event", {"stage": ("in", ["rate-limit", "conversation-lock"])})
		frappe.db.delete("AI Conversation Lock", {"user": "Administrator"})
		self._flush()
		frappe.db.commit()

	def _settings(self, **values):
		"""Override the rate-limit settings for this test ONLY.

		Deliberately does NOT write to Processa Settings. These tests used to set
		the live singleton and restore it in tearDown, so any interrupted run
		left the real site throttled at a test's values — which is exactly what
		happened: a user hit "limit 1" in normal use. Patching the reader keeps
		the blast radius inside the test.
		"""
		from one_bpmn.security import rate_limit as _RL

		current = dict(_RL._DEFAULTS)
		current.update(getattr(self, "_override", {}))
		current.update(values)
		self._override = current

		if getattr(self, "_settings_patch", None) is None:
			self._settings_patch = patch.object(_RL, "settings", lambda: dict(self._override))
			self._settings_patch.start()
			self.addCleanup(self._stop_settings_patch)

	def _stop_settings_patch(self):
		if getattr(self, "_settings_patch", None) is not None:
			self._settings_patch.stop()
			self._settings_patch = None
		self._override = {}

	def _flush(self):
		try:
			frappe.cache().delete(RL._window_key("Administrator", "zz_wi1968_turn"))
		except Exception:
			pass

	def _send(self, text):
		from one_bpmn.security import turn as T

		T.begin_turn()  # one correlation id per turn, as invoke_agent does
		try:
			return frappe.get_doc({
				"doctype": "Chat Message", "conversation": self.conv,
				"message_type": "User", "text": text,
			}).insert(ignore_permissions=True)
		finally:
			T.end_turn()

	def test_the_limit_applies_to_every_message_not_just_the_first(self):
		for i in range(3):
			self._send(f"message {i}")
		with self.assertRaises(RL.RateLimited):
			self._send("one too many")

	def test_a_refused_message_is_not_stored(self):
		"""The refusal must abort the insert, not merely log alongside it."""
		for i in range(3):
			self._send(f"message {i}")
		try:
			self._send("should not persist")
		except RL.RateLimited:
			pass
		self.assertEqual(
			frappe.db.count("Chat Message", {"conversation": self.conv, "text": "should not persist"}),
			0,
			"a refused turn must leave no message behind",
		)

	def test_the_agent_is_resolved_from_the_conversation(self):
		"""The conversation stores a chat-mode label, not the agent's id."""
		from one_bpmn.security.pii import _agent_for_conversation

		self.assertEqual(_agent_for_conversation(self.conv), (self.agent, "zz_wi1968_turn"))
		self.assertEqual(_agent_for_conversation(None), (None, None))
		self.assertEqual(_agent_for_conversation("no-such-conversation"), (None, None))

	def test_bot_messages_are_not_counted_against_the_user(self):
		for i in range(5):
			frappe.get_doc({
				"doctype": "Chat Message", "conversation": self.conv,
				"message_type": "Bot", "text": f"reply {i}",
			}).insert(ignore_permissions=True)
		self._send("still my first message")  # must not raise

	def test_one_turn_counts_once_even_if_gated_twice(self):
		"""invoke_agent and the Chat Message hook both fire on the first turn."""
		from one_bpmn.security import turn as T

		T.begin_turn()
		try:
			for _ in range(4):  # same turn id, four enforcement passes
				RL.enforce(user="Administrator", agent=self.agent,
				           agent_label="zz_wi1968_turn", conversation=self.conv)
		finally:
			T.end_turn()

	def test_internal_conversations_are_not_throttled(self):
		"""Memory distillation writes a User message per turn into its own
		conversation. Throttling that would refuse the system's own bookkeeping
		and break the very turn it belongs to."""
		internal = frappe.get_doc({
			"doctype": "Chat Conversation", "agent_mode": "one_bpmn:agent-memory",
			"title": f"{PREFIX} internal",
		}).insert(ignore_permissions=True).name
		try:
			from one_bpmn.security import turn as T

			for i in range(10):  # far past the limit of 3
				T.begin_turn()
				frappe.get_doc({
					"doctype": "Chat Message", "conversation": internal,
					"message_type": "User", "text": f"Conversation so far: {i}",
				}).insert(ignore_permissions=True)
				T.end_turn()
		finally:
			frappe.db.delete("Chat Message", {"conversation": internal})
			frappe.db.delete("Chat Conversation", {"name": internal})

	def test_every_live_chat_agent_resolves(self):
		"""The gate is useless for an agent whose conversation label does not
		resolve — it would silently skip that agent entirely."""
		from one_bpmn.security.pii import _agent_for_conversation

		for label in ("Logix", "Docu", "ProsAlly", "LuCrusher", "General Chat"):
			if not frappe.db.exists("AI Agent Configuration", {"chat_mode_label": label}):
				continue  # agent not installed on this site
			conv = frappe.get_doc({
				"doctype": "Chat Conversation", "agent_mode": label, "title": f"{PREFIX} {label}",
			}).insert(ignore_permissions=True).name
			try:
				name, agent_id = _agent_for_conversation(conv)
				self.assertIsNotNone(name, f"{label} must resolve or it is never gated")
				self.assertIsNotNone(agent_id, f"{label} must yield an agent id")
			finally:
				frappe.db.delete("Chat Conversation", {"name": conv})


class TestRefusalReachesTheUser(FrappeTestCase):
	"""A refusal must say why, on every chat surface.

	RateLimited subclasses ValidationError, and each chat endpoint catches that
	broadly to mean "the BPMN instance is dead — tell them to reopen the chat".
	So a working throttle was reported to the user as "The ProsAlly process
	orchestration isn't running for this conversation", which is both wrong and
	unactionable. These pin the real message to each surface.
	"""

	SURFACES = ("ProsAlly", "Logix", "Docu")

	def test_the_engine_does_not_halt_the_instance_for_a_refusal(self):
		"""A refusal is a decision, not a fault.

		The engine wrapped every exception from a task into "this process has been
		halted due to an internal error, quote Reference ID …" and marked the
		instance Errored. For a rate limit that was wrong twice: the user got a
		reference id instead of the reason, and the conversation stayed broken
		even after a reviewer released the lock.
		"""
		from unittest.mock import patch

		from one_bpmn.security.rate_limit import RateLimited

		instance = frappe.new_doc("BPMN Process Instance")
		instance.name = "ZZ-INST"

		with patch.object(instance, "_record_runtime_failure") as recorded:
			try:
				frappe.throw("frozen", RateLimited)
			except RateLimited:
				with self.assertRaises(RateLimited):
					instance._fail_runtime("test")
		self.assertFalse(
			recorded.called,
			"a refusal must not be logged as a runtime failure or halt the instance",
		)

	def test_the_engine_still_halts_on_a_real_fault(self):
		"""The sanitising path is untouched for anything that is genuinely broken."""
		from unittest.mock import patch

		instance = frappe.new_doc("BPMN Process Instance")
		instance.name = "ZZ-INST"

		with patch.object(instance, "_record_runtime_failure", return_value="REF123") as recorded:
			try:
				raise RuntimeError("something actually broke")
			except RuntimeError:
				with self.assertRaises(frappe.ValidationError) as ctx:
					instance._fail_runtime("test")
		self.assertTrue(recorded.called)
		self.assertIn("REF123", str(ctx.exception))

	def test_the_delegation_layer_lets_a_refusal_through(self):
		"""Where the wrong message really came from.

		A map-driven agent raises the refusal deep inside the map: its "Save User
		Message" task inserts the Chat Message, and that insert's before_insert
		hook enforces the limit. The exception surfaced at
		_delegate_to_bpmn_instance, which caught ValidationError to mean "the
		instance is not waiting" and returned None — and the caller turned None
		into "the process is not running, please reopen the chat". Every endpoint
		below already had an `except RateLimited` branch; none of them could ever
		be reached, because the refusal was swallowed a layer earlier.
		"""
		from unittest.mock import patch

		from one_bpmn.api import server_script_api as SSA
		from one_bpmn.security.rate_limit import RateLimited

		class Instance:
			def receive_message(self, *args, **kwargs):
				frappe.throw("too quickly", RateLimited, title="Rate Limit Reached")

		with patch.object(
			frappe.db, "get_value",
			side_effect=lambda dt, *a, **k: frappe._dict({"name": "ZZ-INST", "status": "Active"})
			if dt == "BPMN Process Instance" else None,
		), patch.object(frappe, "get_doc", return_value=Instance()):
			with self.assertRaises(RateLimited):
				SSA._delegate_to_bpmn_instance("ZZ-CONV", "hello", {})

	def setUp(self):
		frappe.set_user("Administrator")
		self._settings(rate_limit_enabled=1, rate_limit_messages=1,
		               rate_limit_window_seconds=300, lock_after_blocks=0)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("AI Security Event", {"stage": "rate-limit"})
		for label in ("prosally_agent", "logix_agent", "docu_agent"):
			try:
				frappe.cache().delete(RL._window_key("Administrator", label))
			except Exception:
				pass
		frappe.db.commit()

	def _settings(self, **values):
		"""Override the rate-limit settings for this test ONLY.

		Deliberately does NOT write to Processa Settings. These tests used to set
		the live singleton and restore it in tearDown, so any interrupted run
		left the real site throttled at a test's values — which is exactly what
		happened: a user hit "limit 1" in normal use. Patching the reader keeps
		the blast radius inside the test.
		"""
		from one_bpmn.security import rate_limit as _RL

		current = dict(_RL._DEFAULTS)
		current.update(getattr(self, "_override", {}))
		current.update(values)
		self._override = current

		if getattr(self, "_settings_patch", None) is None:
			self._settings_patch = patch.object(_RL, "settings", lambda: dict(self._override))
			self._settings_patch.start()
			self.addCleanup(self._stop_settings_patch)

	def _stop_settings_patch(self):
		if getattr(self, "_settings_patch", None) is not None:
			self._settings_patch.stop()
			self._settings_patch = None
		self._override = {}

	def _exhaust(self, agent_label):
		"""Fill the window past the limit without making a model call."""
		key = RL._window_key("Administrator", agent_label)
		now = time.time()
		frappe.cache().zadd(key, {f"{now}:a": now, f"{now}:b": now})

	def _conversation(self, label):
		conv = frappe.db.get_value("Chat Conversation", {"agent_mode": label}, "name")
		if conv:
			return conv
		return frappe.get_doc({
			"doctype": "Chat Conversation", "agent_mode": label, "title": f"{PREFIX} {label}",
		}).insert(ignore_permissions=True).name

	def test_prosally_reports_the_refusal_not_a_dead_instance(self):
		from one_bpmn.api.server_script_api import prosally_chat

		self._exhaust("prosally_agent")
		r = prosally_chat(message="hi", session_id="t", conversation_name=self._conversation("ProsAlly")) or {}
		self.assertEqual(r.get("intent"), "BLOCKED")
		self.assertIn("too quickly", r.get("response", ""))
		self.assertNotIn("orchestration", r.get("response", ""))

	def test_logix_reports_the_refusal_not_a_dead_instance(self):
		from one_bpmn.api.server_script_api import process_logix_message

		self._exhaust("logix_agent")
		r = process_logix_message(message="hi", session_id="t", conversation_name=self._conversation("Logix")) or {}
		self.assertEqual(r.get("intent"), "BLOCKED")
		self.assertIn("too quickly", r.get("response", ""))
		self.assertNotIn("orchestration", r.get("response", ""))

	def test_docu_reports_the_refusal_not_a_dead_instance(self):
		from one_bpmn.api.docu_api import docu_chat

		self._exhaust("docu_agent")
		r = docu_chat(message="hi", conversation_name=self._conversation("Docu")) or {}
		self.assertEqual(r.get("intent"), "BLOCKED")
		self.assertIn("too quickly", r.get("response", ""))
		self.assertNotIn("orchestration", r.get("response", ""))

	def test_a_frozen_conversation_says_so_rather_than_blaming_the_instance(self):
		from one_bpmn.api.server_script_api import prosally_chat

		agent = frappe.db.get_value("AI Agent Configuration", {"chat_mode_label": "ProsAlly"}, "name")
		conv = self._conversation("ProsAlly")
		lock = RL.raise_lock("Administrator", agent, conv, reason="Manual", blocked_count=3)
		try:
			r = prosally_chat(message="hi", session_id="t", conversation_name=conv) or {}
			self.assertEqual(r.get("intent"), "BLOCKED")
			self.assertIn("frozen", r.get("response", "").lower())
			self.assertIn("reviewer", r.get("response", "").lower())
		finally:
			frappe.db.delete("AI Conversation Lock", {"name": lock})
			frappe.db.commit()


class TestOneTurnCostsOneSlot(FrappeTestCase):
	"""A chat turn passes two gates and must consume one slot, not two.

	Correlation-id dedup was supposed to handle this, but the map runs the turn
	in a worker thread and a ContextVar does not cross threads — each gate minted
	its own id, so every message cost two of the allowance. With the shipped
	limit that halves it silently; the user who reported it was on limit 1 and
	could not send anything at all.
	"""

	AGENT_LABEL = "zz_wi1968_slots"

	def setUp(self):
		frappe.set_user("Administrator")
		self._flush()

	def tearDown(self):
		self._flush()
		frappe.db.delete("AI Security Event", {"stage": "rate-limit"})
		frappe.db.commit()

	def _flush(self):
		try:
			frappe.cache().delete(RL._window_key("Administrator", self.AGENT_LABEL))
		except Exception:
			pass

	def _window_size(self):
		return int(frappe.cache().zcard(RL._window_key("Administrator", self.AGENT_LABEL)))

	def test_a_checking_gate_does_not_add_to_the_window(self):
		RL.enforce(user="Administrator", agent=None, agent_label=self.AGENT_LABEL,
		           conversation="X", count=False)
		self.assertEqual(self._window_size(), 0, "a check must not consume allowance")

	def test_a_turn_through_both_gates_counts_once(self):
		for _ in range(3):
			RL.enforce(user="Administrator", agent=None, agent_label=self.AGENT_LABEL,
			           conversation="X", count=False)   # API gate
			RL.enforce(user="Administrator", agent=None, agent_label=self.AGENT_LABEL,
			           conversation="X", count=True)    # Chat Message gate
		self.assertEqual(self._window_size(), 3, "three turns must cost three slots")

	def test_counting_does_not_depend_on_the_turn_id(self):
		"""The original bug in one line.

		Dedup used to rely on the turn's correlation id, which lives in a
		ContextVar — and the map runs the turn in a worker thread, so the second
		gate saw no id and minted its own. Counting is now pinned to a single
		gate instead, so it holds even when the two gates share nothing at all.
		Clearing the id between them stands in for that thread boundary.
		"""
		from one_bpmn.security import turn as T

		T.begin_turn()
		RL.enforce(user="Administrator", agent=None, agent_label=self.AGENT_LABEL,
		           conversation="X", count=False)   # API gate, one context
		T.end_turn()                                # the worker thread sees none of it
		RL.enforce(user="Administrator", agent=None, agent_label=self.AGENT_LABEL,
		           conversation="X", count=True)    # Chat Message gate, another
		self.assertEqual(self._window_size(), 1, "one turn, one slot, whatever the id")

	def test_peek_never_throttles_when_the_cache_is_broken(self):
		with patch("frappe.cache", side_effect=RuntimeError("redis down")):
			self.assertEqual(RL.peek_count("Administrator", self.AGENT_LABEL, 60), -1)
