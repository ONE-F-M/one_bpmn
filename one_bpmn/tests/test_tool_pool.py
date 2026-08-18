# Copyright (c) 2026, one-fm and contributors
# WI-001353 (2-03) + WI-001423: tool-pool resolution — the ad-hoc sub-process's
# own shapes are the tools (the AI Agent Tool registry was removed).

from __future__ import annotations

import json
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.tool_pool import DIAGRAM_TASK, resolve_tool_pool
from one_bpmn.api.compilation import _validate_adhoc_selector_pool
from one_bpmn.one_bpmn import engine

FIXTURES = Path(__file__).parent / "fixtures"


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
	# ── one candidate per head task, documentation as description ──

	def test_diagram_candidates_from_inner_tasks(self):
		sp = _adhoc_subworkflow()
		pool = resolve_tool_pool(sp, {})
		by_name = {c.spec.name: c for c in pool}
		self.assertEqual(set(by_name), {"task_a", "task_b", "task_c"})
		self.assertEqual(by_name["task_a"].spec.description, "Collect the required details.")
		self.assertEqual(by_name["task_b"].spec.description, "Verify the collected details.")
		self.assertTrue(all(c.source == DIAGRAM_TASK for c in pool))

	def test_candidates_are_toolspec_shaped(self):
		sp = _adhoc_subworkflow()
		for candidate in resolve_tool_pool(sp, {}):
			self.assertTrue(hasattr(candidate.spec, "name"))
			self.assertTrue(hasattr(candidate.spec, "description"))
			self.assertIsInstance(candidate.spec.parameters, dict)
			self.assertIsInstance(candidate.spec.required, list)

	def test_registry_gone_no_extra_candidates(self):
		# aiToolSources is now moot — the pool is the diagram shapes regardless.
		sp = _adhoc_subworkflow()
		names_default = {c.spec.name for c in resolve_tool_pool(sp, {})}
		names_registry = {c.spec.name for c in resolve_tool_pool(sp, {"aiToolSources": "registry"}, "M")}
		self.assertEqual(names_default, names_registry)

	# ── the model must be able to pass arguments to the step it activates ──

	def test_arguments_come_from_compiled_tool_shapes(self):
		"""Without this the selector could say WHICH step to run but not what
		to run it on, and any {{ task_data.<arg> }} connector input rendered
		as an unresolved placeholder."""
		sp = _adhoc_subworkflow()
		task_cfg = {
			"aiToolShapes": json.dumps(
				[
					{
						"bpmn_id": "task_a",
						"parameters": {"instruction": {"type": "string"}},
						"required": ["instruction"],
					}
				]
			)
		}
		by_name = {c.spec.name: c for c in resolve_tool_pool(sp, task_cfg)}
		self.assertEqual(by_name["task_a"].spec.parameters, {"instruction": {"type": "string"}})
		self.assertEqual(by_name["task_a"].spec.required, ["instruction"])
		# A shape with no declared arguments stays a no-argument tool.
		self.assertEqual(by_name["task_b"].spec.parameters, {})
		self.assertEqual(by_name["task_b"].spec.required, [])

	def test_malformed_tool_shapes_fall_back_to_no_arguments(self):
		sp = _adhoc_subworkflow()
		for broken in ("not json", "{}", None, 42):
			pool = resolve_tool_pool(sp, {"aiToolShapes": broken})
			self.assertTrue(all(c.spec.parameters == {} for c in pool))


class TestSelectorPoolCompileValidation(FrappeTestCase):
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
