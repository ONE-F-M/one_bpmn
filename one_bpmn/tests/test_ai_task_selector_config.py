# Copyright (c) 2026, one-fm and contributors
# WI-001351 (2-01): ai_task_selector service task type and task_cfg schema.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import (
	_extract_adhoc_selector_config,
	_lint_ai_provider_config,
)

SELECTOR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs_Selector" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_Selector" isExecutable="true">
    <bpmn:adHocSubProcess id="AdhocSub_1" name="Selector"
        spiffworkflow:serviceType="ai_task_selector"
        spiffworkflow:aiProvider="{provider}"
        spiffworkflow:aiModel="gpt-test"
        spiffworkflow:aiSystemPrompt="You choose the next task."
        spiffworkflow:aiUserPrompt="Pick one."{extra}>
      <bpmn:task id="task_a" name="Task A" />
    </bpmn:adHocSubProcess>
  </bpmn:process>
</bpmn:definitions>
"""


def _xml(provider="", extra=""):
	return SELECTOR_XML.replace("{provider}", provider).replace("{extra}", extra)


class TestAiTaskSelectorConfig(FrappeTestCase):
	# ── Scenario 2: attributes extracted from the subprocess element ──

	def test_extracts_selector_attributes_from_adhoc_element(self):
		config = _extract_adhoc_selector_config(_xml(provider="My Provider"))
		self.assertIn("AdhocSub_1", config)
		cfg = config["AdhocSub_1"]
		self.assertEqual(cfg["serviceType"], "ai_task_selector")
		self.assertEqual(cfg["aiProvider"], "My Provider")
		self.assertEqual(cfg["aiModel"], "gpt-test")
		self.assertEqual(cfg["aiSystemPrompt"], "You choose the next task.")
		self.assertEqual(cfg["aiUserPrompt"], "Pick one.")

	# ── Scenario 3: aiToolSources defaults to "both" ──

	def test_tool_sources_defaults_to_both(self):
		config = _extract_adhoc_selector_config(_xml(provider="My Provider"))
		self.assertEqual(config["AdhocSub_1"]["aiToolSources"], "both")

	def test_explicit_tool_sources_preserved(self):
		xml = _xml(provider="My Provider", extra=' spiffworkflow:aiToolSources="diagram"')
		config = _extract_adhoc_selector_config(xml)
		self.assertEqual(config["AdhocSub_1"]["aiToolSources"], "diagram")

	def test_untagged_adhoc_subprocess_ignored(self):
		xml = _xml(provider="X").replace(
			' spiffworkflow:serviceType="ai_task_selector"', ""
		).replace("spiffworkflow:serviceType", "spiffworkflow:ignored")
		config = _extract_adhoc_selector_config(xml)
		self.assertEqual(config, {})

	# ── Scenario 4: compiler blocks bad configurations ──

	def test_missing_provider_blocks_save(self):
		extensions = _extract_adhoc_selector_config(_xml(provider=""))
		with self.assertRaises(frappe.ValidationError):
			_lint_ai_provider_config("", extensions)

	def test_unknown_provider_blocks_save(self):
		extensions = _extract_adhoc_selector_config(
			_xml(provider="Nonexistent Provider XYZ-404")
		)
		with self.assertRaises(frappe.ValidationError):
			_lint_ai_provider_config("", extensions)

	def test_raw_api_key_blocks_save(self):
		xml = _xml(provider="sk-live-abc123")
		extensions = _extract_adhoc_selector_config(xml)
		with self.assertRaises(frappe.ValidationError):
			_lint_ai_provider_config("", extensions)

	def test_valid_provider_passes_lint(self):
		provider = frappe.get_doc(
			{
				"doctype": "AI Provider",
				"provider_name": "Selector Lint Test Provider",
				"provider_type": "OpenAI",
				"api_key": "test-key-not-real",
				"enabled": 1,
			}
		)
		provider.insert(ignore_permissions=True)
		extensions = _extract_adhoc_selector_config(_xml(provider=provider.name))
		_lint_ai_provider_config("", extensions)  # must not raise


ADHOC_STRUCTURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    id="Defs_Structure" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_Structure" isExecutable="true">
    <bpmn:adHocSubProcess id="AdhocSub_S" name="Structure">
      {children}
    </bpmn:adHocSubProcess>
  </bpmn:process>
</bpmn:definitions>
"""


class TestAdhocStructureValidation(FrappeTestCase):
	"""_validate_adhoc_structure: BPMN-spec constraints on ad-hoc subprocesses
	(no start/end events inside, at least one activity)."""

	def _validate(self, children):
		from one_bpmn.api.compilation import _validate_adhoc_structure

		_validate_adhoc_structure(ADHOC_STRUCTURE_XML.replace("{children}", children))

	def test_activities_only_passes(self):
		self._validate('<bpmn:userTask id="t1" /><bpmn:scriptTask id="t2" />')

	def test_start_event_inside_adhoc_blocks_save(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._validate('<bpmn:startEvent id="ev1" /><bpmn:userTask id="t1" />')
		self.assertIn("Start Event", str(ctx.exception))

	def test_end_event_inside_adhoc_blocks_save(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._validate('<bpmn:userTask id="t1" /><bpmn:endEvent id="ev2" />')
		self.assertIn("End Event", str(ctx.exception))

	def test_empty_adhoc_blocks_save(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._validate("")
		self.assertIn("at least one activity", str(ctx.exception))

	def test_intermediate_event_allowed(self):
		# Only start/end events are prohibited by the spec; intermediate
		# events may appear inside an ad-hoc subprocess.
		self._validate('<bpmn:intermediateCatchEvent id="ic1" /><bpmn:userTask id="t1" />')

	def test_events_outside_adhoc_untouched(self):
		from one_bpmn.api.compilation import _validate_adhoc_structure

		xml = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    id="Defs_Outer" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_Outer" isExecutable="true">
    <bpmn:startEvent id="Start_1" />
    <bpmn:adHocSubProcess id="AdhocSub_O"><bpmn:userTask id="t1" /></bpmn:adHocSubProcess>
    <bpmn:endEvent id="End_1" />
  </bpmn:process>
</bpmn:definitions>
"""
		_validate_adhoc_structure(xml)  # must not raise
