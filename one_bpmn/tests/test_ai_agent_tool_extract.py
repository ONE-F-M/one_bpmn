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
		# human (user task) and noconfig (script without serverScript) excluded
		self.assertEqual(set(by_id), {"lookup", "notify"})
		self.assertEqual(by_id["lookup"]["serverScript"], "Lookup Cust")
		self.assertEqual(by_id["lookup"]["description"], "Look up a customer.")
		self.assertEqual(by_id["notify"]["serviceType"], "update_field")

	def test_no_agents_is_noop(self):
		xml = _xml("", TOOLS)  # serviceType=ai_agent but no aiToolsAdhoc
		svc = _extract_service_task_config(xml)
		_resolve_ai_agent_tool_shapes(xml, svc)
		self.assertNotIn("aiToolShapes", svc.get("Agent_1", {}))


class TestValidateAgentTools(FrappeTestCase):
	def test_valid_reference_passes(self):
		xml = _xml('spiffworkflow:aiToolsAdhoc="Tools_1"', TOOLS)
		_validate_ai_agent_tools(xml, _extensions(xml))  # must not raise

	def test_missing_reference_rejected(self):
		xml = _xml('spiffworkflow:aiToolsAdhoc="Nope"', TOOLS)
		with self.assertRaises(frappe.ValidationError):
			_validate_ai_agent_tools(xml, _extensions(xml))

	def test_empty_toolbox_rejected(self):
		# adhoc exists but has only ineligible shapes
		xml = _xml('spiffworkflow:aiToolsAdhoc="Tools_1"', '<bpmn:userTask id="human" />')
		with self.assertRaises(frappe.ValidationError):
			_validate_ai_agent_tools(xml, _extensions(xml))

	def test_unset_reference_not_validated(self):
		xml = _xml("", TOOLS)  # draft agent, no aiToolsAdhoc
		_validate_ai_agent_tools(xml, _extensions(xml))  # must not raise
