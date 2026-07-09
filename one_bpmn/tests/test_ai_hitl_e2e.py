# Copyright (c) 2026, one-fm and contributors
# Durable AI Agent HITL, story 6 — end-to-end: an agent gathers data with an
# automatic tool, calls an approval HUMAN tool, suspends, resumes on the
# person's answer, and finishes; the flow continues to the End Event.
#
# The diagram goes through the REAL compile pipeline (tool shapes extracted
# from the referenced ad-hoc sub-process) and the REAL executor + step loop —
# only the LLM adapter is scripted (patched at get_llm_adapter), so every
# layer between the model and the engine is exercised: step loop suspension →
# checkpoint → engine parking → human task row → complete_task → resume job →
# final answer → task completion → flow continuation.

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from SpiffWorkflow.util.task import TaskState

from one_bpmn.agents.llm_provider.base import StepResult, StepToolCall
from one_bpmn.api.compilation import (
	_extract_service_task_config,
	_extract_user_task_config,
	_resolve_ai_agent_tool_shapes,
)
from one_bpmn.one_bpmn import engine as bpmn_engine

test_ignore = ["BPMN Process Model"]

# Agent flow: start → Agent_1 → end. The agent's tools live in the (unwired)
# ad-hoc sub-process: one script tool + one human approval tool.
_DEMO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs_HITL_Demo" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="proc_hitl_demo" isExecutable="true">
    <bpmn:startEvent id="start_1"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="start_1" targetRef="Agent_1" />
    <bpmn:serviceTask id="Agent_1" name="Refund Agent"
        spiffworkflow:serviceType="ai_agent"
        spiffworkflow:aiToolsAdhoc="Tools_1"
        spiffworkflow:aiUserPrompt="Handle the refund request"
        spiffworkflow:aiOutputVariable="agent_out">
      <bpmn:incoming>f1</bpmn:incoming>
      <bpmn:outgoing>f2</bpmn:outgoing>
    </bpmn:serviceTask>
    <bpmn:sequenceFlow id="f2" sourceRef="Agent_1" targetRef="end_1" />
    <bpmn:endEvent id="end_1"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
    <bpmn:adHocSubProcess id="Tools_1">
      <bpmn:scriptTask id="check_balance" spiffworkflow:serverScript="_HITL Check Balance">
        <bpmn:documentation>Check the customer's balance.</bpmn:documentation>
      </bpmn:scriptTask>
      <bpmn:userTask id="approve_refund" name="Approve Refund"
          spiffworkflow:assigneeMode="User"
          spiffworkflow:assigneeUser="Administrator"
          spiffworkflow:taskActions="Approve,Reject">
        <bpmn:documentation>Ask a manager to approve the refund.</bpmn:documentation>
      </bpmn:userTask>
    </bpmn:adHocSubProcess>
  </bpmn:process>
