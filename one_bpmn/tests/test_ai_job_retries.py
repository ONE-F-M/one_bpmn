# Copyright (c) 2026, one-fm and contributors
# WI-001497: bounded retries and failure policy for AI jobs.
#
# Three failure layers, three policies:
# - LLM/provider failures: retried IN-PROCESS by the executor up to the
#   panel's aiMaxRetries (recorded on AI Agent Run.retry_count) — when
#   exhausted, the dispatch writes error variables and the flow continues,
#   IDENTICAL to inline dispatch (WI-001496 parity).
# - Job-level failures (engine restore, DB, crash): re-enqueued with
#   attempt+1 while attempt < aiMaxRetries; instance stays Active.
# - Exhaustion: instance Errored, error logged on the task's activity log,
#   task stays parked so retry_ai_task (manual) resumes where it stopped.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from SpiffWorkflow.util.task import TaskState

from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import (
	BPMNProcessInstance,
	run_parked_ai_task,
)
from one_bpmn.tests.test_ai_job_executor import JobHarness, _executor_with_tools

test_ignore = ["BPMN Process Model"]


class TestJobLevelRetries(JobHarness):
	def _crash(self, task_id, attempt):
		with patch.object(
			BPMNProcessInstance, "resume_parked_ai", side_effect=RuntimeError("boom")
		):
			with patch.object(frappe, "enqueue") as enqueue:
				run_parked_ai_task(
					self.instance.name, "service_task", task_id, attempt=attempt
				)
		return enqueue

	def test_transient_failure_reenqueues_next_attempt(self):
		task_id = self._park_linear_with_tools()
		enqueue = self._crash(task_id, attempt=0)

		enqueue.assert_called_once()
		kwargs = enqueue.call_args.kwargs
		self.assertEqual(kwargs["attempt"], 1)
		self.assertEqual(kwargs["queue"], "bpmn_ai_agent")
		self.assertEqual(
			kwargs["job_id"], f"bpmn-ai-{self.instance.name}-{task_id}-r1"
		)
		# Still recoverable: Active + waiting, NOT Errored.
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self.instance.name, "status"),
			"Active",
		)
		self.assertEqual(
			frappe.db.get_value(
				"BPMN Process Instance", self.instance.name, "waiting_for_ai"
			),
			1,
		)

	def test_exhaustion_marks_errored_and_logs_on_task(self):
		task_id = self._park_linear_with_tools()
		# aiMaxRetries defaults to 2 → attempt=2 is the final allowed attempt.
		enqueue = self._crash(task_id, attempt=2)

		enqueue.assert_not_called()  # no further retry
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self.instance.name, "status"),
			"Errored",
		)
		self.assertEqual(
			frappe.db.get_value(
				"BPMN Process Instance", self.instance.name, "waiting_for_ai"
			),
			0,
		)
		# Error recorded on the task's activity log.
		self.assertTrue(
			frappe.db.exists(
				"BPMN Activity Log",
				{"instance": self.instance.name, "task_id": task_id, "action": "Errored"},
			)
		)

	def test_retry_cap_reads_panel_ai_max_retries(self):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import (
			_job_retry_cap,
		)

		task_id = self._park_linear_with_tools()
		# Single-agent model resolves the ai_agent cfg (default 2)…
		self.assertEqual(_job_retry_cap(self.instance, "service_task", task_id), 2)
		# …and honours a configured aiMaxRetries.
		import json as _json

		spec = _json.loads(self.instance.serialized_spec)
		spec["service_task_extensions"]["Agent_1"]["aiMaxRetries"] = 5
		self.instance.serialized_spec = _json.dumps(spec)
		self.assertEqual(_job_retry_cap(self.instance, "service_task", task_id), 5)
		# adhoc_decision resolves by bpmn id directly.
		spec["service_task_extensions"]["Sel_1"] = {
			"serviceType": "ai_task_selector",
			"aiMaxRetries": 4,
		}
		self.instance.serialized_spec = _json.dumps(spec)
		self.assertEqual(_job_retry_cap(self.instance, "adhoc_decision", "Sel_1"), 4)

	def test_exhausted_task_stays_parked_for_manual_retry(self):
		task_id = self._park_linear_with_tools()
		self._crash(task_id, attempt=2)  # exhaust

		# The parked task is still STARTED in the persisted state…
		import json as _json

		from one_bpmn.one_bpmn import engine as bpmn_engine

		state = frappe.db.get_value(
			"BPMN Process Instance", self.instance.name, "workflow_state"
		)
		wf = bpmn_engine.restore_workflow(workflow_state=_json.loads(state))
		agent = next(t for t in wf.get_tasks() if t.task_spec.name == "Agent_1")
		self.assertEqual(agent.state, TaskState.STARTED)


