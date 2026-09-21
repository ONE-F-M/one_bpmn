# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The runs page behind /processa/runs.

bench run-tests --skip-before-tests --module one_bpmn.tests.test_runs_page
"""

from __future__ import annotations

from datetime import timedelta

import frappe
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_datetime, now_datetime

from one_bpmn.agents import observability as obs
from one_bpmn.api.insights_api import get_run_detail, get_run_steps, list_runs, run_filter_options

test_ignore = ["BPMN Process Instance", "BPMN Process Model"]


class RunsPageFixture(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.agent = f"runs-page-agent-{frappe.generate_hash(length=6)}"
		instance = frappe.get_doc(
			{"doctype": "BPMN Process Instance", "status": "Completed", "initiated_by": "Administrator"}
		)
		instance.flags.ignore_mandatory = True
		instance.insert(ignore_permissions=True, ignore_mandatory=True)
		cls.instance = instance.name

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags[obs._CURRENT_RUN_FLAG] = None
		frappe.flags[obs._SUB_CALL_FLAG] = None
		frappe.flags[obs.SUB_CALL_TURN_FLAG] = None

	def _run(self, **kw):
		values = {
			"doctype": "AI Agent Run",
			"instance": self.instance,
			"bpmn_id": "Activity_Agent",
			"bpmn_label": "Run the agent",
			"agent_configuration": None,
			"status": "Success",
			"model": "claude-haiku-4-5-20251001",
			"started_at": now_datetime(),
			"ended_at": now_datetime(),
			"agent_latency_ms": 1000,
			"total_tokens": 100,
			"estimated_cost": 0.01,
		}
		values.update(kw)
		doc = frappe.get_doc(values).insert(ignore_permissions=True)
		self.addCleanup(
			lambda n=doc.name: (
				frappe.db.exists("AI Agent Run", n)
				and frappe.delete_doc("AI Agent Run", n, force=True, ignore_permissions=True)
			)
		)
		return doc


class TestStepRecording(RunsPageFixture):
	def test_a_step_written_after_the_fact_still_gets_a_window(self):
		run = self._run()
		before = now_datetime()
		step = obs.record_ai_step(run, 1, "assistant", "hello", latency_ms=4000)
		self.assertIsNotNone(step.started_at)
		self.assertIsNotNone(step.ended_at)
		self.assertAlmostEqual(
			(get_datetime(step.ended_at) - get_datetime(step.started_at)).total_seconds(), 4.0, places=1
		)
		self.assertGreaterEqual(get_datetime(step.ended_at), before.replace(microsecond=0))

	def test_a_turn_with_its_own_window_keeps_it(self):
		run = self._run()
		start = add_to_date(now_datetime(), minutes=-10)
		end = add_to_date(start, seconds=3)
		obs.record_selector_turns(
			run,
			[
				{
					"role": "assistant",
					"content": "done",
					"latency_ms": 3000,
					"started_at": start.isoformat(sep=" "),
					"ended_at": end.isoformat(sep=" "),
				}
			],
		)
		row = frappe.get_all(
			"AI Agent Step", filters={"run": run.name}, fields=["started_at", "ended_at", "step_kind"]
		)[0]
		self.assertEqual(get_datetime(row.started_at).replace(microsecond=0), start.replace(microsecond=0))
		self.assertEqual(get_datetime(row.ended_at).replace(microsecond=0), end.replace(microsecond=0))
		self.assertEqual(row.step_kind, "model_call")

	def test_step_kinds(self):
		run = self._run()
		obs.record_ai_step(run, 1, "system", "sys")
		obs.record_ai_step(run, 2, "user", "hi")
		obs.record_ai_step(
			run, 3, "tool", "", tool_calls=[{"name": "lookup", "arguments": {}, "result": "{}"}]
		)
		with obs.sub_call_scope(run, "review_script"):
			obs.record_sub_call(
				"claude-sonnet-4-5",
				frappe._dict(
					text="ok", prompt_tokens=1, completion_tokens=1, cache_read_tokens=0, cache_write_tokens=0
				),
			)
		obs.record_ai_step(run, 5, "assistant", "final")
		kinds = [
			r.step_kind
			for r in frappe.get_all(
				"AI Agent Step", filters={"run": run.name}, fields=["step_kind"], order_by="step_index asc"
			)
		]
		self.assertEqual(kinds, ["prompt", "prompt", "tool_turn", "sub_call", "model_call"])

	def test_classify_step_reads_the_sub_call_tag(self):
		self.assertEqual(obs.classify_step("assistant", "[sub-call: x via m]\nbody"), "sub_call")
		self.assertEqual(obs.classify_step("assistant", "plain"), "model_call")
		self.assertEqual(obs.classify_step("tool", ""), "tool_turn")
		self.assertEqual(obs.classify_step("system", "x"), "prompt")

	def test_run_steps_carry_the_new_columns(self):
		run = self._run()
		obs.record_ai_step(run, 1, "assistant", "final", latency_ms=10)
		steps = get_run_steps(run.name)
		self.assertEqual(steps[0]["step_kind"], "model_call")
		self.assertIn("started_at", steps[0])
		self.assertIn("ended_at", steps[0])


class TestListRuns(RunsPageFixture):
	def test_lists_top_level_runs_with_counts_and_tiles(self):
		parent = self._run(agent_latency_ms=5000, estimated_cost=0.5, total_tokens=1000)
		child = self._run(parent_run=parent.name, estimated_cost=0.25, total_tokens=500)
		obs.record_ai_step(parent, 1, "user", "hi")
		obs.record_ai_step(
			parent,
			2,
			"tool",
			"",
			tool_calls=[
				{"name": "a", "arguments": {}, "result": "Error calling a: boom", "status": "Error"},
				{"name": "b", "arguments": {}, "result": "{}"},
			],
			error_code="TOOL_ERROR",
			error_message="a: boom",
		)

		page = list_runs(instance=self.instance, origin="all", page_length=50)
		names = [r.name for r in page["runs"]]
		self.assertIn(parent.name, names)
		self.assertNotIn(child.name, names)
		row = next(r for r in page["runs"] if r.name == parent.name)
		self.assertEqual(row.steps, 2)
		self.assertEqual(row.tool_calls, 2)
		self.assertEqual(row.failed_steps, 1)
		self.assertEqual(row.child_runs, 1)
		self.assertAlmostEqual(row.tree_estimated_cost, 0.75, places=4)
		self.assertEqual(row.tree_total_tokens, 1500)
		self.assertEqual(row.user, "Administrator")

		summary = page["summary"]
		self.assertEqual(summary["runs"], page["total"])
		self.assertGreaterEqual(summary["error_runs"], 1)
		self.assertGreaterEqual(summary["steps"], 2)
		self.assertGreater(summary["median_latency_ms"], 0)

	def test_errors_only_keeps_runs_with_a_failed_step_or_error_status(self):
		clean = self._run()
		errored = self._run(status="Error", error_code="TIMEOUT")
		failed_step = self._run()
		obs.record_ai_step(failed_step, 1, "tool", "", error_code="TOOL_ERROR", error_message="x")
		names = [
			r.name
			for r in list_runs(instance=self.instance, origin="all", errors_only=1, page_length=50)["runs"]
		]
		self.assertIn(errored.name, names)
		self.assertIn(failed_step.name, names)
		self.assertNotIn(clean.name, names)

	def test_filters_and_order(self):
		slow = self._run(agent_latency_ms=9000, model="model-slow")
		fast = self._run(agent_latency_ms=1, model="model-fast")
		by_latency = list_runs(instance=self.instance, origin="all", order="slowest", page_length=50)["runs"]
		self.assertEqual(by_latency[0].name, slow.name)
		only_fast = list_runs(instance=self.instance, origin="all", model="model-fast", page_length=50)[
			"runs"
		]
		self.assertEqual([r.name for r in only_fast], [fast.name])
		self.assertEqual(
			list_runs(instance=self.instance, origin="all", user="nobody@example.com")["total"], 0
		)

	def test_search_matches_the_final_output(self):
		hit = self._run(final_output="the needle is here")
		self._run(final_output="hay")
		names = [
			r.name
			for r in list_runs(instance=self.instance, origin="all", search="needle", page_length=50)["runs"]
		]
		self.assertEqual(names, [hit.name])

	def test_filter_options_include_the_runs_people(self):
		self._run()
		options = run_filter_options(origin="all")
		self.assertIn("Administrator", options["users"])
		self.assertIn("claude-haiku-4-5-20251001", options["models"])

	def test_only_a_system_manager_may_list(self):
		"""The user is made here rather than borrowed from the site: picking
		whatever account happens to exist made this pass or fail depending on
		which bench it ran on."""
		email = f"_runs_page_{frappe.generate_hash(length=8)}@example.com"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Runs Page",
				"send_welcome_email": 0,
				"roles": [],
			}
		)
		user.flags.ignore_permissions = True
		user.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.set_user("Administrator"))

		frappe.set_user(email)
		self.assertNotIn("System Manager", frappe.get_roles())

		# frappe.only_for is a no-op while in_test is set, so the guard cannot
		# fire unless the flag is cleared. Both calls below only read.
		frappe.flags.in_test = False
		try:
			with self.assertRaises(frappe.PermissionError):
				list_runs()
			with self.assertRaises(frappe.PermissionError):
				get_run_detail("x")
		finally:
			frappe.flags.in_test = True


class TestRunDetail(RunsPageFixture):
	def test_detail_carries_instance_tree_and_siblings(self):
		first = self._run(started_at=add_to_date(now_datetime(), minutes=-5), final_output="first answer")
		second = self._run(final_output="second answer")
		obs.record_ai_step(second, 1, "system", "the system prompt")
		obs.record_ai_step(
			second, 2, "tool", "", tool_calls=[{"name": "lookup", "arguments": {"q": 1}, "result": "{}"}]
		)
		obs.record_ai_step(second, 3, "assistant", "second answer")

		detail = get_run_detail(second.name)
		self.assertEqual(detail["run"]["name"], second.name)
		self.assertEqual(detail["instance"]["name"], self.instance)
		self.assertEqual(detail["system_prompt"], "the system prompt")
		self.assertEqual(
			[s["step_kind"] for s in detail["tree"]["steps"]], ["prompt", "tool_turn", "model_call"]
		)
		self.assertEqual(detail["tree"]["steps"][1]["tool_calls"][0]["tool_name"], "lookup")
		self.assertEqual([s.name for s in detail["siblings"]], [first.name, second.name])
		self.assertEqual(detail["siblings"][0]["final_output"], "first answer")

	def test_a_missing_run_is_an_error(self):
		with self.assertRaises(frappe.DoesNotExistError):
			get_run_detail("no-such-run")


class TestADelegatedRunKnowsItsCaller(FrappeTestCase):
	"""A run started by an A2A Task executes in its own request, so the
	in-request flag is empty and the chain has to come from the task."""

	def test_the_caller_on_the_task_becomes_the_parent(self):
		from one_bpmn.agents import observability

		instance = frappe._dict({
			"name": "INST-CHILD",
			"context_doctype": "A2A Task",
			"context_docname": "A2A-1",
		})
		with patch.object(observability.frappe.db, "get_value", return_value="RUN-PARENT"):
			self.assertEqual(observability._delegating_run(instance), "RUN-PARENT")

	def test_an_instance_that_is_not_a_delegation_has_no_parent(self):
		from one_bpmn.agents import observability

		instance = frappe._dict({
			"name": "INST-CHAT",
			"context_doctype": "Chat Conversation",
			"context_docname": "CONV-1",
		})
		self.assertIsNone(observability._delegating_run(instance))

	def test_a_task_that_records_no_caller_leaves_the_parent_empty(self):
		from one_bpmn.agents import observability

		instance = frappe._dict({
			"name": "INST-CHILD",
			"context_doctype": "A2A Task",
			"context_docname": "A2A-2",
		})
		with patch.object(observability.frappe.db, "get_value", return_value=None):
			self.assertIsNone(observability._delegating_run(instance))


class TestEveryRunNumbersItsStepsFromOne(RunsPageFixture):
	"""An earlier shift added one to every step row, so depending on when a run
	happened its first step reads 0, 1 or 2. Each run moves by its own offset."""

	def _steps(self, run, indexes):
		for index in indexes:
			doc = frappe.get_doc(
				{
					"doctype": "AI Agent Step",
					"run": run.name,
					"step_index": index,
					"role": "assistant",
					"content": "",
				}
			).insert(ignore_permissions=True)
			self.addCleanup(
				lambda n=doc.name: (
					frappe.db.exists("AI Agent Step", n)
					and frappe.delete_doc("AI Agent Step", n, force=True, ignore_permissions=True)
				)
			)

	def _indexes(self, run):
		return [
			s.step_index
			for s in frappe.get_all(
				"AI Agent Step",
				filters={"run": run.name},
				fields=["step_index"],
				order_by="step_index asc",
			)
		]

	def _execute(self):
		from one_bpmn.one_bpmn.patches.v1_0 import every_run_numbers_its_steps_from_one as patch

		patch.execute()

	def test_a_run_pushed_to_two_comes_back_to_one(self):
		run = self._run()
		self._steps(run, [2, 3, 4])
		self._execute()
		self.assertEqual(self._indexes(run), [1, 2, 3])

	def test_a_run_left_at_zero_moves_up(self):
		run = self._run()
		self._steps(run, [0, 1, 2])
		self._execute()
		self.assertEqual(self._indexes(run), [1, 2, 3])

	def test_a_run_already_right_is_left_alone(self):
		run = self._run()
		self._steps(run, [1, 2, 3])
		self._execute()
		self.assertEqual(self._indexes(run), [1, 2, 3])

	def test_running_it_twice_changes_nothing(self):
		run = self._run()
		self._steps(run, [2, 3])
		self._execute()
		self._execute()
		self.assertEqual(self._indexes(run), [1, 2])

	def test_runs_with_different_offsets_are_fixed_together(self):
		low = self._run()
		high = self._run()
		self._steps(low, [0, 1])
		self._steps(high, [2, 3])
		self._execute()
		self.assertEqual(self._indexes(low), [1, 2])
		self.assertEqual(self._indexes(high), [1, 2])
