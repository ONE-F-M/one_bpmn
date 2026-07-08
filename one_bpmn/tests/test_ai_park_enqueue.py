# Copyright (c) 2026, one-fm and contributors
# WI-001495: park-and-enqueue seam for AI tasks.
#
# When an engine pass reaches an AI task it is NOT dispatched inline: the
# task stays parked in STARTED state, exactly one AI-only job is enqueued on
# bpmn_ai_agent (job_id-deduplicated per instance+task), and the instance
# shows waiting_for_ai=1 ("Waiting for AI execution"). Non-AI siblings in
# the same pass still dispatch inline. run_parked_ai_task executes the AI
# work in the worker and resumes the flow.
#
# Parking is inactive under in_test (no worker, auto-rollback) — these tests
# opt in via frappe.flags.bpmn_force_ai_parking.

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from SpiffWorkflow.util.task import TaskState

from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage
from one_bpmn.one_bpmn import engine as bpmn_engine

test_ignore = ["BPMN Process Model"]

_LINEAR_AGENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_ParkLinear" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="proc_park_linear" isExecutable="true">
    <bpmn:startEvent id="start_1">
      <bpmn:outgoing>f1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="start_1" targetRef="Agent_1" />
    <bpmn:serviceTask id="Agent_1" name="Agent">
      <bpmn:incoming>f1</bpmn:incoming>
      <bpmn:outgoing>f2</bpmn:outgoing>
    </bpmn:serviceTask>
    <bpmn:sequenceFlow id="f2" sourceRef="Agent_1" targetRef="end_1" />
    <bpmn:endEvent id="end_1">
      <bpmn:incoming>f2</bpmn:incoming>
    </bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""

_PARALLEL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_ParkPar" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="proc_park_parallel" isExecutable="true">
    <bpmn:startEvent id="start_1"><bpmn:outgoing>f0</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f0" sourceRef="start_1" targetRef="gw_split" />
    <bpmn:parallelGateway id="gw_split">
      <bpmn:incoming>f0</bpmn:incoming>
      <bpmn:outgoing>fa</bpmn:outgoing>
      <bpmn:outgoing>fb</bpmn:outgoing>
    </bpmn:parallelGateway>
    <bpmn:sequenceFlow id="fa" sourceRef="gw_split" targetRef="Agent_1" />
    <bpmn:sequenceFlow id="fb" sourceRef="gw_split" targetRef="Svc_1" />
    <bpmn:serviceTask id="Agent_1" name="Agent">
      <bpmn:incoming>fa</bpmn:incoming>
      <bpmn:outgoing>fa2</bpmn:outgoing>
    </bpmn:serviceTask>
    <bpmn:serviceTask id="Svc_1" name="Plain Service">
      <bpmn:incoming>fb</bpmn:incoming>
      <bpmn:outgoing>fb2</bpmn:outgoing>
    </bpmn:serviceTask>
    <bpmn:sequenceFlow id="fa2" sourceRef="Agent_1" targetRef="gw_join" />
    <bpmn:sequenceFlow id="fb2" sourceRef="Svc_1" targetRef="gw_join" />
    <bpmn:parallelGateway id="gw_join">
      <bpmn:incoming>fa2</bpmn:incoming>
      <bpmn:incoming>fb2</bpmn:incoming>
      <bpmn:outgoing>f9</bpmn:outgoing>
    </bpmn:parallelGateway>
    <bpmn:sequenceFlow id="f9" sourceRef="gw_join" targetRef="end_1" />
    <bpmn:endEvent id="end_1"><bpmn:incoming>f9</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""

_TWO_AGENTS_XML = _PARALLEL_XML.replace("proc_park_parallel", "proc_park_two").replace(
	'<bpmn:serviceTask id="Svc_1" name="Plain Service">',
	'<bpmn:serviceTask id="Agent_2" name="Agent Two">',
).replace('sourceRef="gw_split" targetRef="Svc_1"', 'sourceRef="gw_split" targetRef="Agent_2"').replace(
	'sourceRef="Svc_1" targetRef="gw_join"', 'sourceRef="Agent_2" targetRef="gw_join"'
)


def _executor_ok(output="agent done"):
	return ExecutorResult(
		output=output,
		error_code=ErrorCode.SUCCESS,
		token_usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
	)


