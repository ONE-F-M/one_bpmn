"""The clean-up of runs whose resumes wrote turns again and whose turn cap step repeated the run's tokens."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from one_bpmn.one_bpmn.patches.v1_0 import dedupe_resumed_run_steps as patch

RUN_FIELDS = [
	"total_prompt_tokens",
	"total_completion_tokens",
	"total_tokens",
	"estimated_cost",
	"agent_latency_ms",
	"duration_ms",
]


class TestDedupeResumedRunSteps(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def _run(self, **totals):
		return frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"bpmn_id": "dedupe_probe",
				"status": "Error",
				"started_at": frappe.utils.now_datetime(),
				**totals,
			}
		).insert(ignore_permissions=True)

	def _step(
		self, run, index, kind, content, prompt=0, completion=0, cost=0.0, latency=0, error=None, role="tool"
	):
		doc = frappe.get_doc(
			{
				"doctype": "AI Agent Step",
				"run": run.name,
				"step_index": index,
				"role": role,
				"step_kind": kind,
				"content": content,
				"prompt_tokens": prompt,
				"completion_tokens": completion,
				"cost": cost,
				"latency_ms": latency,
				"error_message": error,
			}
		)
		doc.db_insert()
		return doc

	def _row(self, run):
		return frappe.db.get_value("AI Agent Run", run.name, RUN_FIELDS, as_dict=True)

	def _steps(self, run):
		return frappe.get_all(
			"AI Agent Step",
			filters={"run": run.name},
			fields=[
				"step_index",
				"content",
				"prompt_tokens",
				"completion_tokens",
				"cost",
				"latency_ms",
				"error_message",
			],
			order_by="step_index asc",
		)

	def _resumed_run(self):
		"""Two turns written twice by a resume, then a turn cap step repeating all of it."""
		run = self._run(
			total_prompt_tokens=1500, total_completion_tokens=300, estimated_cost=3.0, duration_ms=12345
		)
		self._step(run, 1, "prompt", "system prompt", role="system")
		for index in (2, 4):
			self._step(run, index, "tool_turn", "turn one", prompt=100, completion=20, cost=0.1, latency=10)
			self._step(
				run, index + 1, "model_call", "turn two", prompt=150, completion=30, cost=0.2, latency=20
			)
		self._step(
			run,
			6,
			"model_call",
			"",
			prompt=500,
			completion=100,
			cost=0.6,
			latency=60,
			error="turn cap exhausted",
			role="assistant",
		)
		return run

	def test_repeated_turns_go_and_the_turn_cap_step_is_zeroed(self):
		run = self._resumed_run()
		patch.execute()

		steps = self._steps(run)
		self.assertEqual([s.content for s in steps], ["system prompt", "turn one", "turn two", ""])
		self.assertEqual([s.step_index for s in steps], [1, 2, 3, 6])
		cap = steps[-1]
		self.assertEqual(
			(cap.prompt_tokens, cap.completion_tokens, flt(cap.cost), cap.latency_ms), (0, 0, 0, 0)
		)
		self.assertEqual(cap.error_message, "turn cap exhausted")

	def test_run_totals_come_from_the_remaining_steps_and_duration_is_kept(self):
		run = self._resumed_run()
		patch.execute()

		row = self._row(run)
		self.assertEqual(row.total_prompt_tokens, 250)
		self.assertEqual(row.total_completion_tokens, 50)
		self.assertEqual(row.total_tokens, 300)
		self.assertAlmostEqual(flt(row.estimated_cost), 0.3)
		self.assertEqual(row.agent_latency_ms, 30)
		self.assertEqual(row.duration_ms, 12345)

	def test_a_real_failed_call_and_a_clean_run_are_not_touched(self):
		failed = self._run(total_prompt_tokens=999, total_completion_tokens=99, estimated_cost=9.0)
		self._step(
			failed,
			1,
			"model_call",
			"",
			prompt=30,
			completion=3,
			cost=0.05,
			latency=5,
			error="provider timeout",
		)
		self._step(failed, 2, "model_call", "answer", prompt=40, completion=4, cost=0.06, latency=6)
		clean = self._run(total_prompt_tokens=777, estimated_cost=7.0)
		self._step(clean, 1, "tool_turn", "only turn", prompt=10, completion=1, cost=0.01, latency=1)
		before = (self._row(failed), self._steps(failed), self._row(clean), self._steps(clean))

		patch.execute()

		self.assertEqual(
			(self._row(failed), self._steps(failed), self._row(clean), self._steps(clean)), before
		)

	def test_turns_with_the_same_figures_but_different_text_are_kept_and_the_run_untouched(self):
		run = self._run(total_prompt_tokens=555, estimated_cost=5.0)
		self._step(run, 1, "tool_turn", "first", prompt=0, completion=0)
		self._step(run, 2, "tool_turn", "second", prompt=0, completion=0)
		before = (self._row(run), self._steps(run))

		patch.execute()

		self.assertEqual((self._row(run), self._steps(run)), before)

	def test_a_second_run_changes_nothing(self):
		run = self._resumed_run()
		patch.execute()
		once = (self._row(run), self._steps(run))

		patch.execute()

		self.assertEqual((self._row(run), self._steps(run)), once)