class TestManualRetry(JobHarness):
	def test_manual_retry_requeues_and_recovers(self):
		from one_bpmn.api.instance_api import retry_ai_task

		task_id = self._park_linear_with_tools()
		# Exhaust the automatic retries → Errored.
		with patch.object(
			BPMNProcessInstance, "resume_parked_ai", side_effect=RuntimeError("boom")
		):
			with patch.object(frappe, "enqueue"):
				run_parked_ai_task(self.instance.name, "service_task", task_id, attempt=2)

		# Manual retry re-kicks a fresh job and reactivates the instance.
		with patch.object(frappe, "enqueue") as enqueue:
			result = retry_ai_task(self.instance.name, task_id, "service_task")
		self.assertEqual(result["status"], "queued")
		enqueue.assert_called_once()
		kwargs = enqueue.call_args.kwargs
		self.assertEqual(kwargs["attempt"], 0)
		self.assertIn("-manual-", kwargs["job_id"])
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self.instance.name, "status"),
			"Active",
		)

		# The fresh job succeeds and the flow completes.
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=_executor_with_tools(),
		):
			with patch.object(frappe, "enqueue"):
				run_parked_ai_task(self.instance.name, "service_task", task_id)
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self.instance.name, "status"),
			"Completed",
		)

	def test_manual_retry_rejects_completed_instance(self):
		from one_bpmn.api.instance_api import retry_ai_task

		task_id = self._park_linear_with_tools()
		frappe.db.set_value(
			"BPMN Process Instance", self.instance.name, "status", "Completed"
		)
		self.instance.reload()
		with self.assertRaises(frappe.ValidationError):
			retry_ai_task(self.instance.name, task_id, "service_task")

	def test_manual_retry_permission_failure(self):
		from one_bpmn.api.instance_api import retry_ai_task

		task_id = self._park_linear_with_tools()
		with self.set_user("Guest"):
			with self.assertRaises(frappe.PermissionError):
				retry_ai_task(self.instance.name, task_id, "service_task")

	def test_manual_retry_validates_kind(self):
		from one_bpmn.api.instance_api import retry_ai_task

		with self.assertRaises(frappe.ValidationError):
			retry_ai_task(self.instance.name, "x", "not_a_kind")


class TestDispatchFailureParity(JobHarness):
	def test_executor_exhaustion_keeps_inline_semantics(self):
		"""When the executor exhausts ITS retries the dispatch writes the
		error variables and the flow continues — identical to inline
		dispatch. The job does NOT error the instance for provider failures
		(the diagram can gateway on the error variables)."""
		from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage

		task_id = self._park_linear_with_tools()
		failed = ExecutorResult(
			output=None,
			error_code=ErrorCode.FAILED_MODEL_CALL,
			error_message="upstream 500",
			token_usage=TokenUsage(prompt_tokens=1, completion_tokens=0, total_tokens=1),
		)
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=failed,
		):
			with patch.object(frappe, "enqueue"):
				run_parked_ai_task(self.instance.name, "service_task", task_id)

		# Flow continued to the End Event — provider failure is a process
		# variable, not an instance failure (inline parity).
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self.instance.name, "status"),
			"Completed",
		)
		runs = frappe.get_all(
			"AI Agent Run",
			filters={"instance": self.instance.name},
			fields=["status", "error_code"],
		)
		self.assertEqual(len(runs), 1)
		self.assertEqual(runs[0].status, "Error")
