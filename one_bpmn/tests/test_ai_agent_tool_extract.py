# Copyright (c) 2026, one-fm and contributors
# WI-001421: compile-time extraction + validation of an AI Agent Task's tool
# reference (the shapes of its referenced ad-hoc sub-process).

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import (
	_extract_service_task_config,
	_resolve_ai_agent_tool_shapes,
	_validate_ai_agent_tools,
)


def _xml(agent_attrs: str, tools_inner: str, adhoc_id: str = "Tools_1") -> str:
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="P1" isExecutable="true">
    <bpmn:serviceTask id="Agent_1" spiffworkflow:serviceType="ai_agent" {agent_attrs} />
    <bpmn:adHocSubProcess id="{adhoc_id}">
      {tools_inner}
    </bpmn:adHocSubProcess>
  </bpmn:process>
</bpmn:definitions>"""


TOOLS = (
	'<bpmn:scriptTask id="lookup" spiffworkflow:serverScript="Lookup Cust">'
	"<bpmn:documentation>Look up a customer.</bpmn:documentation></bpmn:scriptTask>"
	'<bpmn:serviceTask id="notify" spiffworkflow:serviceType="update_field" />'
	'<bpmn:userTask id="human" />'
	'<bpmn:scriptTask id="noconfig" />'
)


def _extensions(xml):
	svc = _extract_service_task_config(xml)
	_resolve_ai_agent_tool_shapes(xml, svc)
	return svc


class TestResolveToolShapes(FrappeTestCase):
	def test_embeds_eligible_shapes_only(self):
		svc = _extensions(_xml('spiffworkflow:aiToolsAdhoc="Tools_1"', TOOLS))
		shapes = json.loads(svc["Agent_1"]["aiToolShapes"])
		by_id = {s["bpmn_id"]: s for s in shapes}
		# noconfig (script without serverScript) excluded; the user task is
		# included as a HUMAN tool (Durable AI Agent HITL)
		self.assertEqual(set(by_id), {"lookup", "notify", "human"})
		self.assertEqual(by_id["lookup"]["serverScript"], "Lookup Cust")
		self.assertEqual(by_id["lookup"]["description"], "Look up a customer.")
		self.assertEqual(by_id["notify"]["serviceType"], "update_field")
		self.assertTrue(by_id["human"]["human"])
		self.assertNotIn("human", by_id["lookup"])
		self.assertNotIn("human", by_id["notify"])

	def test_no_agents_is_noop(self):
		xml = _xml("", TOOLS)  # serviceType=ai_agent but no aiToolsAdhoc
		svc = _extract_service_task_config(xml)
		_resolve_ai_agent_tool_shapes(xml, svc)
		self.assertNotIn("aiToolShapes", svc.get("Agent_1", {}))

	def test_embeds_ai_tool_params(self):
		params = json.dumps(
			{"properties": {"query": {"type": "string", "description": "Search text"}}, "required": ["query"]}
		).replace('"', "&quot;")
		tools = (
			f'<bpmn:scriptTask id="lookup" spiffworkflow:serverScript="Lookup Cust" spiffworkflow:aiToolParams="{params}">'
			"<bpmn:documentation>Look up a customer.</bpmn:documentation></bpmn:scriptTask>"
			'<bpmn:scriptTask id="no_params" spiffworkflow:serverScript="No Params" />'
		)
		svc = _extensions(_xml('spiffworkflow:aiToolsAdhoc="Tools_1"', tools))
		shapes = json.loads(svc["Agent_1"]["aiToolShapes"])
		by_id = {s["bpmn_id"]: s for s in shapes}
		self.assertEqual(by_id["lookup"]["parameters"], {"query": {"type": "string", "description": "Search text"}})
		self.assertEqual(by_id["lookup"]["required"], ["query"])
		# A shape with no aiToolParams carries no parameters/required keys.
		self.assertNotIn("parameters", by_id["no_params"])
		self.assertNotIn("required", by_id["no_params"])


class TestValidateAgentTools(FrappeTestCase):
	def test_valid_reference_passes(self):
		xml = _xml('spiffworkflow:aiToolsAdhoc="Tools_1"', TOOLS)
		_validate_ai_agent_tools(xml, _extensions(xml))  # must not raise

	def test_missing_reference_rejected(self):
		xml = _xml('spiffworkflow:aiToolsAdhoc="Nope"', TOOLS)
		with self.assertRaises(frappe.ValidationError):
			_validate_ai_agent_tools(xml, _extensions(xml))

	def test_empty_toolbox_rejected(self):
		# adhoc exists but has only ineligible shapes (a User/Manual task
		# would now count as a HUMAN tool — use an unconfigured script task)
		xml = _xml('spiffworkflow:aiToolsAdhoc="Tools_1"', '<bpmn:scriptTask id="noconfig" />')
		with self.assertRaises(frappe.ValidationError):
			_validate_ai_agent_tools(xml, _extensions(xml))

	def test_unset_reference_not_validated(self):
		xml = _xml("", TOOLS)  # draft agent, no aiToolsAdhoc
		_validate_ai_agent_tools(xml, _extensions(xml))  # must not raise
