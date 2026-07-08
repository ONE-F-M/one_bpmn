# Copyright (c) 2026, one-fm and contributors
# WI-001496: AI background job executor and engine resume.
#
# The queued AI job (run_parked_ai_task) executes the parked AI unit and
# updates the engine with the results:
#   - output variables written EXACTLY as inline dispatch writes them
#   - AI Agent Run observability records identically
#   - the continuation pass runs in the worker to the next wait state/End
#   - selector: one decision per job; activated shapes run in the worker
#     continuation; an activated User task parks the pass and ends the job
#   - redelivery and failures are safe

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from SpiffWorkflow.util.task import TaskState

from one_bpmn.one_bpmn import engine as bpmn_engine
from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import (
	run_parked_ai_task,
)
from one_bpmn.tests.test_ai_park_enqueue import (
	ParkHarness,
	_LINEAR_AGENT_XML,
	_executor_ok,
)

test_ignore = ["BPMN Process Model"]

_SELECTOR_ADHOC_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" id="Defs_SelPark" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="proc_sel_park" isExecutable="true">
    <bpmn:startEvent id="start_1"><bpmn:outgoing>f_in</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f_in" sourceRef="start_1" targetRef="AdhocSub_1" />
    <bpmn:adHocSubProcess id="AdhocSub_1" name="Selector Work">
      <bpmn:incoming>f_in</bpmn:incoming>
      <bpmn:outgoing>f_out</bpmn:outgoing>
      <bpmn:scriptTask id="task_a" name="Task A">
        <bpmn:script>step_a = 1</bpmn:script>
      </bpmn:scriptTask>
      <bpmn:scriptTask id="task_b" name="Task B">
        <bpmn:script>step_b = 1</bpmn:script>
      </bpmn:scriptTask>
      <bpmn:completionCondition xsi:type="bpmn:tFormalExpression">done</bpmn:completionCondition>
    </bpmn:adHocSubProcess>
    <bpmn:sequenceFlow id="f_out" sourceRef="AdhocSub_1" targetRef="end_1" />
    <bpmn:endEvent id="end_1"><bpmn:incoming>f_out</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""

_SELECTOR_USER_XML = _SELECTOR_ADHOC_XML.replace("proc_sel_park", "proc_sel_user").replace(
	'<bpmn:scriptTask id="task_a" name="Task A">\n        <bpmn:script>step_a = 1</bpmn:script>\n      </bpmn:scriptTask>',
	'<bpmn:userTask id="user_a" name="Approve" />',
)

_AGENT_CFG = {
	"Agent_1": {
		"serviceType": "ai_agent",
		"aiProvider": "",
		"aiUserPrompt": "go",
		"aiOutputVariable": "agent_out",
		"aiToolShapes": json.dumps(
			[{"bpmn_id": "lookup", "description": "Look up.", "serverScript": "S1"}]
		),
	}
}


def _executor_with_tools():
	from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage

	return ExecutorResult(
		output="all done",
		error_code=ErrorCode.SUCCESS,
		token_usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
		trace=[
			{
				"role": "tool",
				"tool_calls": [
					{"name": "lookup", "arguments": {}, "result": '{"found": true}'}
				],
			},
			{"role": "assistant", "content": "all done", "tool_calls": []},
		],
	)


class JobHarness(ParkHarness):
	AI_KEYS = ("agent_out", "lookup_toolCallResult", "Agent_1_toolCallResults")

	def _persist(self, wf, extensions):
		bpmn_engine.clean_doc_from_wf_data(wf)
		self.instance.workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))
		self.instance.serialized_spec = json.dumps(
			{
				"service_task_extensions": extensions,
				"user_task_extensions": {},
				"script_task_extensions": {},
			}
		)
		self.instance.db_update()

	def _final_ai_data(self, instance_name):
		"""AI output keys from the persisted end-of-flow task data."""
		state = frappe.db.get_value("BPMN Process Instance", instance_name, "workflow_state")
		wf = bpmn_engine.restore_workflow(workflow_state=json.loads(state))
		for t in wf.get_tasks():
			if t.task_spec.name == "end_1":
				return {k: t.data.get(k) for k in self.AI_KEYS}
		return {}

	def _park_linear_with_tools(self):
		wf = self._wf(_LINEAR_AGENT_XML, "proc_park_linear", dict(_AGENT_CFG))
		enqueue = self._run(wf)
		enqueue.assert_called_once()
		task_id = enqueue.call_args.kwargs["task_id"]
		self._persist(wf, self.instance._service_task_extensions)
		return task_id


