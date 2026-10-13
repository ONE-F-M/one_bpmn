# Copyright (c) 2026, one-fm and contributors
"""A parked AI step whose job was lost is started again, a limited number of times, and never while a job could still be running it."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import frappe

from one_bpmn import tasks
from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import BPMNProcessInstance
from one_bpmn.tests.test_ai_job_executor import JobHarness

IS_ENQUEUED = "frappe.utils.background_jobs.is_job_enqueued"


class WatchdogCase(JobHarness):
	def setUp(self):
		super().setUp()
		frappe.flags.bpmn_force_ai_parking = True
		self.task_id = self._park_linear_with_tools()
		self.set_instance(status="Active", waiting_for_ai=1)
		self.age(30)

	def set_instance(self, **values):
		frappe.db.set_value("BPMN Process Instance", self.instance.name, values, update_modified=False)

	def age(self, minutes: int):
		state = json.loads(frappe.db.get_value("BPMN Process Instance", self.instance.name, "workflow_state"))
		state["tasks"][self.task_id]["last_state_change"] = time.time() - minutes * 60
		self.set_instance(workflow_state=json.dumps(state))

	def run_watchdog(self, alive=lambda job_id: False) -> list[dict]:
		"""One pass over every active instance, returning the jobs it enqueued for this test's instance."""
		with (
			patch.object(frappe, "enqueue") as enqueue,
			patch.object(frappe.db, "commit"),
			patch.object(frappe.db, "rollback"),
			patch(IS_ENQUEUED, side_effect=alive),
		):
			tasks.requeue_stranded_ai_steps()
		return [
			call.kwargs
			for call in enqueue.call_args_list
			if call.kwargs["instance_name"] == self.instance.name
		]

	def logged(self, action: str) -> int:
		return frappe.db.count("BPMN Activity Log", {"instance": self.instance.name, "action": action})


class TestAStrandedStep(WatchdogCase):
	def test_it_is_enqueued_once_and_the_requeue_is_logged(self):
		jobs = self.run_watchdog()
		self.assertEqual(len(jobs), 1)
		self.assertEqual(jobs[0]["job_id"], f"bpmn-ai-{self.instance.name}-{self.task_id}-watchdog-1")
		self.assertEqual((jobs[0]["kind"], jobs[0]["task_id"]), ("service_task", self.task_id))
		self.assertEqual(self.logged("Retried"), 1)

	def test_two_passes_over_the_same_step_enqueue_one_job(self):
		queued = [job["job_id"] for job in self.run_watchdog()]
		self.assertEqual(self.run_watchdog(alive=lambda job_id: job_id in queued), [])
		self.assertEqual(len(queued), 1)

	def test_after_two_requeues_the_instance_is_errored_and_nothing_is_enqueued(self):
		self.run_watchdog()
		self.run_watchdog()
		with patch.object(frappe, "log_error") as log_error:
			jobs = self.run_watchdog()
		self.assertEqual(jobs, [])
		self.assertIn(
			f"BPMN stranded AI step: {self.instance.name}",
			[c.kwargs["title"] for c in log_error.call_args_list],
		)
		status, waiting = frappe.db.get_value(
			"BPMN Process Instance", self.instance.name, ["status", "waiting_for_ai"]
		)
		self.assertEqual((status, waiting), ("Errored", 0))
		self.assertEqual(self.logged("Errored"), 1)


class TestAStepThatIsLeftAlone(WatchdogCase):
	def test_one_parked_for_less_than_the_threshold(self):
		self.age(tasks.STRANDED_AI_STEP_MINUTES - 5)
		self.assertEqual(self.run_watchdog(), [])

	def test_one_whose_job_is_queued_or_started(self):
		base = f"bpmn-ai-{self.instance.name}-{self.task_id}"
		self.assertEqual(self.run_watchdog(alive=lambda job_id: job_id == base), [])

	def test_one_whose_retry_job_is_queued(self):
		base = f"bpmn-ai-{self.instance.name}-{self.task_id}"
		self.assertEqual(self.run_watchdog(alive=lambda job_id: job_id == f"{base}-r1"), [])

	def test_one_whose_job_is_running_and_holds_the_instance_row(self):
		with patch.object(tasks, "_instance_job_is_running", return_value=True):
			self.assertEqual(self.run_watchdog(), [])

	def test_one_waiting_for_a_delegated_agent(self):
		with patch.object(BPMNProcessInstance, "_task_waiting_a2a", return_value={"a2a_task": "A2A-1"}):
			self.assertEqual(self.run_watchdog(), [])

	def test_an_instance_that_is_not_active(self):
		self.set_instance(status="Completed")
		self.assertEqual(self.run_watchdog(), [])

	def test_an_instance_that_is_not_waiting_for_ai(self):
		self.set_instance(waiting_for_ai=0)
		self.assertEqual(self.run_watchdog(), [])