class ParkHarness(FrappeTestCase):
	"""Shared harness: real instance doc + real engine workflow."""

	def setUp(self):
		self.instance = frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_id": f"test-{frappe.generate_hash(length=6)}",
				"status": "Active",
			}
		)
		self.instance.flags.ignore_mandatory = True
		self.instance.insert(ignore_permissions=True, ignore_mandatory=True)
		frappe.flags.bpmn_force_ai_parking = True
		self.addCleanup(setattr, frappe.flags, "bpmn_force_ai_parking", False)
		self.addCleanup(setattr, frappe.flags, "bpmn_ai_resume_target", None)

	def _wf(self, xml, process_id, extensions):
		spec_dict, sp_specs = bpmn_engine.parse_bpmn(xml, process_id)
		self._spec_dict = spec_dict
		self.instance._service_task_extensions = extensions
		self.instance._user_task_extensions = {}
		self.instance._script_task_extensions = {}
		return bpmn_engine.create_workflow(spec_dict, sp_specs, initial_data={})

	def _run(self, wf):
		with patch.object(frappe, "enqueue") as enqueue:
			self.instance._run_engine(wf)
		return enqueue

	@staticmethod
	def _state_of(wf, spec_name):
		for t in wf.get_tasks():
			if t.task_spec.name == spec_name:
				return t.state
		return None

	@staticmethod
	def _task_by_spec(wf, spec_name):
		for t in wf.get_tasks():
			if t.task_spec.name == spec_name:
				return t
		return None


class TestAiTaskParking(ParkHarness):
	def test_ai_task_parks_and_enqueues_one_job(self):
		wf = self._wf(
			_LINEAR_AGENT_XML,
			"proc_park_linear",
			{"Agent_1": {"serviceType": "ai_agent", "aiUserPrompt": "go"}},
		)
		enqueue = self._run(wf)

		# Parked: STARTED, not dispatched, not completed.
		self.assertEqual(self._state_of(wf, "Agent_1"), TaskState.STARTED)
		# Exactly one AI-only job on the dedicated queue.
		enqueue.assert_called_once()
		kwargs = enqueue.call_args.kwargs
		self.assertEqual(kwargs["queue"], "bpmn_ai_agent")
		self.assertEqual(kwargs["kind"], "service_task")
		self.assertTrue(kwargs["deduplicate"])
		task = self._task_by_spec(wf, "Agent_1")
		self.assertEqual(kwargs["job_id"], f"bpmn-ai-{self.instance.name}-{task.id}")
		# Instance shows "Waiting for AI execution".
		self.assertEqual(self.instance.waiting_for_ai, 1)

	def test_non_ai_sibling_dispatches_inline(self):
		wf = self._wf(
			_PARALLEL_XML,
			"proc_park_parallel",
			{
				"Agent_1": {"serviceType": "ai_agent"},
				# unknown serviceType → _dispatch_service_task no-ops but the
				# task completes inline, exactly like any non-AI service task
				"Svc_1": {"serviceType": ""},
			},
		)
		enqueue = self._run(wf)

		self.assertEqual(self._state_of(wf, "Agent_1"), TaskState.STARTED)
		self.assertEqual(self._state_of(wf, "Svc_1"), TaskState.COMPLETED)
		enqueue.assert_called_once()  # only the AI task went to the worker

	def test_two_parallel_ai_tasks_one_deduplicated_job_each(self):
		wf = self._wf(
			_TWO_AGENTS_XML,
			"proc_park_two",
			{
				"Agent_1": {"serviceType": "ai_agent"},
				"Agent_2": {"serviceType": "ai_agent"},
			},
		)
		enqueue = self._run(wf)

		self.assertEqual(enqueue.call_count, 2)
		job_ids = {c.kwargs["job_id"] for c in enqueue.call_args_list}
		self.assertEqual(len(job_ids), 2)  # distinct per task
		for c in enqueue.call_args_list:
			self.assertTrue(c.kwargs["deduplicate"])

		# A second pass over the same state re-parks but the in-pass dedup
		# still emits one enqueue call per task (queue-level job_id dedup
		# makes redelivery a no-op).
		enqueue2 = self._run(wf)
		self.assertEqual(enqueue2.call_count, 2)
		self.assertEqual({c.kwargs["job_id"] for c in enqueue2.call_args_list}, job_ids)

	def test_parking_inactive_in_tests_by_default(self):
		frappe.flags.bpmn_force_ai_parking = False
		wf = self._wf(
			_LINEAR_AGENT_XML,
			"proc_park_linear",
			{"Agent_1": {"serviceType": "ai_agent", "aiProvider": "", "aiUserPrompt": "hi"}},
		)
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=_executor_ok(),
		):
			enqueue = self._run(wf)
		# Dispatched inline (existing test-suite behaviour), no job.
		enqueue.assert_not_called()
		self.assertEqual(self._state_of(wf, "Agent_1"), TaskState.COMPLETED)


