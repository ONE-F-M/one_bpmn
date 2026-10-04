# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A shape's prompt, model, temperature and max tokens against its linked AI Agent Configuration."""

import json
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.agent_config_resolver import (
	get_shape_drift,
	shape_config_drift,
	sync_shapes_to_config,
)
from one_bpmn.api.compilation import _check_shape_config_drift
from one_bpmn.commands.agent_drift import drift_lines

CONFIG = "ZZ Drift Test Agent"
MODEL = "ZZ Drift Test Map"
LIVE_PROMPT = "Route every request through the three-call procedure."

XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="Defs_1">
  <bpmn:process id="Drift_Process" isExecutable="true">
    <bpmn:serviceTask id="Agent_1" spiffworkflow:serviceType="ai_agent" spiffworkflow:aiAgentConfig="ZZ Drift Test Agent" spiffworkflow:aiSystemPrompt="Be a friendly persona." spiffworkflow:aiTemperature="0.7" spiffworkflow:aiMaxTokens="4096" />
    <bpmn:adHocSubProcess id="Tools_1">
      <bpmn:scriptTask id="Tool_1" spiffworkflow:aiAgentConfig="ZZ Drift Test Agent" />
    </bpmn:adHocSubProcess>
  </bpmn:process>
</bpmn:definitions>"""

STALE_EXTENSION = {
	"serviceType": "ai_agent",
	"aiAgentConfig": CONFIG,
	"aiSystemPrompt": "Be a friendly persona.",
	"aiTemperature": "0.7",
	"aiMaxTokens": "4096",
}


class TestShapeConfigDrift(FrappeTestCase):
	def test_numbers_compare_by_value_and_prompts_ignore_edge_whitespace(self):
		live = {"aiTemperature": 0.3, "aiMaxTokens": 4096, "aiSystemPrompt": "Hello"}
		shape = {"aiTemperature": "0.30", "aiMaxTokens": "4096", "aiSystemPrompt": "Hello\n"}
		self.assertEqual(shape_config_drift(shape, live), [])

	def test_differing_fields_name_the_live_value(self):
		live = {"aiTemperature": 0.3, "aiModel": "claude-sonnet-5"}
		shape = {"aiTemperature": "0.7", "aiModel": "claude-haiku-4-5-20251001"}
		drift = {d["field"]: d for d in shape_config_drift(shape, live)}
		self.assertEqual(set(drift), {"aiTemperature", "aiModel"})
		self.assertEqual(drift["aiModel"]["live"], "claude-sonnet-5")
		self.assertEqual(drift["aiModel"]["shape"], "claude-haiku-4-5-20251001")

	def test_a_field_the_configuration_leaves_blank_is_not_drift(self):
		self.assertEqual(shape_config_drift({"aiModel": "claude-haiku-4-5-20251001"}, {}), [])


class TestDriftAgainstAConfiguration(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		provider = frappe.db.get_value("AI Provider", {}, "name")
		if not provider:
			raise unittest.SkipTest("no AI Provider on this site")
		frappe.get_doc({
			"doctype": "AI Agent Configuration",
			"agent_name": CONFIG,
			"agent_id": "zz_drift_test_agent",
			"agent_framework": "Direct API",
			"agent_type": "Background",
			"enabled": 1,
			"ai_provider": provider,
			"system_prompt": LIVE_PROMPT,
			"temperature": 0.3,
			"max_tokens": 4096,
		}).insert(ignore_permissions=True)
		model = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"title": MODEL,
			"process_id": "Drift_Process",
			"version": 1,
			"is_active": 1,
			"bpmn_xml": XML,
			"serialized_spec": json.dumps({"service_task_extensions": {"Agent_1": dict(STALE_EXTENSION)}}),
		})
		model.flags.ignore_mandatory = True
		model.flags.skip_editability_check = True
		model.flags.skip_script_security_check = True
		model.insert(ignore_permissions=True, ignore_mandatory=True)
		cls.model_name = model.name

	def test_deploy_warning_names_what_runs(self):
		warnings = _check_shape_config_drift({"Agent_1": dict(STALE_EXTENSION)})
		self.assertEqual(len(warnings), 1)
		detail = warnings[0]["detail"]
		self.assertIn("Agent_1", detail)
		self.assertIn("Temperature 0.3 (the shape says 0.7)", detail)
		self.assertIn(f"{len(LIVE_PROMPT)} characters", detail)
		self.assertNotIn("Max Tokens", detail)

	def setUp(self):
		super().setUp()
		frappe.db.set_value(
			"BPMN Process Model", self.model_name,
			{"bpmn_xml": XML, "serialized_spec": json.dumps({"service_task_extensions": {"Agent_1": dict(STALE_EXTENSION)}})},
			update_modified=False,
		)
		frappe.db.set_value(
			"AI Agent Configuration", CONFIG, {"system_prompt": LIVE_PROMPT, "temperature": 0.3}, update_modified=False
		)

	def test_bench_command_lists_the_active_map(self):
		self.assertTrue(any(line.startswith(f"{self.model_name}: 'Agent_1'") for line in drift_lines()))

	def test_sync_writes_live_values_onto_the_shape_and_the_spec(self):
		self.assertEqual(sync_shapes_to_config(CONFIG), [self.model_name])
		xml, spec = frappe.db.get_value("BPMN Process Model", self.model_name, ["bpmn_xml", "serialized_spec"])

		self.assertTrue(xml.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
		self.assertIn("<bpmn:serviceTask", xml)
		self.assertIn(f'spiffworkflow:aiSystemPrompt="{LIVE_PROMPT}"', xml)
		self.assertIn('spiffworkflow:aiTemperature="0.3"', xml)
		self.assertIn('<bpmn:scriptTask id="Tool_1" spiffworkflow:aiAgentConfig="ZZ Drift Test Agent"/>', xml)
		extension = json.loads(spec)["service_task_extensions"]["Agent_1"]
		self.assertEqual(extension["aiSystemPrompt"], LIVE_PROMPT)
		self.assertEqual(extension["aiTemperature"], "0.3")
		self.assertEqual(sync_shapes_to_config(CONFIG), [])

	def test_saving_a_new_temperature_reaches_the_map(self):
		sync_shapes_to_config(CONFIG)
		config = frappe.get_doc("AI Agent Configuration", CONFIG)
		config.temperature = 0.5
		config.save(ignore_permissions=True)
		xml = frappe.db.get_value("BPMN Process Model", self.model_name, "bpmn_xml")
		self.assertIn('spiffworkflow:aiTemperature="0.5"', xml)

	def test_panel_endpoint_returns_per_field_drift(self):
		drift = get_shape_drift(CONFIG, json.dumps({"aiTemperature": "0.7", "aiMaxTokens": "4096"}))
		self.assertEqual([d["field"] for d in drift], ["aiSystemPrompt", "aiTemperature"])

	def test_panel_endpoint_refuses_a_user_without_read(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				get_shape_drift(CONFIG, "{}")
		finally:
			frappe.set_user("Administrator")
