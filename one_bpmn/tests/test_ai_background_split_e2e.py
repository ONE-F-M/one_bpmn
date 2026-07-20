# Copyright (c) 2026, one-fm and contributors
# WI-001500: AI background split — end-to-end verification.
#
# One UAT-shaped model (mirroring the "AI Agent Task UAT" diagram): an
# exclusive gateway routes to a plain branch OR an AI Agent branch.
#   - plain branch: the whole flow runs inline, zero background jobs
#   - AI branch: everything up to the agent runs inline, the agent parks,
#     ONLY its LLM work runs as the bpmn_ai_agent job, the job resumes the
#     flow to completion with full observability
#   - gate: actions rejected while the AI job executes, accepted at waits
#   - failure: forced job failures retry boundedly, then error, then a
#     manual retry recovers

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from SpiffWorkflow.util.task import TaskState

from one_bpmn.one_bpmn import engine as bpmn_engine
from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import (
	BPMNProcessInstance,
	run_parked_ai_task,
)
from one_bpmn.tests.test_ai_job_executor import JobHarness, _executor_with_tools

test_ignore = ["BPMN Process Model"]

# UAT-shaped: start → route gateway → [plain script | AI agent] → end
_UAT_SHAPE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_SplitUat" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="proc_split_uat" isExecutable="true">
    <bpmn:startEvent id="start_1"><bpmn:outgoing>f0</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f0" sourceRef="start_1" targetRef="gw_route" />
    <bpmn:exclusiveGateway id="gw_route" default="flow_plain">
      <bpmn:incoming>f0</bpmn:incoming>
      <bpmn:outgoing>flow_plain</bpmn:outgoing>
      <bpmn:outgoing>flow_ai</bpmn:outgoing>
    </bpmn:exclusiveGateway>
    <bpmn:sequenceFlow id="flow_plain" sourceRef="gw_route" targetRef="plain_step" />
    <bpmn:sequenceFlow id="flow_ai" sourceRef="gw_route" targetRef="Agent_1">
      <bpmn:conditionExpression>route == "ai"</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:scriptTask id="plain_step" name="Plain Step">
      <bpmn:incoming>flow_plain</bpmn:incoming>
      <bpmn:outgoing>f_p</bpmn:outgoing>
      <bpmn:script>plain_ran = 1</bpmn:script>
    </bpmn:scriptTask>
    <bpmn:serviceTask id="Agent_1" name="Fulfilment Advisor">
      <bpmn:incoming>flow_ai</bpmn:incoming>
      <bpmn:outgoing>f_a</bpmn:outgoing>
    </bpmn:serviceTask>
    <bpmn:sequenceFlow id="f_p" sourceRef="plain_step" targetRef="gw_join" />
    <bpmn:sequenceFlow id="f_a" sourceRef="Agent_1" targetRef="gw_join" />
    <bpmn:exclusiveGateway id="gw_join">
      <bpmn:incoming>f_p</bpmn:incoming>
      <bpmn:incoming>f_a</bpmn:incoming>
      <bpmn:outgoing>f9</bpmn:outgoing>
    </bpmn:exclusiveGateway>
    <bpmn:sequenceFlow id="f9" sourceRef="gw_join" targetRef="end_1" />
    <bpmn:endEvent id="end_1"><bpmn:incoming>f9</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""

_UAT_CFG = {
	"Agent_1": {
		"serviceType": "ai_agent",
		"aiProvider": "",
		"aiUserPrompt": "advise",
		"aiOutputVariable": "advice",
		"aiToolShapes": json.dumps(
			[{"bpmn_id": "lookup", "description": "Look up.", "serverScript": "S1"}]
		),
	}
}


class SplitE2eHarness(JobHarness):
	def _start_uat(self, route):
		spec_dict, sp_specs = bpmn_engine.parse_bpmn(_UAT_SHAPE_XML, "proc_split_uat")
		self.instance._service_task_extensions = dict(_UAT_CFG)
		self.instance._user_task_extensions = {}
		self.instance._script_task_extensions = {}
		wf = bpmn_engine.create_workflow(
			spec_dict, sp_specs, initial_data={"route": route}
		)
		enqueue = self._run(wf)
		return wf, enqueue


