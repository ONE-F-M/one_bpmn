# Copyright (c) 2026, one-fm and contributors
# Durable AI Agent HITL, story 4 — human-tool eligibility (compile + shape
# tools). User/Manual shapes of the referenced ad-hoc sub-process compile
# into HUMAN ToolSpecs that route to suspension, never inline execution.

from __future__ import annotations

import asyncio
import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor.step_loop import run_agent_loop
from one_bpmn.agents.llm_provider.base import StepResult, StepToolCall
from one_bpmn.agents.shape_tools import compile_shape_tools
from one_bpmn.api.compilation import (
	_extract_service_task_config,
	_resolve_ai_agent_tool_shapes,
	_validate_ai_agent_tools,
)


def _xml(tools_inner: str) -> str:
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="P1" isExecutable="true">
    <bpmn:serviceTask id="Agent_1" spiffworkflow:serviceType="ai_agent" spiffworkflow:aiToolsAdhoc="Tools_1" />
    <bpmn:adHocSubProcess id="Tools_1">
      {tools_inner}
    </bpmn:adHocSubProcess>
  </bpmn:process>
</bpmn:definitions>"""


def _shapes(tools_inner: str) -> list:
	xml = _xml(tools_inner)
	svc = _extract_service_task_config(xml)
	_resolve_ai_agent_tool_shapes(xml, svc)
	return json.loads(svc["Agent_1"]["aiToolShapes"])


class TestHumanToolExtraction(FrappeTestCase):
	def test_user_and_manual_tasks_become_human_tools(self):
		shapes = _shapes(
			'<bpmn:userTask id="Approve_1" name="Approve Refund">'
			"<bpmn:documentation>Ask a manager to approve.</bpmn:documentation></bpmn:userTask>"
			'<bpmn:manualTask id="Verify_1" name="Physical Check" />'
		)
		by_id = {s["bpmn_id"]: s for s in shapes}
		self.assertEqual(set(by_id), {"Approve_1", "Verify_1"})
		for s in by_id.values():
			self.assertTrue(s["human"])
		self.assertEqual(by_id["Approve_1"]["label"], "Approve Refund")
		self.assertEqual(by_id["Approve_1"]["description"], "Ask a manager to approve.")
		self.assertEqual(by_id["Verify_1"]["label"], "Physical Check")

	def test_human_tool_gets_default_request_parameter(self):
		shapes = _shapes('<bpmn:userTask id="Approve_1" name="Approve" />')
		self.assertIn("request", shapes[0]["parameters"])
		self.assertEqual(shapes[0]["required"], ["request"])

	def test_human_tool_explicit_params_override_default(self):
		params = json.dumps({
			"properties": {"amount": {"type": "string", "description": "KWD amount"}},
			"required": ["amount"],
		}).replace('"', "&quot;")
		shapes = _shapes(
			f'<bpmn:userTask id="Approve_1" name="Approve" spiffworkflow:aiToolParams="{params}" />'
		)
		self.assertEqual(list(shapes[0]["parameters"]), ["amount"])
		self.assertEqual(shapes[0]["required"], ["amount"])

	def test_human_only_toolbox_passes_validation(self):
		xml = _xml('<bpmn:userTask id="Approve_1" name="Approve" />')
		svc = _extract_service_task_config(xml)
		_resolve_ai_agent_tool_shapes(xml, svc)
		_validate_ai_agent_tools(xml, svc)  # must not raise

	def test_automatic_shapes_unchanged(self):
		shapes = _shapes(
			'<bpmn:scriptTask id="lookup" spiffworkflow:serverScript="Lookup" />'
			'<bpmn:userTask id="Approve_1" name="Approve" />'
		)
		by_id = {s["bpmn_id"]: s for s in shapes}
		self.assertNotIn("human", by_id["lookup"])
		self.assertNotIn("parameters", by_id["lookup"])


class TestHumanToolCompilation(FrappeTestCase):
	def _instance(self):
		return frappe._dict(context_doctype="", context_docname="", name="_inst")

	def test_human_descriptor_compiles_to_human_toolspec(self):
		tools = compile_shape_tools(
			[
				{"bpmn_id": "lookup", "description": "look", "serverScript": "X"},
				{"bpmn_id": "Approve_1", "human": True, "label": "Approve Refund",
				 "parameters": {"request": {"type": "string"}}, "required": ["request"]},
			],
			self._instance(),
		)
		by_name = {t.name: t for t in tools}
		self.assertEqual(set(by_name), {"lookup", "Approve_1"})
		self.assertTrue(by_name["Approve_1"].human)
		self.assertFalse(by_name["lookup"].human)
		self.assertEqual(by_name["Approve_1"].parameters, {"request": {"type": "string"}})
		# default description falls back to the label
		self.assertIn("Approve Refund", by_name["Approve_1"].description)

	def test_human_stub_never_executes_silently(self):
		tools = compile_shape_tools(
			[{"bpmn_id": "Approve_1", "human": True, "label": "Approve"}], self._instance()
		)
		with self.assertRaises(RuntimeError):
			tools[0].fn(request="hi")

	def test_human_tool_routes_to_suspension_in_the_loop(self):
		tools = compile_shape_tools(
			[{"bpmn_id": "Approve_1", "human": True, "label": "Approve",
			  "parameters": {"request": {"type": "string"}}, "required": ["request"]}],
			self._instance(),
		)

		class OneShot:
			async def step(self, system, transcript, tools=None, max_tokens=16384):
				return StepResult(
					tool_calls=[StepToolCall(id="h1", name="Approve_1", arguments={"request": "ok?"})]
				)

		completion, suspension = asyncio.run(
			run_agent_loop(
				OneShot(), system="s", user="u", tools=tools, max_turns=5
			)
		)
		self.assertIsNone(completion)
		self.assertEqual(suspension.pending_call["name"], "Approve_1")
		self.assertEqual(suspension.pending_call["arguments"], {"request": "ok?"})
