# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A run reads as what happened (WI-002190 follow-ups).

Four things the first pass left open, each seen on staging on 2026-09-08:

  - a sub-call step and a loop turn could share a step index (run jt89pn9jur
    had two steps numbered 1), because sub-calls are written while the loop
    runs and the turns afterwards, both from "count + 1";
  - a tool that failed left its step with no error, so the error fields were
    still empty on every step the day a Lucidchart fetch returned 403;
  - the Insights step table read a tool_name field the step has never had, so
    its Tool column always showed a dash;
  - the runs a tool started sat beside their parent as unrelated rows, and
    the parent's totals left them out.

    bench run-tests --skip-before-tests --module one_bpmn.tests.test_run_tree
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import observability as obs
from one_bpmn.api.insights_api import get_recent_runs, get_run_steps, get_run_tree


class _Result:
	def __init__(self, text="", prompt=0, completion=0):
		self.text = text
		self.prompt_tokens = prompt
		self.completion_tokens = completion
		self.cache_read_tokens = 0
		self.cache_write_tokens = 0


class RunTreeFixture(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.flags[obs._CURRENT_RUN_FLAG] = None
		frappe.flags[obs._SUB_CALL_FLAG] = None
		frappe.flags[obs.SUB_CALL_TURN_FLAG] = None
		self.probe = f"tree_probe_{frappe.generate_hash(length=6)}"

	def _run(self, **kw):
		values = {
			"doctype": "AI Agent Run",
			"bpmn_id": self.probe,
			"status": "Success",
			"model": "claude-haiku-4-5-20251001",
			"started_at": frappe.utils.now_datetime(),
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

	@staticmethod
	def _indexes(run_name):
		return frappe.get_all(
			"AI Agent Step",
			filters={"run": run_name},
			fields=["step_index", "role", "content"],
			order_by="step_index asc",
		)


class TestStepNumbering(RunTreeFixture):
	def test_a_sub_call_follows_the_turn_that_made_it(self):
		"""System and user first, then each turn, then the sub-calls its tools
		made, then the final answer. Every index unique."""
		run = self._run(status="Running")
		obs.record_ai_step(run, 1, "system", "sys")
		obs.record_ai_step(run, 2, "user", "hello")

		# The loop is on turn 1; its review tool asks the model something.
		frappe.flags[obs.SUB_CALL_TURN_FLAG] = 1
		with obs.sub_call_scope(run, "review_script"):
			obs.record_sub_call("claude-sonnet-4-5", _Result("approved", 400, 20))
		frappe.flags[obs.SUB_CALL_TURN_FLAG] = None

		obs.record_selector_turns(
			run,
			[
				{"role": "tool", "content": "", "turn_no": 1,
				 "tool_calls": [{"name": "review_script", "arguments": {}, "result": "{}"}]},
				{"role": "assistant", "content": "done", "turn_no": 2},
			],
		)

		rows = self._indexes(run.name)
		self.assertEqual([r.step_index for r in rows], [1, 2, 3, 4, 5])
		self.assertEqual([r.role for r in rows], ["system", "user", "tool", "assistant", "assistant"])
		self.assertTrue(rows[3].content.startswith("[sub-call: review_script via claude-sonnet-4-5; turn 1]"))
		self.assertEqual(rows[4].content, "done")

	def test_an_untagged_sub_call_comes_after_the_turns(self):
		run = self._run(status="Running")
		obs.record_ai_step(run, 1, "system", "sys")
		with obs.sub_call_scope(run, "classify"):
			obs.record_sub_call("claude-sonnet-4-5", _Result("x", 10, 1))
		obs.record_selector_turns(run, [{"role": "assistant", "content": "done"}])

		rows = self._indexes(run.name)
		self.assertEqual([r.step_index for r in rows], [1, 2, 3])
		self.assertEqual(rows[1].content, "done")
		self.assertIn("[sub-call: classify", rows[2].content)

	def test_indexes_never_collide_when_the_prompt_steps_were_written_late(self):
		"""Older code wrote system/user after the loop. Even then the turns are
		numbered past every ordinary step already present."""
		run = self._run(status="Running")
		with obs.sub_call_scope(run, "review_script"):
			obs.record_sub_call("claude-sonnet-4-5", _Result("x", 10, 1))
		obs.record_ai_step(run, 1, "system", "sys")
		obs.record_ai_step(run, 2, "user", "hello")
		obs.record_selector_turns(run, [{"role": "assistant", "content": "done"}])

		indexes = [r.step_index for r in self._indexes(run.name)]
		self.assertEqual(len(indexes), len(set(indexes)), indexes)
		self.assertEqual(sorted(indexes), [1, 2, 3, 4])

	def test_the_tag_round_trips(self):
		tag = obs.sub_call_tag("review_script", "claude-sonnet-4-5", 3)
		self.assertEqual(
			obs.parse_sub_call(tag + "\nbody"),
			{"tool": "review_script", "model": "claude-sonnet-4-5", "turn_no": 3},
		)
		self.assertEqual(
			obs.parse_sub_call("[sub-call: classify via claude-haiku-4-5-20251001]\n"),
			{"tool": "classify", "model": "claude-haiku-4-5-20251001", "turn_no": None},
		)
		self.assertIsNone(obs.parse_sub_call("plain reply"))
		self.assertIsNone(obs.parse_sub_call(None))


class TestToolFailuresReachTheStep(RunTreeFixture):
	def test_a_failed_tool_marks_its_step(self):
		run = self._run(status="Running")
		obs.record_selector_turns(
			run,
			[{
				"role": "tool", "content": "", "turn_no": 1,
				"tool_calls": [
					{"name": "fetch_lucidchart_document", "arguments": {}, "result": "Error calling fetch_lucidchart_document: 403 Forbidden"},
					{"name": "finalize", "arguments": {}, "result": "{}"},
				],
			}],
		)
		step = frappe.get_all(
			"AI Agent Step", filters={"run": run.name}, fields=["error_code", "error_message"]
		)[0]
		self.assertEqual(step.error_code, "TOOL_ERROR")
		self.assertIn("fetch_lucidchart_document: Error calling", step.error_message)
		self.assertIn("403 Forbidden", step.error_message)
		self.assertNotIn("finalize", step.error_message, "only the failing calls are named")

	def test_a_refused_call_is_denied_not_errored(self):
		run = self._run(status="Running")
		obs.record_selector_turns(
			run,
			[{"role": "tool", "turn_no": 1,
			  "tool_calls": [{"name": "delete_everything", "arguments": {}, "result": "Blocked by policy: not allowed"}]}],
		)
		step = frappe.get_all("AI Agent Step", filters={"run": run.name}, fields=["error_code"])[0]
		self.assertEqual(step.error_code, "TOOL_DENIED")

	def test_a_clean_turn_carries_no_error(self):
		run = self._run(status="Running")
		obs.record_selector_turns(
			run,
			[{"role": "tool", "turn_no": 1,
			  "tool_calls": [{"name": "finalize", "arguments": {}, "result": '{"ok": true}'}]}],
		)
		step = frappe.get_all("AI Agent Step", filters={"run": run.name}, fields=["error_code", "error_message"])[0]
		self.assertFalse(step.error_code)
		self.assertFalse(step.error_message)

	def test_argument_validation_refusals_count_as_errors(self):
		"""WI-002195 refuses a call before the script runs; that refusal is a
		failure of the step like any other."""
		self.assertEqual(
			obs._tool_call_status("Missing required argument 'state' for tool wi_set_state"), "Error"
		)
		self.assertEqual(obs._tool_call_status("Argument 'n' for tool t must be integer, got str"), "Error")
		self.assertEqual(obs._tool_call_status("Unknown tool: nope"), "Error")
		self.assertEqual(obs._tool_call_status("Blocked by policy: no"), "Denied")
		self.assertEqual(obs._tool_call_status("all good"), "Success")


class TestRunTree(RunTreeFixture):
	def _parent_with_children(self):
		parent = self._run(total_tokens=1000, estimated_cost=0.01)
		obs.record_ai_step(parent, 1, "system", "sys")
		obs.record_ai_step(
			parent, 2, "tool", "",
			tool_calls=[{"name": "classify_intent", "arguments": {}, "result": "{}"}],
		)
		obs.record_ai_step(
			parent, 3, "tool", "",
			tool_calls=[
				{"name": "write_script", "arguments": {}, "result": "{}"},
				{"name": "write_script", "arguments": {}, "result": "{}"},
			],
		)
		classify = self._run(bpmn_id="classify_intent", parent_run=parent.name, total_tokens=100, estimated_cost=0.001)
		obs.record_ai_step(classify, 1, "assistant", "CREATE")
		writer_a = self._run(bpmn_id="write_script", parent_run=parent.name, total_tokens=200, estimated_cost=0.002)
		writer_b = self._run(bpmn_id="write_script", parent_run=parent.name, total_tokens=300, estimated_cost=0.003)
		stray = self._run(bpmn_id="something_else", parent_run=parent.name, total_tokens=50, estimated_cost=0.0005)
		return parent, classify, writer_a, writer_b, stray

	def test_children_nest_under_the_step_that_called_them(self):
		parent, classify, writer_a, writer_b, stray = self._parent_with_children()
		tree = get_run_tree(parent.name)

		self.assertEqual(tree["run"]["name"], parent.name)
		by_index = {s["step_index"]: s for s in tree["steps"]}
		self.assertEqual([c["run"]["name"] for c in by_index[2]["child_runs"]], [classify.name])
		self.assertEqual(
			sorted(c["run"]["name"] for c in by_index[3]["child_runs"]),
			sorted([writer_a.name, writer_b.name]),
		)
		self.assertEqual(by_index[1]["child_runs"], [])
		self.assertEqual([c["run"]["name"] for c in tree["unplaced_children"]], [stray.name])
		# The nested run brings its own steps along.
		self.assertEqual(by_index[2]["child_runs"][0]["steps"][0]["content"], "CREATE")

	def test_the_rollup_is_the_whole_turn(self):
		parent, *_ = self._parent_with_children()
		tree = get_run_tree(parent.name)
		self.assertEqual(tree["rollup"]["runs"], 5)
		self.assertEqual(tree["rollup"]["total_tokens"], 1000 + 100 + 200 + 300 + 50)
		self.assertAlmostEqual(tree["rollup"]["estimated_cost"], 0.0165, places=6)
		# The run's own figure is untouched: the parent still reports what it spent itself.
		self.assertEqual(tree["run"]["total_tokens"], 1000)

	def test_steps_name_their_tools_and_sub_calls(self):
		parent, *_ = self._parent_with_children()
		frappe.flags[obs.SUB_CALL_TURN_FLAG] = 2
		with obs.sub_call_scope(parent, "review_script"):
			obs.record_sub_call("claude-sonnet-4-5", _Result("ok", 10, 1))
		frappe.flags[obs.SUB_CALL_TURN_FLAG] = None

		steps = get_run_steps(parent.name)
		by_index = {s["step_index"]: s for s in steps}
		self.assertEqual(by_index[2]["tool_names"], ["classify_intent"])
		self.assertEqual(by_index[3]["tool_names"], ["write_script", "write_script"])
		self.assertIsNone(by_index[1]["sub_call"])
		sub = next(s for s in steps if s["sub_call"])
		self.assertEqual(sub["sub_call"]["tool"], "review_script")
		self.assertEqual(sub["sub_call"]["model"], "claude-sonnet-4-5")
		self.assertEqual(sub["role"], "assistant")

	def test_recent_runs_list_parents_only_with_their_tree_totals(self):
		parent, classify, writer_a, writer_b, stray = self._parent_with_children()
		grandchild = self._run(bpmn_id="deeper", parent_run=classify.name, total_tokens=7, estimated_cost=0.0001)

		rows = get_recent_runs(bpmn_id=self.probe, status="Success")
		self.assertEqual([r["name"] for r in rows], [parent.name], "children never list on their own")
		row = rows[0]
		self.assertEqual(row["child_runs"], 5)
		self.assertEqual(row["tree_total_tokens"], 1000 + 100 + 200 + 300 + 50 + 7)
		self.assertAlmostEqual(row["tree_estimated_cost"], 0.0166, places=6)
		self.assertEqual(row["total_tokens"], 1000)

	def test_a_run_without_children_has_a_plain_tree(self):
		run = self._run(total_tokens=10)
		obs.record_ai_step(run, 1, "assistant", "hi")
		tree = get_run_tree(run.name)
		self.assertEqual(tree["rollup"]["runs"], 1)
		self.assertEqual(tree["unplaced_children"], [])
		self.assertEqual(tree["steps"][0]["child_runs"], [])
		self.assertEqual(tree["steps"][0]["tool_names"], [])

	def test_a_missing_run_is_an_error(self):
		with self.assertRaises(frappe.DoesNotExistError):
			get_run_tree("no-such-run")