class TestJobOutputParity(JobHarness):
	def test_job_writes_outputs_exactly_like_inline_dispatch(self):
		# ── Reference: inline dispatch (parking off — today's test path) ──
		frappe.flags.bpmn_force_ai_parking = False
		wf_inline = self._wf(_LINEAR_AGENT_XML, "proc_park_linear", dict(_AGENT_CFG))
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=_executor_with_tools(),
		):
			self._run(wf_inline)
		end_inline = next(
			t for t in wf_inline.get_tasks() if t.task_spec.name == "end_1"
		)
		inline_data = {k: end_inline.data.get(k) for k in self.AI_KEYS}
		self.assertEqual(inline_data["agent_out"], "all done")

		# ── Same flow through park + background job ──
		frappe.flags.bpmn_force_ai_parking = True
		task_id = self._park_linear_with_tools()
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=_executor_with_tools(),
		):
			with patch.object(frappe, "enqueue"):
				run_parked_ai_task(self.instance.name, "service_task", task_id)

		job_data = self._final_ai_data(self.instance.name)
		# AC: output variables written EXACTLY as inline dispatch writes them.
		self.assertEqual(job_data, inline_data)
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self.instance.name, "status"),
			"Completed",
		)

	def test_job_records_observability_like_inline(self):
		frappe.flags.bpmn_force_ai_parking = True
		task_id = self._park_linear_with_tools()
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=_executor_with_tools(),
		):
			with patch.object(frappe, "enqueue"):
				run_parked_ai_task(self.instance.name, "service_task", task_id)

		runs = frappe.get_all(
			"AI Agent Run",
			filters={"instance": self.instance.name},
			fields=["status", "bpmn_id"],
		)
		self.assertEqual(len(runs), 1)
		self.assertEqual(runs[0].status, "Success")
		self.assertEqual(runs[0].bpmn_id, "Agent_1")

	def test_job_redelivery_after_completion_is_noop(self):
		frappe.flags.bpmn_force_ai_parking = True
		task_id = self._park_linear_with_tools()
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=_executor_with_tools(),
		) as run:
			with patch.object(frappe, "enqueue"):
				run_parked_ai_task(self.instance.name, "service_task", task_id)
				calls = run.call_count
				run_parked_ai_task(self.instance.name, "service_task", task_id)
		self.assertEqual(run.call_count, calls)  # second delivery: no side effects
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self.instance.name, "status"),
			"Completed",
		)

	def test_job_failure_marks_instance_errored(self):
		frappe.flags.bpmn_force_ai_parking = True
		task_id = self._park_linear_with_tools()
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import (
			BPMNProcessInstance,
		)

		with patch.object(
			BPMNProcessInstance, "resume_parked_ai", side_effect=RuntimeError("boom")
		):
			run_parked_ai_task(self.instance.name, "service_task", task_id)

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


class TestSelectorJobTurns(JobHarness):
	SEL_CFG = {"AdhocSub_1": {"serviceType": "ai_task_selector"}}

	def _park_selector(self, xml=_SELECTOR_ADHOC_XML, process_id="proc_sel_park"):
		spec_dict, sp_specs = bpmn_engine.parse_bpmn(xml, process_id)
		self.instance._service_task_extensions = dict(self.SEL_CFG)
		self.instance._user_task_extensions = {}
		self.instance._script_task_extensions = {}
		wf = bpmn_engine.create_workflow(
			spec_dict, sp_specs, initial_data={"done": False}
		)
		enqueue = self._run(wf)
		self._persist(wf, self.instance._service_task_extensions)
		return wf, enqueue

	def _states(self, instance_name):
		state = frappe.db.get_value("BPMN Process Instance", instance_name, "workflow_state")
		wf = bpmn_engine.restore_workflow(workflow_state=json.loads(state))
		return {t.task_spec.name: t.state for t in wf.get_tasks()}

	def test_selector_decision_parks_at_engine_level(self):
		_, enqueue = self._park_selector()
		enqueue.assert_called_once()
		kwargs = enqueue.call_args.kwargs
		self.assertEqual(kwargs["kind"], "adhoc_decision")
		self.assertEqual(kwargs["task_id"], "AdhocSub_1")
		self.assertEqual(self.instance.waiting_for_ai, 1)

	def test_one_decision_per_job_and_shapes_run_in_continuation(self):
		self._park_selector()

		def choose_task_a(instance, sp, task_cfg, bpmn_id):
			return ("activate", "task_a", {})

		with patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.ai_task_selector"
			".dispatch_ai_task_selector",
			side_effect=choose_task_a,
		) as dispatch:
			with patch.object(frappe, "enqueue") as enqueue:
				run_parked_ai_task(self.instance.name, "adhoc_decision", "AdhocSub_1")

		# Exactly ONE decision ran in this job.
		self.assertEqual(dispatch.call_count, 1)
		# The activated shape executed in the worker continuation pass.
		states = self._states(self.instance.name)
		self.assertEqual(states.get("task_a"), TaskState.COMPLETED)
		# The NEXT decision parked again — one job per selector turn.
		self.assertTrue(
			any(
				c.kwargs.get("kind") == "adhoc_decision"
				and c.kwargs.get("task_id") == "AdhocSub_1"
				for c in enqueue.call_args_list
			)
		)
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self.instance.name, "status"),
			"Active",
		)

	def test_activated_user_task_parks_pass_and_ends_job(self):
		self._park_selector(xml=_SELECTOR_USER_XML, process_id="proc_sel_user")

		def choose_user_a(instance, sp, task_cfg, bpmn_id):
			return ("activate", "user_a", {})

		with patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.ai_task_selector"
			".dispatch_ai_task_selector",
			side_effect=choose_user_a,
		) as dispatch:
			with patch.object(frappe, "enqueue") as enqueue:
				run_parked_ai_task(self.instance.name, "adhoc_decision", "AdhocSub_1")

		self.assertEqual(dispatch.call_count, 1)
		# The human task is now the wait state — READY, not auto-run.
		states = self._states(self.instance.name)
		self.assertEqual(states.get("user_a"), TaskState.READY)
		# No further selector decision was queued while a human head is
		# active (the gate promotes one head at a time), and the instance
		# is waiting on the human — not on AI.
		self.assertFalse(
			any(
				c.kwargs.get("kind") == "adhoc_decision"
				for c in enqueue.call_args_list
			)
		)
		self.assertEqual(
			frappe.db.get_value(
				"BPMN Process Instance", self.instance.name, "waiting_for_ai"
			),
			0,
		)