class TestParkedAiResume(ParkHarness):
	def _park_linear(self):
		wf = self._wf(
			_LINEAR_AGENT_XML,
			"proc_park_linear",
			{
				"Agent_1": {
					"serviceType": "ai_agent",
					"aiProvider": "",
					"aiUserPrompt": "go",
					"aiOutputVariable": "agent_out",
				}
			},
		)
		enqueue = self._run(wf)
		task = self._task_by_spec(wf, "Agent_1")
		# Persist parked state the way start()/advance() do.
		bpmn_engine.clean_doc_from_wf_data(wf)
		self.instance.workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))
		self.instance.serialized_spec = json.dumps(
			{
				"service_task_extensions": self.instance._service_task_extensions,
				"user_task_extensions": {},
				"script_task_extensions": {},
			}
		)
		self.instance.db_update()
		return enqueue, str(task.id)

	def test_resume_dispatches_completes_and_continues(self):
		_, task_id = self._park_linear()

		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=_executor_ok("all done"),
		):
			with patch.object(frappe, "enqueue"):
				self.instance.resume_parked_ai(kind="service_task", task_id=task_id)

		# The flow ran to the End Event and the wait state cleared.
		self.assertEqual(self.instance.status, "Completed")
		self.assertEqual(self.instance.waiting_for_ai, 0)

	def test_resume_is_idempotent_on_redelivery(self):
		_, task_id = self._park_linear()
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=_executor_ok(),
		) as run:
			with patch.object(frappe, "enqueue"):
				self.instance.resume_parked_ai(kind="service_task", task_id=task_id)
				first_calls = run.call_count
				# Redelivery of the same job: task no longer STARTED → no-op.
				self.instance.resume_parked_ai(kind="service_task", task_id=task_id)
		self.assertEqual(run.call_count, first_calls)
		self.assertEqual(self.instance.status, "Completed")

	def test_resume_unknown_task_is_noop(self):
		self._park_linear()
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run"
		) as run:
			self.instance.resume_parked_ai(
				kind="service_task", task_id="00000000-0000-0000-0000-000000000000"
			)
		run.assert_not_called()


class TestSelectorDecisionParking(ParkHarness):
	def _decider(self, sp_name="Adhoc_1"):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance.ai_task_selector import (
			make_adhoc_decider,
		)

		self.instance._service_task_extensions = {
			sp_name: {"serviceType": "ai_task_selector"}
		}
		self.instance._pending_ai_jobs = []
		sp = frappe._dict(spec=frappe._dict(name=sp_name), data={})
		return make_adhoc_decider(self.instance, None), sp

	def test_selector_decision_parks_instead_of_calling_llm(self):
		decider, sp = self._decider()
		with patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.ai_task_selector"
			".dispatch_ai_task_selector"
		) as dispatch:
			chosen = decider(sp, [frappe._dict(task_spec=frappe._dict(name="t1"))])
		dispatch.assert_not_called()
		self.assertIs(chosen, bpmn_engine.NO_ACTIVATION)
		self.assertIn(("adhoc_decision", "Adhoc_1"), self.instance._pending_ai_jobs)

	def test_resume_target_allows_exactly_one_decision(self):
		decider, sp = self._decider()
		frappe.flags.bpmn_ai_resume_target = "Adhoc_1"
		with patch(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance.ai_task_selector"
			".dispatch_ai_task_selector",
			return_value=("idle", None, None),
		) as dispatch:
			first = decider(sp, [frappe._dict(task_spec=frappe._dict(name="t1"))])
			# target consumed — the NEXT decision of the same loop parks again
			second = decider(sp, [frappe._dict(task_spec=frappe._dict(name="t1"))])
		self.assertEqual(dispatch.call_count, 1)
		self.assertIsNone(frappe.flags.bpmn_ai_resume_target)
		self.assertIs(first, bpmn_engine.NO_ACTIVATION)  # idle → nothing activated
		self.assertIs(second, bpmn_engine.NO_ACTIVATION)  # parked again
		self.assertIn(("adhoc_decision", "Adhoc_1"), self.instance._pending_ai_jobs)

	def test_non_selector_adhoc_untouched(self):
		decider, sp = self._decider()
		self.instance._service_task_extensions = {}  # plain ad-hoc, no selector
		chosen = decider(sp, [frappe._dict(task_spec=frappe._dict(name="t1"))])
		self.assertIsNone(chosen)  # falls through to diagram order
		self.assertEqual(self.instance._pending_ai_jobs, [])
