# Writeback resilience: a transient distillation failure is retried, one that
# will not work is recorded instead of vanishing, and two writebacks for the
# same scope key do not lose each other's work.

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.memory import distill as D
from one_bpmn.agents.memory import tools as T
from one_bpmn.agents.memory import writeback as W

CTX = {"provider_name": "p", "backend": "direct_api", "model": "m"}
_ADD = {"action": "add", "supersedes": [], "degraded": None}


def _args(agent: str, output: str = "the agent said something worth keeping") -> dict:
	return {
		"agent_output": output,
		"agent": agent,
		"scope": "Agent",
		"scope_key": agent,
		"provider_name": "p",
		"backend": "direct_api",
		"model": "m",
		"source_run": None,
	}


class TestDistillationReportsFailure(FrappeTestCase):
	"""Nothing worth remembering and the call not working both used to be an
	empty list, so a broken model looked like a quiet conversation."""

	def test_an_empty_turn_is_still_an_empty_list(self):
		self.assertEqual(
			D.distill_memories("", agent="a", scope="Agent", scope_key="a", provider_name="p", model="m"), []
		)

	def test_no_model_is_silent_by_default_and_loud_when_asked(self):
		kwargs = dict(agent="a", scope="Agent", scope_key="a", provider_name="p", model=None)
		self.assertEqual(D.distill_memories("something", **kwargs), [])
		with self.assertRaises(D.DistillationFailed):
			D.distill_memories("something", raise_on_failure=True, **kwargs)


class TestRetry(FrappeTestCase):
	def setUp(self):
		self.agent = f"RT_{frappe.generate_hash(length=8)}"
		# The pauses are real seconds; the behaviour under test is the count.
		p = patch.object(W.time, "sleep")
		self.sleep = p.start()
		self.addCleanup(p.stop)

	def test_a_transient_failure_is_retried_and_succeeds(self):
		calls = {"n": 0}

		def flaky(*a, **kw):
			calls["n"] += 1
			if calls["n"] < 3:
				raise D.DistillationFailed("rate limited")
			return [{"content": "a durable fact", "topic": "t", "dedup_key": f"{self.agent}:t"}]

		with patch.object(D, "distill_memories", side_effect=flaky):
			facts = W._distill_with_retries(**_args(self.agent))

		self.assertEqual(calls["n"], 3)
		self.assertEqual(len(facts), 1)
		self.assertEqual(self.sleep.call_count, 2)

	def test_it_gives_up_after_the_bounded_number_of_tries(self):
		with patch.object(D, "distill_memories", side_effect=D.DistillationFailed("still broken")):
			facts = W._distill_with_retries(**_args(self.agent))
		self.assertEqual(facts, [])

	def test_a_first_time_success_is_not_slowed_down(self):
		with patch.object(D, "distill_memories", return_value=[]):
			W._distill_with_retries(**_args(self.agent))
		self.sleep.assert_not_called()


class TestDeadLetter(FrappeTestCase):
	def setUp(self):
		self.agent = f"DL_{frappe.generate_hash(length=8)}"
		p = patch.object(W.time, "sleep")
		p.start()
		self.addCleanup(p.stop)

	def _letters(self):
		return frappe.get_all("AI Memory Dead Letter", filters={"agent": self.agent}, fields=["*"])

	def test_a_failure_that_will_not_work_is_recorded_with_its_payload(self):
		with patch.object(D, "distill_memories", side_effect=D.DistillationFailed("the model is misconfigured")):
			W._distill_with_retries(**_args(self.agent, "everything the agent said"))

		letters = self._letters()
		self.assertEqual(len(letters), 1)
		self.assertEqual(letters[0].payload, "everything the agent said")
		self.assertIn("misconfigured", letters[0].error)
		self.assertEqual(letters[0].attempts, W.MAX_ATTEMPTS)
		self.assertEqual(letters[0].memory_scope, "Agent")
		self.assertEqual(letters[0].scope_key, self.agent)

	def test_the_caller_is_never_told(self):
		"""A background job must not surface a failure into the workflow, which
		is why this went unrecorded for so long."""
		with patch.object(D, "distill_memories", side_effect=D.DistillationFailed("boom")):
			written = W.distill_and_write(**_args(self.agent))
		self.assertEqual(written, [])
		self.assertEqual(len(self._letters()), 1)

	def test_a_success_leaves_nothing_behind(self):
		with patch.object(D, "distill_memories", return_value=[]):
			W._distill_with_retries(**_args(self.agent))
		self.assertEqual(self._letters(), [])

	def test_a_dead_letter_that_cannot_be_written_is_not_the_failure(self):
		"""This is the last thing between a failure and silence, so it swallows
		its own problems instead of becoming one."""
		with patch.object(D, "distill_memories", side_effect=D.DistillationFailed("boom")), patch.object(
			W, "_dead_letter", side_effect=RuntimeError("no doctype")
		), self.assertRaises(RuntimeError):
			W._distill_with_retries(**_args(self.agent))

	def test_the_recorder_swallows_its_own_failure(self):
		with patch("frappe.get_doc", side_effect=RuntimeError("no doctype")), patch("frappe.log_error"):
			W._dead_letter("payload", error="e", attempts=3, agent=self.agent, scope="Agent", scope_key=self.agent)
		self.assertEqual(self._letters(), [])


