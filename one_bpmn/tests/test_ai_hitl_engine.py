# Copyright (c) 2026, one-fm and contributors
# Durable AI Agent HITL, story 3 — engine suspend/resume wiring.
#
# The ai_agent service task parks in STARTED when its dispatch suspends for a
# human tool; the chosen User/Manual shape is spawned as a pending human task
# (active_tasks row + assignment); completing that task enqueues a
# human_resume job that re-enters the checkpointed loop and — on a final
# answer — completes the service task and continues the flow.

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
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_HITL" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="proc_hitl_linear" isExecutable="true">
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

_TOOL_SHAPES = json.dumps([
	{"bpmn_id": "Lookup_1", "description": "look up data", "serverScript": "X"},
	{"bpmn_id": "Approve_1", "description": "ask for approval", "human": True, "label": "Approve Refund"},
])

_AGENT_CFG = {
	"serviceType": "ai_agent",
	"aiProvider": "",
	"aiUserPrompt": "go",
	"aiOutputVariable": "agent_out",
	"aiToolShapes": _TOOL_SHAPES,
}

_HUMAN_SHAPE_CFG = {
	"Approve_1": {
		"assigneeMode": "User",
		"assigneeUser": "Administrator",
		"taskActions": "Approve,Reject",
	}
}


def _suspended_result():
	return ExecutorResult(
		error_code=ErrorCode.SUSPENDED,
		token_usage=TokenUsage(prompt_tokens=40, completion_tokens=4, total_tokens=44),
		trace=[],
		suspension={
			"transcript": [
				{"role": "user", "content": "go"},
				{
					"role": "assistant",
					"content": "need approval",
					"tool_calls": [{"id": "h1", "name": "Approve_1", "arguments": {"request": "ok?"}}],
				},
			],
			"pending_call": {"id": "h1", "name": "Approve_1", "arguments": {"request": "ok?"}},
			"deferred_results": [],
			"trace": [],
			"turns_used": 1,
			"prompt_tokens": 40,
			"completion_tokens": 4,
		},
	)


def _final_result(output="approved and done"):
	return ExecutorResult(
		output=output,
		error_code=ErrorCode.SUCCESS,
		token_usage=TokenUsage(prompt_tokens=10, completion_tokens=1, total_tokens=11),
	)


class HitlHarness(FrappeTestCase):
	def setUp(self):
		self.instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_id": f"test-{frappe.generate_hash(length=6)}",
			"status": "Active",
		})
		self.instance.flags.ignore_mandatory = True
		self.instance.insert(ignore_permissions=True, ignore_mandatory=True)
		frappe.flags.bpmn_force_ai_parking = True
		self.addCleanup(setattr, frappe.flags, "bpmn_force_ai_parking", False)
		self.addCleanup(setattr, frappe.flags, "bpmn_ai_resume_target", None)

	def _park_linear(self):
		"""Start the linear agent process with parking on; persist state the
		way start()/advance() do. Returns the parked wf task id."""
		spec_dict, sp_specs = bpmn_engine.parse_bpmn(_LINEAR_AGENT_XML, "proc_hitl_linear")
		self.instance._service_task_extensions = {"Agent_1": dict(_AGENT_CFG)}
		self.instance._user_task_extensions = dict(_HUMAN_SHAPE_CFG)
		self.instance._script_task_extensions = {}
		wf = bpmn_engine.create_workflow(spec_dict, sp_specs, initial_data={})
		with patch.object(frappe, "enqueue"):
			self.instance._run_engine(wf)
		task = next(t for t in wf.get_tasks() if t.task_spec.name == "Agent_1")
		self._persist(wf)
		return str(task.id)

	def _persist(self, wf):
		bpmn_engine.clean_doc_from_wf_data(wf)
		self.instance.workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))
		self.instance.serialized_spec = json.dumps({
			"service_task_extensions": {"Agent_1": dict(_AGENT_CFG)},
			"user_task_extensions": dict(_HUMAN_SHAPE_CFG),
			"script_task_extensions": {},
		})
		self.instance.db_update()
		self.instance.update_children()

	def _suspend(self, task_id):
		"""Worker pass that suspends the agent for the human tool."""
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=_suspended_result(),
		):
			with patch.object(frappe, "enqueue"):
				self.instance.resume_parked_ai(kind="service_task", task_id=task_id)

	def _human_row(self):
		return next(
			(
				r
				for r in self.instance.active_tasks
				if str(r.task_id).startswith(self.instance.AI_HUMAN_PREFIX)
			),
			None,
		)


