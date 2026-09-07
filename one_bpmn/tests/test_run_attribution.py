# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""What a run was made of, and what text made it (WI-002190).

Three gaps, one theme: a run's record did not describe the run.

  - Model calls made from inside tool scripts were never recorded, so the
    cost dashboard metered the orchestrator's cheap turns and missed the
    expensive ones its tools made.
  - A run started by a tool inside another run shared only a correlation_id
    with its parent, so a turn read as a flat list of unrelated runs.
  - The system prompt was stored nowhere at all, so when it changed nothing
    said which runs used which version.

    bench run-tests --skip-before-tests --module one_bpmn.tests.test_run_attribution
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import observability as obs


class RunFixture(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags[obs._CURRENT_RUN_FLAG] = None
		frappe.flags[obs._SUB_CALL_FLAG] = None

	def _run(self, **kw):
		doc = frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"bpmn_id": "attribution_probe",
				"status": "Running",
				"started_at": frappe.utils.now_datetime(),
				**kw,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda n=doc.name: (
				frappe.db.exists("AI Agent Run", n)
				and frappe.delete_doc("AI Agent Run", n, force=True, ignore_permissions=True)
			)
		)
		return doc


class _Result:
	"""Stands in for a CompletionResult, which sums these off its trace."""

	def __init__(self, text="", prompt=0, completion=0):
		self.text = text
		self.prompt_tokens = prompt
		self.completion_tokens = completion
		self.cache_read_tokens = 0
		self.cache_write_tokens = 0


class TestSubCallsAreMetered(RunFixture):
	def test_a_call_inside_a_tool_becomes_a_step(self):
		run = self._run(model="claude-haiku-4-5-20251001")
		with obs.sub_call_scope(run, "classify"):
			obs.record_sub_call("claude-sonnet-4-5", _Result("verdict", 4000, 200), latency_ms=900)

		steps = frappe.get_all(
			"AI Agent Step",
			filters={"run": run.name},
			fields=["content", "prompt_tokens", "completion_tokens", "latency_ms"],
		)
		self.assertEqual(len(steps), 1)
		self.assertIn("classify", steps[0].content, "the step says which tool spent this")
		self.assertIn("claude-sonnet-4-5", steps[0].content, "and on which model")
		self.assertEqual(steps[0].prompt_tokens, 4000)
		self.assertEqual(steps[0].latency_ms, 900)

	def test_outside_a_tool_nothing_is_recorded(self):
		"""The executor records its own turns. Recording here too would count
		every orchestrator call twice."""
		run = self._run()
		obs.record_sub_call("claude-sonnet-4-5", _Result("x", 100, 10))
		self.assertEqual(frappe.get_all("AI Agent Step", filters={"run": run.name}), [])

	def test_the_scope_is_restored_not_cleared(self):
		"""A tool that calls another tool must not lose its own attribution."""
		run = self._run()
		with obs.sub_call_scope(run, "outer"):
			with obs.sub_call_scope(run, "inner"):
				self.assertEqual(obs.current_sub_call()["tool"], "inner")
			self.assertEqual(obs.current_sub_call()["tool"], "outer")
		self.assertIsNone(obs.current_sub_call())

	def test_the_run_keeps_its_own_model(self):
		"""A run on Haiku spending on Sonnet still reports as a Haiku run."""
		run = self._run(model="claude-haiku-4-5-20251001")
		with obs.sub_call_scope(run, "generate"):
			obs.record_sub_call("claude-sonnet-4-5", _Result("x", 10, 1))
		self.assertEqual(frappe.db.get_value("AI Agent Run", run.name, "model"), "claude-haiku-4-5-20251001")


class TestPromptsAreIdentified(RunFixture):
	def test_the_text_is_stored_once_and_named_by_its_hash(self):
		digest = obs.snapshot_prompt("You are a careful assistant.")
		self.addCleanup(
			lambda: (
				frappe.db.exists("AI Prompt Snapshot", digest)
				and frappe.delete_doc("AI Prompt Snapshot", digest, force=True, ignore_permissions=True)
			)
		)
		self.assertTrue(digest)
		row = frappe.get_doc("AI Prompt Snapshot", digest)
		self.assertEqual(row.system_prompt, "You are a careful assistant.")
		self.assertEqual(row.char_count, len("You are a careful assistant."))

	def test_the_same_prompt_does_not_pile_up_rows(self):
		a = obs.snapshot_prompt("identical text")
		b = obs.snapshot_prompt("identical text")
		self.addCleanup(
			lambda: (
				frappe.db.exists("AI Prompt Snapshot", a)
				and frappe.delete_doc("AI Prompt Snapshot", a, force=True, ignore_permissions=True)
			)
		)
		self.assertEqual(a, b)
		self.assertEqual(frappe.db.count("AI Prompt Snapshot", {"prompt_hash": a}), 1)

	def test_a_changed_prompt_is_a_different_version(self):
		a = obs.snapshot_prompt("version one")
		b = obs.snapshot_prompt("version two")
		for d in (a, b):
			self.addCleanup(
				lambda n=d: (
					frappe.db.exists("AI Prompt Snapshot", n)
					and frappe.delete_doc("AI Prompt Snapshot", n, force=True, ignore_permissions=True)
				)
			)
		self.assertNotEqual(a, b, "results either side must be comparable")

	def test_no_prompt_is_not_a_version(self):
		self.assertEqual(obs.snapshot_prompt(""), "")
		self.assertEqual(obs.snapshot_prompt(None), "")


class TestNestedRunsFormATree(RunFixture):
	def test_a_finished_child_hands_the_current_run_back_to_its_parent(self):
		"""Clearing to None instead would stop metering everything the parent
		did after the nested run returned."""
		from one_bpmn.agents.executor import ExecutorResult

		parent = self._run()
		frappe.flags[obs._CURRENT_RUN_FLAG] = parent.name
		child = self._run(parent_run=parent.name)

		obs.finalize_ai_run(child, ExecutorResult(output="done"))
		self.assertEqual(obs.current_run_name(), parent.name)

	def test_a_top_level_run_leaves_nothing_current(self):
		from one_bpmn.agents.executor import ExecutorResult

		run = self._run()
		frappe.flags[obs._CURRENT_RUN_FLAG] = run.name
		obs.finalize_ai_run(run, ExecutorResult(output="done"))
		self.assertIsNone(obs.current_run_name())
