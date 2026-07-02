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