class TestSuspension(HitlHarness):
	def test_suspend_parks_task_and_spawns_human_row(self):
		task_id = self._park_linear()
		self._suspend(task_id)

		# Service task remains STARTED (waiting), the instance is not done.
		wf = bpmn_engine.restore_workflow(
			workflow_state=json.loads(self.instance.workflow_state)
		)
		agent = next(t for t in wf.get_tasks() if t.task_spec.name == "Agent_1")
		self.assertEqual(agent.state, TaskState.STARTED)
		self.assertEqual(self.instance.status, "Active")

		# Human task row: synthetic id, correct type/label/actions/assignee.
		row = self._human_row()
		self.assertIsNotNone(row)
		self.assertEqual(row.task_type, "AI Human Task")
		self.assertEqual(row.task_name, "Approve Refund")
		self.assertEqual(row.status, "Waiting")
		self.assertEqual(row.assigned_user, "Administrator")
		self.assertEqual(row.task_actions, "Approve,Reject")

		# Waiting states: human yes, AI no.
		self.assertEqual(self.instance.waiting_for_human, "Approve Refund")
		self.assertEqual(self.instance.waiting_for_ai, 0)

		# Checkpoint bound to the row.
		run_name = frappe.db.get_value(
			"AI Agent Run",
			{"instance": self.instance.name, "status": "Suspended"},
			"name",
		)
		self.assertIsNotNone(run_name)
		self.assertEqual(
			frappe.db.get_value("AI Agent Run", run_name, "pending_human_task"),
			row.task_id,
		)

		# Not a retry target / not "waiting for AI execution".
		self.assertEqual(self.instance.get_parked_ai_units(), [])

	def test_rekicked_job_on_suspended_task_is_noop(self):
		task_id = self._park_linear()
		self._suspend(task_id)
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run"
		) as run:
			with patch.object(frappe, "enqueue"):
				self.instance.resume_parked_ai(kind="service_task", task_id=task_id)
		run.assert_not_called()
		# still exactly one human row
		rows = [
			r for r in self.instance.active_tasks
			if str(r.task_id).startswith(self.instance.AI_HUMAN_PREFIX)
		]
		self.assertEqual(len(rows), 1)

	def test_engine_pass_does_not_repark_suspended_task(self):
		task_id = self._park_linear()
		self._suspend(task_id)

		wf = bpmn_engine.restore_workflow(
			workflow_state=json.loads(self.instance.workflow_state)
		)
		self.instance._service_task_extensions = {"Agent_1": dict(_AGENT_CFG)}
		with patch.object(frappe, "enqueue") as enqueue:
			self.instance._run_engine(wf)
		enqueue.assert_not_called()
		self.assertEqual(self.instance.waiting_for_ai, 0)

	def test_sync_active_tasks_keeps_human_row(self):
		task_id = self._park_linear()
		self._suspend(task_id)
		wf = bpmn_engine.restore_workflow(
			workflow_state=json.loads(self.instance.workflow_state)
		)
		self.instance._sync_active_tasks(wf)
		self.assertIsNotNone(self._human_row())


