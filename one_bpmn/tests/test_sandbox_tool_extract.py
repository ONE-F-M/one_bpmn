# Copyright (c) 2026, one-fm and contributors
# Compile-time extraction + validation of a connector Service Task's
# sandboxToolsAdhoc reference — a second, independent ad-hoc sub-process
# whose shapes are schema-only: never compiled into directly-callable
# ToolSpecs by this engine, only forwarded (by the connector itself) to
# whatever it dispatches to for execution there.

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import (
	_extract_service_task_config,
	_resolve_ai_agent_tool_shapes,
	_resolve_sandbox_tool_shapes,
	_validate_ai_agent_tools,
	_validate_sandbox_tools,
)


def _xml(connector_attrs: str, tools_inner: str, adhoc_id: str = "SandboxTools_1", extra: str = "") -> str:
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="P1" isExecutable="true">
    <bpmn:serviceTask id="Dispatch_1" spiffworkflow:serviceType="connector" {connector_attrs} />
    <bpmn:adHocSubProcess id="{adhoc_id}">
      {tools_inner}
    </bpmn:adHocSubProcess>
    {extra}
  </bpmn:process>
</bpmn:definitions>"""


TOOLS = (
	'<bpmn:scriptTask id="read_file" spiffworkflow:serviceType="connector">'
	"<bpmn:documentation>Read a file.</bpmn:documentation></bpmn:scriptTask>"
	'<bpmn:scriptTask id="write_file" spiffworkflow:serviceType="connector">'
	"<bpmn:documentation>Write a file.</bpmn:documentation></bpmn:scriptTask>"
)


def _extensions(xml):
	svc = _extract_service_task_config(xml)
	_resolve_sandbox_tool_shapes(xml, svc)
	return svc


class TestResolveSandboxToolShapes(FrappeTestCase):
	def test_embeds_eligible_shapes_only(self):
		svc = _extensions(_xml('spiffworkflow:sandboxToolsAdhoc="SandboxTools_1"', TOOLS))
		shapes = json.loads(svc["Dispatch_1"]["sandboxToolShapes"])
		by_id = {s["bpmn_id"]: s for s in shapes}
		self.assertEqual(set(by_id), {"read_file", "write_file"})
		self.assertEqual(by_id["read_file"]["description"], "Read a file.")

	def test_no_reference_is_noop(self):
		xml = _xml("", TOOLS)  # serviceType=connector but no sandboxToolsAdhoc
		svc = _extract_service_task_config(xml)
		_resolve_sandbox_tool_shapes(xml, svc)
		self.assertNotIn("sandboxToolShapes", svc.get("Dispatch_1", {}))

	def test_non_connector_service_type_ignored(self):
		# sandboxToolsAdhoc set, but this is an ai_agent task, not a connector —
		# _connectors_with_sandbox_tools must not pick it up.
		xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="P1" isExecutable="true">
    <bpmn:serviceTask id="Agent_1" spiffworkflow:serviceType="ai_agent" spiffworkflow:sandboxToolsAdhoc="SandboxTools_1" />
    <bpmn:adHocSubProcess id="SandboxTools_1">{TOOLS}</bpmn:adHocSubProcess>
  </bpmn:process>
</bpmn:definitions>"""
		svc = _extract_service_task_config(xml)
		_resolve_sandbox_tool_shapes(xml, svc)
		self.assertNotIn("sandboxToolShapes", svc.get("Agent_1", {}))

	def test_coexists_with_ai_agent_tool_shapes_without_collision(self):
		# One diagram, both mechanisms at once: an AI Agent Task with its own
		# aiToolsAdhoc-referenced toolbox (executed directly by this engine),
		# and a connector with an unrelated sandboxToolsAdhoc-referenced one
		# (schema-only, forwarded elsewhere). Verifies _extract_tool_shapes'
		# statelessness — a second, independent extraction against a
		# different sub-process id must not affect or be affected by the first.
		agent_tools = '<bpmn:scriptTask id="lookup" spiffworkflow:serverScript="Lookup Cust" />'
		xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="P1" isExecutable="true">
    <bpmn:serviceTask id="Agent_1" spiffworkflow:serviceType="ai_agent" spiffworkflow:aiToolsAdhoc="AgentTools_1" />
    <bpmn:adHocSubProcess id="AgentTools_1">{agent_tools}</bpmn:adHocSubProcess>
    <bpmn:serviceTask id="Dispatch_1" spiffworkflow:serviceType="connector" spiffworkflow:sandboxToolsAdhoc="SandboxTools_1" />
    <bpmn:adHocSubProcess id="SandboxTools_1">{TOOLS}</bpmn:adHocSubProcess>
  </bpmn:process>
