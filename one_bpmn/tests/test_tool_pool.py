# Copyright (c) 2026, one-fm and contributors
# WI-001353 (2-03): tool-pool resolution — merge diagram tasks and registry.

from __future__ import annotations

from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.tool_pool import (
	DIAGRAM_TASK,
	REGISTRY_TOOL,
	resolve_tool_pool,
)
from one_bpmn.api.compilation import _validate_adhoc_selector_pool
from one_bpmn.one_bpmn import engine

FIXTURES = Path(__file__).parent / "fixtures"


def _registry_available() -> bool:
	"""The AI Agent Tool doctype (WI-001354) and compiler (WI-001355) ship on
	sibling branches; registry-half tests only run where both are present."""
	if not frappe.db.exists("DocType", "AI Agent Tool"):
		return False
	try:
		from one_bpmn.agents.tool_registry import compile_tool_spec  # noqa: F401
		from one_bpmn.one_bpmn.doctype.ai_agent_tool import ai_agent_tool  # noqa: F401
	except ImportError:
		return False
	return True


def _adhoc_subworkflow():
	xml = (FIXTURES / "adhoc_three_tasks.bpmn").read_text()
	spec_dict, sp_specs = engine.parse_bpmn(xml, "Process_AdhocThree")
	wf = engine.create_workflow(spec_dict, sp_specs, initial_data={"done": False})
	wf.do_engine_steps()
	return next(iter(wf.subprocesses.values()))


def _selector_xml(inner: str) -> str:
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs_Pool" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_Pool" isExecutable="true">
    <bpmn:adHocSubProcess id="AdhocSub_1" spiffworkflow:serviceType="ai_task_selector">
      {inner}
    </bpmn:adHocSubProcess>
  </bpmn:process>
</bpmn:definitions>
"""


class TestResolveToolPool(FrappeTestCase):
	# ── Scenario 1: one candidate per head task, documentation as description ──

	def test_diagram_candidates_from_inner_tasks(self):
		sp = _adhoc_subworkflow()
		pool = resolve_tool_pool(sp, {"aiToolSources": "diagram"})
		by_name = {c.spec.name: c for c in pool}
		self.assertEqual(set(by_name), {"task_a", "task_b", "task_c"})
		self.assertEqual(by_name["task_a"].spec.description, "Collect the required details.")
		self.assertEqual(by_name["task_b"].spec.description, "Verify the collected details.")
		self.assertTrue(all(c.source == DIAGRAM_TASK for c in pool))

	# ── Scenario 5: every candidate is ToolSpec-shaped ──

	def test_candidates_are_toolspec_shaped(self):
		sp = _adhoc_subworkflow()
		for candidate in resolve_tool_pool(sp, {"aiToolSources": "diagram"}):
			self.assertTrue(hasattr(candidate.spec, "name"))
			self.assertTrue(hasattr(candidate.spec, "description"))
			self.assertIsInstance(candidate.spec.parameters, dict)
			self.assertIsInstance(candidate.spec.required, list)

	# ── Scenarios 2/3: aiToolSources gating ──

	def test_diagram_only_excludes_registry(self):
		if not _registry_available():
			self.skipTest("registry doctype/compiler not on this branch")
		self._make_registry_tool("pool_scope_tool")
		sp = _adhoc_subworkflow()
		pool = resolve_tool_pool(sp, {"aiToolSources": "diagram"}, "Some Model")
		self.assertTrue(all(c.source == DIAGRAM_TASK for c in pool))

	def test_both_includes_global_registry_tools(self):
		if not _registry_available():
			self.skipTest("registry doctype/compiler not on this branch")
		self._make_registry_tool("pool_global_tool")
		sp = _adhoc_subworkflow()
		pool = resolve_tool_pool(sp, {"aiToolSources": "both"}, "Some Model")
		registry_names = {c.spec.name for c in pool if c.source == REGISTRY_TOOL}
		self.assertIn("pool_global_tool", registry_names)

	def _make_registry_tool(self, name):
		if frappe.db.exists("AI Agent Tool", name):
			return
		frappe.get_doc(
			{
				"doctype": "AI Agent Tool",
				"tool_name": name,
				"description": "Test registry tool.",
				"input_schema": '{"x": {"type": "string"}}',
				"handler_type": "server_script",
				"handler_reference": self._make_script(f"{name} handler"),
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

	def _make_script(self, name):
		if not frappe.db.exists("Server Script", name):
			frappe.get_doc(
				{
					"doctype": "Server Script",
					"name": name,
					"script_type": "API",
					"api_method": name.lower().replace(" ", "_"),
					"script": "frappe.response['message'] = {'ok': True}",
				}
			).insert(ignore_permissions=True)
		return name


class TestSelectorPoolCompileValidation(FrappeTestCase):
	# ── Scenario 6 (eligibility decision 2026-07-02): containers rejected ──

	def test_container_candidate_rejected(self):
		for tag, label in (
			("subProcess", "Sub-Process"),
			("callActivity", "Call Activity"),
			("adHocSubProcess", "Ad-hoc Subprocess"),
		):
			xml = _selector_xml(f'<bpmn:{tag} id="inner_container_1" />')
			with self.assertRaises(frappe.ValidationError, msg=label):
				_validate_adhoc_selector_pool(xml, "Some Model")

	def test_connected_container_allowed(self):
		# A container wired into a sequence flow is normal BPMN, not a
		# selector candidate — only no-incoming containers are rejected.
		xml = _selector_xml(
			'<bpmn:subProcess id="inner_connected"><bpmn:incoming>f1</bpmn:incoming></bpmn:subProcess>'
		)
		_validate_adhoc_selector_pool(xml, "Some Model")  # must not raise

	def test_leaf_tasks_of_all_kinds_allowed(self):
		xml = _selector_xml(
			'<bpmn:scriptTask id="c1" /><bpmn:userTask id="c2" />'
			'<bpmn:sendTask id="c3" /><bpmn:businessRuleTask id="c4" />'
		)
		_validate_adhoc_selector_pool(xml, "Some Model")  # must not raise

	def test_untagged_adhoc_not_validated(self):
		xml = _selector_xml('<bpmn:callActivity id="inner_ca" />').replace(
			' spiffworkflow:serviceType="ai_task_selector"', ""
		)
		_validate_adhoc_selector_pool(xml, "Some Model")  # must not raise

	# ── Scenario 4: diagram/registry name collision rejected ──

	def test_name_collision_with_registry_tool_rejected(self):
		if not _registry_available():
			self.skipTest("registry doctype/compiler not on this branch")
		tool_name = "collision_task_x"
		if not frappe.db.exists("AI Agent Tool", tool_name):
			if not frappe.db.exists("Server Script", "Collision Handler"):
				frappe.get_doc(
					{
						"doctype": "Server Script",
						"name": "Collision Handler",
						"script_type": "API",
						"api_method": "collision_handler",
						"script": "pass",
					}
				).insert(ignore_permissions=True)
			frappe.get_doc(
				{
					"doctype": "AI Agent Tool",
					"tool_name": tool_name,
					"description": "Collides with a diagram task.",
					"input_schema": '{"x": {"type": "string"}}',
					"handler_type": "server_script",
					"handler_reference": "Collision Handler",
					"is_active": 1,
				}
			).insert(ignore_permissions=True)

		xml = _selector_xml(f'<bpmn:task id="{tool_name}" />')
		with self.assertRaises(frappe.ValidationError):
			_validate_adhoc_selector_pool(xml, "Some Model")