class TestHumanCompletionAndResume(HitlHarness):
	def _suspend_and_get_row(self):
		task_id = self._park_linear()
		self._suspend(task_id)
		return task_id, self._human_row()

	def test_complete_ai_human_task_stores_result_and_enqueues_resume(self):
		task_id, row = self._suspend_and_get_row()

		with patch.object(frappe, "enqueue") as enqueue:
			self.instance.complete_ai_human_task(
				row.task_id, {"action": "Approve", "note": "go ahead"}
			)

		self.assertEqual(row.status, "Completed")
		self.assertEqual(self.instance.waiting_for_human, "")

		enqueue.assert_called_once()
		kwargs = enqueue.call_args.kwargs
		self.assertEqual(kwargs["kind"], "human_resume")
		self.assertEqual(kwargs["task_id"], task_id)
		self.assertEqual(kwargs["queue"], "bpmn_ai_agent")

		# The human result landed on the checkpoint.
		run_name = frappe.db.get_value(
			"AI Agent Run", {"instance": self.instance.name, "status": "Suspended"}, "name"
		)
		payload = json.loads(frappe.db.get_value("AI Agent Run", run_name, "checkpoint"))
		self.assertEqual(payload["pending_result"], {"action": "Approve", "note": "go ahead"})

	def test_complete_twice_throws(self):
		_, row = self._suspend_and_get_row()
		with patch.object(frappe, "enqueue"):
			self.instance.complete_ai_human_task(row.task_id, {"action": "Approve"})
		with self.assertRaises(frappe.ValidationError):
			self.instance.complete_ai_human_task(row.task_id, {"action": "Approve"})

	def test_human_resume_completes_task_and_flow(self):
		task_id, row = self._suspend_and_get_row()
		with patch.object(frappe, "enqueue"):
			self.instance.complete_ai_human_task(row.task_id, {"action": "Approve"})

		captured = {}

		def fake_run(_self, config, context):
			captured["resume_state"] = config.resume_state
			return _final_result("refund processed")

		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run", new=fake_run
		):
			with patch.object(frappe, "enqueue"):
				self.instance.resume_parked_ai(kind="human_resume", task_id=task_id)

		# The executor was resumed with the human's answer injected.
		state = captured["resume_state"]
		self.assertEqual(json.loads(state["human_result"]), {"action": "Approve"})
		self.assertEqual(state["turns_used"], 1)

		# Flow ran to the End Event; all waits cleared; run finalized.
		self.assertEqual(self.instance.status, "Completed")
		self.assertEqual(self.instance.waiting_for_ai, 0)
		self.assertEqual(self.instance.waiting_for_human, "")
		run_status = frappe.db.get_value(
			"AI Agent Run", {"instance": self.instance.name}, "status"
		)
		self.assertEqual(run_status, "Success")

	def test_human_resume_redelivery_is_noop(self):
		task_id, row = self._suspend_and_get_row()
		with patch.object(frappe, "enqueue"):
			self.instance.complete_ai_human_task(row.task_id, {"action": "Approve"})
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=_final_result(),
		) as run:
			with patch.object(frappe, "enqueue"):
				self.instance.resume_parked_ai(kind="human_resume", task_id=task_id)
				calls = run.call_count
				self.instance.resume_parked_ai(kind="human_resume", task_id=task_id)
		self.assertEqual(run.call_count, calls)
		self.assertEqual(self.instance.status, "Completed")

	def test_resume_can_suspend_again(self):
		task_id, row = self._suspend_and_get_row()
		with patch.object(frappe, "enqueue"):
			self.instance.complete_ai_human_task(row.task_id, {"action": "Approve"})

		# The resumed agent asks for a SECOND human input.
		second = _suspended_result()
		second.suspension["pending_call"]["id"] = "h2"
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=second,
		):
			with patch.object(frappe, "enqueue"):
				self.instance.resume_parked_ai(kind="human_resume", task_id=task_id)

		self.assertEqual(self.instance.status, "Active")
		self.assertEqual(self.instance.waiting_for_human, "Approve Refund")
		rows = [
			r for r in self.instance.active_tasks
			if str(r.task_id).startswith(self.instance.AI_HUMAN_PREFIX)
			and r.status == "Waiting"
		]
		self.assertEqual(len(rows), 1)  # a fresh waiting row for the new pause


class TestCompleteTaskApiRouting(HitlHarness):
	def test_complete_task_routes_human_rows_to_resume(self):
		task_id = self._park_linear()
		self._suspend(task_id)
		row = self._human_row()

		from one_bpmn.api import instance_api

		with patch.object(frappe, "enqueue") as enqueue:
			response = instance_api.complete_task(
				self.instance.name, row.task_id, data=json.dumps({"action": "Approve"})
			)

		self.assertTrue(response["queued"])
		self.assertEqual(response["waiting_for_human"], "")
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.kwargs["kind"], "human_resume")

	def test_complete_task_validates_action_for_human_rows(self):
		task_id = self._park_linear()
		self._suspend(task_id)
		row = self._human_row()

		from one_bpmn.api import instance_api

		with self.assertRaises(frappe.ValidationError):
			instance_api.complete_task(
				self.instance.name, row.task_id, data=json.dumps({"action": "Escalate"})
			)