class TestSplitEndToEnd(SplitE2eHarness):
	def test_non_ai_branch_completes_inline_with_zero_jobs(self):
		wf, enqueue = self._start_uat(route="plain")
		enqueue.assert_not_called()
		self.assertTrue(wf.is_completed())
		self.assertEqual(self._state_of(wf, "plain_step"), TaskState.COMPLETED)
		# The AI branch was never taken, nothing waits on AI.
		self.assertEqual(self.instance.waiting_for_ai, 0)

	def test_ai_branch_parks_then_job_resumes_to_completion(self):
		wf, enqueue = self._start_uat(route="ai")

		# Inline portion stopped AT the agent: parked, one job, waiting flag.
		self.assertEqual(self._state_of(wf, "Agent_1"), TaskState.STARTED)
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.kwargs["queue"], "bpmn_ai_agent")
		self.assertEqual(self.instance.waiting_for_ai, 1)
		task_id = enqueue.call_args.kwargs["task_id"]

		# Persist the parked state, then the AI-only job runs.
		self._persist(wf, self.instance._service_task_extensions)
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=_executor_with_tools(),
		):
			with patch.object(frappe, "enqueue"):
				run_parked_ai_task(self.instance.name, "service_task", task_id)

		# The job completed the agent AND the continuation (join → end).
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self.instance.name, "status"),
			"Completed",
		)
		self.assertEqual(
			frappe.db.get_value(
				"BPMN Process Instance", self.instance.name, "waiting_for_ai"
			),
			0,
		)
		# Output variables + observability arrived through the job path.
		final = self._final_ai_data(self.instance.name)
		self.assertEqual(final["agent_out"], None)  # UAT cfg writes "advice"
		state = frappe.db.get_value(
			"BPMN Process Instance", self.instance.name, "workflow_state"
		)
		self.assertIn('"advice": "all done"', state)
		runs = frappe.get_all(
			"AI Agent Run", filters={"instance": self.instance.name}, pluck="status"
		)
		self.assertEqual(runs, ["Success"])

	def test_action_rejected_while_ai_executes_accepted_while_waiting(self):
		from one_bpmn.api.instance_api import complete_task

		wf, enqueue = self._start_uat(route="ai")
		self._persist(wf, self.instance._service_task_extensions)

		# Waiting (job queued, not running): the gate is CLEAR — the request
		# passes the gate and fails only on task lookup.
		with self.assertRaises(frappe.ValidationError) as ctx:
			complete_task(self.instance.name, "no-such-task")
		self.assertNotIn("processing", str(ctx.exception).lower())

		# While the job actively executes: rejected with "processing".
		task_id = enqueue.call_args.kwargs["task_id"]
		observed = {}

		def probe(instance, kind, task_id):
			try:
				complete_task(instance.name, "no-such-task")
			except frappe.ValidationError as e:
				observed["error"] = str(e)

		with patch.object(BPMNProcessInstance, "resume_parked_ai", new=probe):
			with patch.object(frappe, "enqueue"):
				run_parked_ai_task(self.instance.name, "service_task", task_id)
		self.assertIn("processing", observed["error"].lower())

	def test_forced_failure_retries_then_errors_then_manual_retry_recovers(self):
		from one_bpmn.api.instance_api import retry_ai_task

		wf, enqueue = self._start_uat(route="ai")
		self._persist(wf, self.instance._service_task_extensions)
		task_id = enqueue.call_args.kwargs["task_id"]

		# Attempt 0 fails → bounded retry scheduled (attempt 1), still Active.
		with patch.object(
			BPMNProcessInstance, "resume_parked_ai", side_effect=RuntimeError("provider down")
		):
			with patch.object(frappe, "enqueue") as retry_q:
				run_parked_ai_task(self.instance.name, "service_task", task_id, attempt=0)
		self.assertEqual(retry_q.call_args.kwargs["attempt"], 1)
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self.instance.name, "status"),
			"Active",
		)

		# Final attempt fails → Errored + error on the task's activity log.
		with patch.object(
			BPMNProcessInstance, "resume_parked_ai", side_effect=RuntimeError("provider down")
		):
			with patch.object(frappe, "enqueue") as retry_q:
				run_parked_ai_task(self.instance.name, "service_task", task_id, attempt=2)
		retry_q.assert_not_called()
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self.instance.name, "status"),
			"Errored",
		)
		self.assertTrue(
			frappe.db.exists(
				"BPMN Activity Log",
				{"instance": self.instance.name, "task_id": task_id, "action": "Errored"},
			)
		)

		# Manual retry re-kicks the SAME parked task and the flow recovers.
		with patch.object(frappe, "enqueue"):
			retry_ai_task(self.instance.name, task_id, "service_task")
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
