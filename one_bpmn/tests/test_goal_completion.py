"""
Did the run achieve what it was asked to do? (WI-001823)

Satisfaction is sparse and self-selected; completion is recorded on every run
with no user effort, which is what makes it usable for comparing agents. That
only holds if the values mean what they say — so the property these tests defend
hardest is that **Unknown is never coerced**. An undetermined run counted as a
success or a failure would bias every average built on it, invisibly, because
the row would still read as definite.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_goal_completion
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import goal_completion as gc
from one_bpmn.agents.executor import ErrorCode, ExecutorResult
from one_bpmn.agents.observability import finalize_ai_run


class TestWhatTheExecutorKnows(FrappeTestCase):
	"""determine() is pure — no database, no model, no guessing."""

	def test_a_clean_run_with_an_answer_achieved(self):
		state, basis = gc.determine(ExecutorResult(output="here is your answer"))
		self.assertEqual(state, gc.ACHIEVED)
		self.assertIn("without error", basis)

	def test_an_errored_run_is_not_achieved(self):
		state, basis = gc.determine(
			ExecutorResult(error_code=ErrorCode.FAILED_MODEL_CALL, error_message="boom")
		)
		self.assertEqual(state, gc.NOT_ACHIEVED)
		self.assertIn("FAILED_MODEL_CALL", basis)

	def test_the_turn_cap_is_not_achieved_and_says_so(self):
		"""It arrives as a model failure like any other, but it is a distinct
		outcome — the agent was still working, not broken — and the basis has to
		be readable enough that nobody has to open the trace to know which."""
		state, basis = gc.determine(
			ExecutorResult(hit_turn_cap=True, error_code=ErrorCode.FAILED_MODEL_CALL)
		)
		self.assertEqual(state, gc.NOT_ACHIEVED)
		self.assertIn("ran out of turns", basis)

	def test_a_clean_run_with_no_output_is_unknown_not_success(self):
		"""Finished without error but said nothing. Counting that as achieved
		would inflate every agent that quietly does nothing."""
		state, basis = gc.determine(ExecutorResult(output=""))
		self.assertEqual(state, gc.UNKNOWN)
		self.assertIn("no output", basis)

	def test_a_suspended_run_is_unknown_because_it_has_not_ended(self):
		state, basis = gc.determine(ExecutorResult(error_code=ErrorCode.SUSPENDED))
		self.assertEqual(state, gc.UNKNOWN)
		self.assertIn("not decided", basis)

	def test_no_result_at_all_is_unknown(self):
		state, _ = gc.determine(None)
		self.assertEqual(state, gc.UNKNOWN)

	def test_a_structured_reply_counts_as_an_answer(self):
		state, _ = gc.determine(ExecutorResult(output={"response": "done"}))
		self.assertEqual(state, gc.ACHIEVED)

	def test_an_empty_structured_reply_does_not(self):
		state, _ = gc.determine(ExecutorResult(output={"response": "", "bpmn_xml": ""}))
		self.assertEqual(state, gc.UNKNOWN)

	def test_every_basis_is_a_sentence_somebody_could_act_on(self):
		"""A number in a report has to be traceable to its evidence."""
		for result in (
			ExecutorResult(output="ok"),
			ExecutorResult(error_code=ErrorCode.FAILED_MODEL_CALL),
			ExecutorResult(hit_turn_cap=True, error_code=ErrorCode.FAILED_MODEL_CALL),
			ExecutorResult(output=""),
			ExecutorResult(error_code=ErrorCode.SUSPENDED),
		):
			_, basis = gc.determine(result)
			self.assertTrue(basis and basis.endswith("."), f"unhelpful basis: {basis!r}")


class TestAMapDeclaringItsOwnDefinitionOfDone(FrappeTestCase):
	"""Agents differ in what finishing means, so a map may name the reply key
	that proves it — declaratively, never as an expression to evaluate."""

	def test_the_declared_key_being_present_is_achievement(self):
		state, basis = gc.determine(
			ExecutorResult(output={"response": "here", "bpmn_xml": "<bpmn/>"}), goal_key="bpmn_xml"
		)
		self.assertEqual(state, gc.ACHIEVED)
		self.assertIn("bpmn_xml", basis)

	def test_a_chatty_reply_without_the_declared_key_is_not_achievement(self):
		"""The whole point: an agent that answered pleasantly but produced no
		diagram did not do what it was asked."""
		state, basis = gc.determine(
			ExecutorResult(output={"response": "I could not draw that"}), goal_key="bpmn_xml"
		)
		self.assertEqual(state, gc.NOT_ACHIEVED)
		self.assertIn("bpmn_xml", basis)

	def test_an_empty_declared_key_is_not_achievement(self):
		state, _ = gc.determine(ExecutorResult(output={"bpmn_xml": "   "}), goal_key="bpmn_xml")
		self.assertEqual(state, gc.NOT_ACHIEVED)

	def test_a_declared_key_does_not_rescue_an_errored_run(self):
		state, basis = gc.determine(
			ExecutorResult(output={"bpmn_xml": "<bpmn/>"}, error_code=ErrorCode.FAILED_MODEL_CALL),
			goal_key="bpmn_xml",
		)
		self.assertEqual(state, gc.NOT_ACHIEVED)
		self.assertIn("error", basis.lower())


class RunFixture(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.instance = None

	def _run(self, status="Running", instance=None):
		doc = frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"bpmn_id": "goal_probe",
				"status": status,
				"started_at": frappe.utils.now_datetime(),
				"instance": instance,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda n=doc.name: frappe.db.exists("AI Agent Run", n)
			and frappe.delete_doc("AI Agent Run", n, force=True, ignore_permissions=True)
		)
		return doc


class TestItIsRecordedOnTheRun(RunFixture):
	def test_finalizing_a_successful_run_records_achievement(self):
		run = self._run()
		finalize_ai_run(run, ExecutorResult(output="the answer"))
		row = frappe.get_doc("AI Agent Run", run.name)
		self.assertEqual(row.goal_completion, gc.ACHIEVED)
		self.assertTrue(row.completion_basis)

	def test_finalizing_a_failed_run_records_non_achievement(self):
		run = self._run()
		finalize_ai_run(run, ExecutorResult(error_code=ErrorCode.FAILED_MODEL_CALL, error_message="x"))
		self.assertEqual(
			frappe.db.get_value("AI Agent Run", run.name, "goal_completion"), gc.NOT_ACHIEVED
		)

	def test_the_declared_key_reaches_the_record(self):
		run = self._run()
		finalize_ai_run(run, ExecutorResult(output={"script": "print(1)"}), goal_key="script")
		self.assertEqual(
			frappe.db.get_value("AI Agent Run", run.name, "goal_completion"), gc.ACHIEVED
		)

	def test_a_background_task_with_no_process_still_gets_an_outcome(self):
		"""Not every run belongs to a chat, and a background AI Agent Task never
		waits for an instance to complete — so the executor's own signals have to
		be enough on their own."""
		run = self._run(instance=None)
		finalize_ai_run(run, ExecutorResult(output="done"))
		row = frappe.get_doc("AI Agent Run", run.name)
		self.assertIsNone(row.instance)
		self.assertEqual(row.goal_completion, gc.ACHIEVED)

	def test_a_new_run_starts_unknown(self):
		"""Never blank, never a guess — a run in flight has simply not decided."""
		self.assertEqual(self._run().goal_completion, gc.UNKNOWN)


class TestTheProcessHasTheFinalWord(RunFixture):
	"""Whether the map reached its end event is the strongest signal, and the one
	that can only be read after the runs have already finished."""

	def _instance(self):
		model = frappe.db.get_value("BPMN Process Model", {}, "name")
		if not model:
			self.skipTest("no process model on this site")
		doc = frappe.get_doc(
			{"doctype": "BPMN Process Instance", "process_model": model, "status": "Active"}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.db.exists("BPMN Process Instance", doc.name)
			and frappe.delete_doc("BPMN Process Instance", doc.name, force=True, ignore_permissions=True)
		)
		return doc

    # ── the two settling directions ──────────────────────────────────────────

	def test_reaching_the_end_event_settles_an_undecided_run(self):
		inst = self._instance()
		run = self._run(status="Success", instance=inst.name)
		self.assertEqual(run.goal_completion, gc.UNKNOWN)

		settled = gc.settle_for_instance(inst.name, "Completed")
		self.assertEqual(settled, 1)
		row = frappe.get_doc("AI Agent Run", run.name)
		self.assertEqual(row.goal_completion, gc.ACHIEVED)
		self.assertIn("end event", row.completion_basis)

	def test_an_errored_process_settles_it_the_other_way(self):
		inst = self._instance()
		run = self._run(status="Success", instance=inst.name)
		gc.settle_for_instance(inst.name, "Errored")
		self.assertEqual(
			frappe.db.get_value("AI Agent Run", run.name, "goal_completion"), gc.NOT_ACHIEVED
		)

	# ── what it must NOT do ──────────────────────────────────────────────────

	def test_a_completed_map_does_not_promote_a_run_that_errored(self):
		"""A map recovering through its error branch is not the agent having
		achieved its goal. This is the one that would quietly inflate every
		success rate if it were wrong."""
		inst = self._instance()
		run = self._run(status="Error", instance=inst.name)
		gc.settle_for_instance(inst.name, "Completed")
		self.assertEqual(
			frappe.db.get_value("AI Agent Run", run.name, "goal_completion"), gc.UNKNOWN
		)

	def test_an_outcome_the_executor_already_decided_is_never_overwritten(self):
		inst = self._instance()
		run = self._run(status="Success", instance=inst.name)
		finalize_ai_run(run, ExecutorResult(output={"x": 1}), goal_key="script")  # Not Achieved
		self.assertEqual(
			frappe.db.get_value("AI Agent Run", run.name, "goal_completion"), gc.NOT_ACHIEVED
		)

		gc.settle_for_instance(inst.name, "Completed")
		self.assertEqual(
			frappe.db.get_value("AI Agent Run", run.name, "goal_completion"),
			gc.NOT_ACHIEVED,
			"the map completing overwrote what the run itself established",
		)

	def test_a_run_still_in_flight_is_left_alone(self):
		inst = self._instance()
		run = self._run(status="Running", instance=inst.name)
		gc.settle_for_instance(inst.name, "Completed")
		self.assertEqual(
			frappe.db.get_value("AI Agent Run", run.name, "goal_completion"), gc.UNKNOWN
		)

	def test_a_status_that_is_not_an_ending_settles_nothing(self):
		inst = self._instance()
		self._run(status="Success", instance=inst.name)
		self.assertEqual(gc.settle_for_instance(inst.name, "Active"), 0)

	def test_no_instance_settles_nothing(self):
		self.assertEqual(gc.settle_for_instance("", "Completed"), 0)