class TestScopeLock(FrappeTestCase):
	"""What is ours is which key gets which lock, when one is taken at all, and
	what happens when it cannot be had. That the lock excludes is the framework's
	own file lock doing its job and is not retested here."""

	def setUp(self):
		self.agent = f"LK_{frappe.generate_hash(length=8)}"

	def _name(self, scope_key):
		return T.scope_lock_name(T._resolve_scope("Agent", scope_key))

	def test_one_key_gets_one_lock_and_two_keys_get_two(self):
		self.assertEqual(self._name(self.agent), self._name(self.agent))
		self.assertNotEqual(self._name(self.agent), self._name(f"{self.agent}_other"))

	def test_one_person_does_not_wait_on_another(self):
		mine = self._name({"agent_element": self.agent, "user": "alice@example.com"})
		theirs = self._name({"agent_element": self.agent, "user": "bob@example.com"})
		shared = self._name(self.agent)
		self.assertNotEqual(mine, theirs)
		self.assertNotEqual(mine, shared)

	def test_the_name_is_safe_to_put_in_a_filename(self):
		name = self._name({"agent_element": self.agent, "user": "someone@example.com"})
		self.assertRegex(name, r"^ai-memory-[0-9a-f]{16}$")

	def test_reconciling_writes_take_the_lock_and_plain_writes_do_not(self):
		taken = []

		def fake_lock(keys):
			taken.append(keys)
			return nullcontext()

		with patch.object(T, "_scope_lock", side_effect=fake_lock):
			T.memory_write("Agent", self.agent, "a plain write", ignore_permissions=True)
			self.assertEqual(taken, [])
			with patch("one_bpmn.agents.memory.reconcile.reconcile", return_value=_ADD):
				T.memory_write(
					"Agent", self.agent, "a reconciled write", reconcile=True, reconcile_ctx=CTX, ignore_permissions=True
				)
		self.assertEqual(len(taken), 1)
		self.assertEqual(taken[0]["agent_element"], self.agent)

	def test_a_lock_nobody_can_get_still_writes_the_memory(self):
		"""Losing the memory is worse than the duplicate that racing produces."""
		with patch.object(T, "_scope_lock", side_effect=RuntimeError("held too long")), patch(
			"one_bpmn.agents.memory.reconcile.reconcile", return_value=_ADD
		):
			row = T.memory_write(
				"Agent", self.agent, "written anyway", reconcile=True, reconcile_ctx=CTX, ignore_permissions=True
			)
		self.assertTrue(frappe.db.exists("AI Memory", row["name"]))

	def test_the_corroboration_count_is_read_and_written_inside_the_lock(self):
		"""The lost update the lock exists to prevent: two writebacks that both
		read count 0 and both write 1."""
		first = T.memory_write("Agent", self.agent, "exports ship by DHL", ignore_permissions=True)
		with patch("one_bpmn.agents.memory.reconcile.reconcile", return_value={"action": "update", "supersedes": [first["name"]], "degraded": None}):
			second = T.memory_write(
				"Agent", self.agent, "all exports go by DHL", reconcile=True, reconcile_ctx=CTX, ignore_permissions=True
			)
			third = T.memory_write(
				"Agent", self.agent, "DHL carries every export", reconcile=True, reconcile_ctx=CTX, ignore_permissions=True
			)
		self.assertEqual(frappe.db.get_value("AI Memory", second["name"], "corroboration_count"), 1)
		self.assertEqual(frappe.db.get_value("AI Memory", third["name"], "corroboration_count"), 1)