</bpmn:definitions>"""


class ScriptedAdapter:
	"""step()-level LLM script; the last step repeats."""

	def __init__(self, steps):
		self._steps = list(steps)
		self.transcripts = []

	async def step(self, system, transcript, tools=None, max_tokens=16384):
		self.transcripts.append([dict(e) for e in transcript])
		if len(self._steps) > 1:
			return self._steps.pop(0)
		return self._steps[0]


def _turn_tool(name, args, call_id="c1"):
	return StepResult(
		tool_calls=[StepToolCall(id=call_id, name=name, arguments=args)],
		prompt_tokens=10,
		completion_tokens=2,
	)


class TestDurableAgentHitlEndToEnd(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("AI Provider", "_Test HITL E2E Provider"):
			frappe.get_doc({
				"doctype": "AI Provider",
				"provider_name": "_Test HITL E2E Provider",
				"provider_type": "OpenAI",
				"api_key": "test-key-not-real",
				"default_model": "gpt-test",
				"enabled": 1,
			}).insert(ignore_permissions=True)
		if not frappe.db.exists("Server Script", "_HITL Check Balance"):
			frappe.get_doc({
				"doctype": "Server Script",
				"name": "_HITL Check Balance",
				"script_type": "API",
				"api_method": "_hitl_check_balance",
				"script": 'result["balance"] = "120 KWD"',
			}).insert(ignore_permissions=True)

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

	def _start_and_park(self):
		"""Compile the demo XML for real, start the flow, park the agent."""
		svc = _extract_service_task_config(_DEMO_XML)
		svc["Agent_1"]["aiProvider"] = "_Test HITL E2E Provider"
		_resolve_ai_agent_tool_shapes(_DEMO_XML, svc)
		usr = _extract_user_task_config(_DEMO_XML)

		# Sanity: the compile really extracted both tools, human flagged.
		shapes = {s["bpmn_id"]: s for s in json.loads(svc["Agent_1"]["aiToolShapes"])}
		assert set(shapes) == {"check_balance", "approve_refund"}
		assert shapes["approve_refund"]["human"] is True

		spec_dict, sp_specs = bpmn_engine.parse_bpmn(_DEMO_XML, "proc_hitl_demo")
		self.instance._service_task_extensions = svc
		self.instance._user_task_extensions = usr
		self.instance._script_task_extensions = {}
		wf = bpmn_engine.create_workflow(spec_dict, sp_specs, initial_data={})
		with patch.object(frappe, "enqueue"):
			self.instance._run_engine(wf)
		task = next(t for t in wf.get_tasks() if t.task_spec.name == "Agent_1")
		self.assertEqual(task.state, TaskState.STARTED)

		bpmn_engine.clean_doc_from_wf_data(wf)
		self.instance.workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))
		self.instance.serialized_spec = json.dumps({
			"service_task_extensions": svc,
			"user_task_extensions": usr,
			"script_task_extensions": {},
		})
		self.instance.db_update()
		self.instance.update_children()
		return str(task.id)

	def _adapter_patch(self, adapter):
		return patch(
			"one_bpmn.agents.llm_provider.factory.get_llm_adapter",
			return_value=adapter,
		)

	def _human_row(self, instance=None):
		instance = instance or self.instance
		return next(
			(
				r
				for r in instance.active_tasks
				if str(r.task_id).startswith(instance.AI_HUMAN_PREFIX)
				and r.status == "Waiting"
			),
			None,
		)

	def test_approve_path_end_to_end(self):
		task_id = self._start_and_park()

		# Segment 1: the model checks the balance (real Server Script runs),
		# then calls the human approval tool → the agent suspends.
		adapter = ScriptedAdapter([
			_turn_tool("check_balance", {}, "a1"),
			_turn_tool("approve_refund", {"request": "Refund 30 KWD for SO-77?"}, "h1"),
		])
		with self._adapter_patch(adapter):
			with patch.object(frappe, "enqueue"):
				self.instance.resume_parked_ai(kind="service_task", task_id=task_id)

		row = self._human_row()
		self.assertIsNotNone(row)
		self.assertEqual(row.task_name, "Approve Refund")
		self.assertEqual(row.assigned_user, "Administrator")
		self.assertEqual(self.instance.waiting_for_human, "Approve Refund")
		# the automatic tool really executed through the Server Script
		self.assertIn("120 KWD", json.dumps(adapter.transcripts[-1]))

		# The person approves via the real API (validation + routing).
		from one_bpmn.api import instance_api

		with patch.object(frappe, "enqueue") as enqueue:
			instance_api.complete_task(
				self.instance.name, row.task_id, data=json.dumps({"action": "Approve"})
			)
		self.assertEqual(enqueue.call_args.kwargs["kind"], "human_resume")

		# Segment 2: resumed with the approval, the model concludes.
		final_adapter = ScriptedAdapter([
			StepResult(content="Refund of 30 KWD approved and recorded.", prompt_tokens=20, completion_tokens=5),
		])
		self.instance.reload()
		with self._adapter_patch(final_adapter):
			with patch.object(frappe, "enqueue"):
				self.instance.resume_parked_ai(kind="human_resume", task_id=task_id)

		# The resumed model call saw the human's answer as the tool result.
		last_entry = final_adapter.transcripts[0][-1]
		self.assertEqual(last_entry["role"], "tool_results")
		human_results = [r for r in last_entry["results"] if r["name"] == "approve_refund"]
		self.assertIn("Approve", human_results[0]["content"])

		# Flow completed; evidence spans both segments; run is Success.
		self.assertEqual(self.instance.status, "Completed")
		self.assertEqual(self.instance.waiting_for_human, "")
		self.assertEqual(self.instance.waiting_for_ai, 0)
		run = frappe.get_all(
			"AI Agent Run",
			filters={"instance": self.instance.name},
			fields=["status", "total_prompt_tokens"],
		)[0]
		self.assertEqual(run.status, "Success")
		self.assertEqual(run.total_prompt_tokens, 40)  # 10+10 suspended + 20 final

	def test_reject_path_agent_reasons_about_outcome(self):
		task_id = self._start_and_park()
		adapter = ScriptedAdapter([
			_turn_tool("approve_refund", {"request": "Refund 500 KWD?"}, "h1"),
		])
		with self._adapter_patch(adapter):
			with patch.object(frappe, "enqueue"):
				self.instance.resume_parked_ai(kind="service_task", task_id=task_id)
		row = self._human_row()

		from one_bpmn.api import instance_api

		with patch.object(frappe, "enqueue"):
			instance_api.complete_task(
				self.instance.name, row.task_id,
				data=json.dumps({"action": "Reject", "reason": "amount exceeds policy"}),
			)

		final_adapter = ScriptedAdapter([
			StepResult(content="The refund was rejected: amount exceeds policy. Closing without refund."),
		])
		self.instance.reload()
		with self._adapter_patch(final_adapter):
			with patch.object(frappe, "enqueue"):
				self.instance.resume_parked_ai(kind="human_resume", task_id=task_id)

		# The rejection reached the model as the tool result — it reasoned
		# about it and the flow still completed normally (reject ≠ error).
		last_entry = final_adapter.transcripts[0][-1]
		self.assertIn("amount exceeds policy", json.dumps(last_entry))
		self.assertEqual(self.instance.status, "Completed")
		self.assertEqual(
			frappe.get_all(
				"AI Agent Run", filters={"instance": self.instance.name}, pluck="status"
			)[0],
			"Success",
		)

	def test_restart_in_the_middle_checkpoint_survives(self):
		task_id = self._start_and_park()
		adapter = ScriptedAdapter([
			_turn_tool("approve_refund", {"request": "ok?"}, "h1"),
		])
		with self._adapter_patch(adapter):
			with patch.object(frappe, "enqueue"):
				self.instance.resume_parked_ai(kind="service_task", task_id=task_id)
		row_id = self._human_row().task_id

		# "Restart": drop every in-memory object and reload purely from DB —
		# what a worker or web process sees after a restart.
		fresh = frappe.get_doc("BPMN Process Instance", self.instance.name)
		fresh_row = self._human_row(fresh)
		self.assertIsNotNone(fresh_row)
		self.assertEqual(fresh_row.task_id, row_id)
		self.assertEqual(fresh.waiting_for_human, "Approve Refund")

		with patch.object(frappe, "enqueue"):
			fresh.complete_ai_human_task(row_id, {"action": "Approve"})

		final_adapter = ScriptedAdapter([StepResult(content="done after restart")])
		fresh2 = frappe.get_doc("BPMN Process Instance", self.instance.name)
		with self._adapter_patch(final_adapter):
			with patch.object(frappe, "enqueue"):
				fresh2.resume_parked_ai(kind="human_resume", task_id=task_id)

		self.assertEqual(fresh2.status, "Completed")
		# The resumed conversation reloaded from the DB checkpoint intact.
		roles = [e["role"] for e in final_adapter.transcripts[0]]
		self.assertEqual(roles, ["user", "assistant", "tool_results"])