</bpmn:definitions>"""
		svc = _extract_service_task_config(xml)
		_resolve_ai_agent_tool_shapes(xml, svc)
		_resolve_sandbox_tool_shapes(xml, svc)

		agent_shapes = {s["bpmn_id"] for s in json.loads(svc["Agent_1"]["aiToolShapes"])}
		sandbox_shapes = {s["bpmn_id"] for s in json.loads(svc["Dispatch_1"]["sandboxToolShapes"])}
		self.assertEqual(agent_shapes, {"lookup"})
		self.assertEqual(sandbox_shapes, {"read_file", "write_file"})
		self.assertNotIn("sandboxToolShapes", svc["Agent_1"])
		self.assertNotIn("aiToolShapes", svc["Dispatch_1"])


class TestValidateSandboxTools(FrappeTestCase):
	def test_valid_reference_passes(self):
		xml = _xml('spiffworkflow:sandboxToolsAdhoc="SandboxTools_1"', TOOLS)
		_validate_sandbox_tools(xml, _extensions(xml))  # must not raise

	def test_missing_reference_rejected(self):
		xml = _xml('spiffworkflow:sandboxToolsAdhoc="Nope"', TOOLS)
		with self.assertRaises(frappe.ValidationError):
			_validate_sandbox_tools(xml, _extensions(xml))

	def test_empty_toolbox_rejected(self):
		xml = _xml('spiffworkflow:sandboxToolsAdhoc="SandboxTools_1"', '<bpmn:scriptTask id="noconfig" />')
		with self.assertRaises(frappe.ValidationError):
			_validate_sandbox_tools(xml, _extensions(xml))

	def test_unset_reference_not_validated(self):
		xml = _xml("", TOOLS)  # no sandboxToolsAdhoc at all
		_validate_sandbox_tools(xml, _extensions(xml))  # must not raise

	def test_orphaned_sandbox_subprocess_does_not_break_ai_agent_validation(self):
		# An ad-hoc sub-process referenced ONLY by sandboxToolsAdhoc (not by
		# any aiToolsAdhoc) must not trip _validate_ai_agent_tools — the two
		# validators must stay independent of each other.
		agent_tools = '<bpmn:scriptTask id="lookup" spiffworkflow:serverScript="Lookup Cust" />'
		xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="P1" isExecutable="true">
    <bpmn:serviceTask id="Agent_1" spiffworkflow:serviceType="ai_agent" spiffworkflow:aiToolsAdhoc="AgentTools_1" />
    <bpmn:adHocSubProcess id="AgentTools_1">{agent_tools}</bpmn:adHocSubProcess>
    <bpmn:serviceTask id="Dispatch_1" spiffworkflow:serviceType="connector" spiffworkflow:sandboxToolsAdhoc="SandboxTools_1" />
    <bpmn:adHocSubProcess id="SandboxTools_1">{TOOLS}</bpmn:adHocSubProcess>
  </bpmn:process>
</bpmn:definitions>"""
		svc = _extract_service_task_config(xml)
		_resolve_ai_agent_tool_shapes(xml, svc)
		_resolve_sandbox_tool_shapes(xml, svc)
		_validate_ai_agent_tools(xml, svc)  # must not raise
		_validate_sandbox_tools(xml, svc)  # must not raise
