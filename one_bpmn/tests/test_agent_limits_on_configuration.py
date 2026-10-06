# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Timeout, retries, tool calls and top P are set on the AI Agent Configuration and reach the map."""

import json
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.agent_config_resolver import (
	resolve_dispatch_overrides,
	shape_config_drift,
	sync_shapes_to_config,
	update_agent_config_from_shape,
)
from one_bpmn.one_bpmn.patches.v1_0 import agent_limits_move_to_the_configuration as p

CONFIG = "ZZ Limits Test Agent"
MODEL = "ZZ Limits Test Map"
LIMITS = ("timeout_seconds", "max_retries", "max_tool_calls", "top_p")

XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="Defs_1">
  <bpmn:process id="Limits_Process" isExecutable="true">
    <bpmn:serviceTask id="Agent_1" spiffworkflow:serviceType="ai_agent" spiffworkflow:aiAgentConfig="ZZ Limits Test Agent" spiffworkflow:aiTimeout="300" spiffworkflow:aiMaxRetries="1" spiffworkflow:aiMaxToolCalls="30" spiffworkflow:aiTopP="1" />
  </bpmn:process>
</bpmn:definitions>"""

SHAPE = {
	"serviceType": "ai_agent",
	"aiAgentConfig": CONFIG,
	"aiTimeout": "300",
	"aiMaxRetries": "1",
	"aiMaxToolCalls": "30",
	"aiTopP": "1",
}


def _spec(*shapes: dict) -> str:
	return json.dumps({"service_task_extensions": {f"Agent_{i}": s for i, s in enumerate(shapes, 1)}})


def _limits() -> dict:
	return frappe.db.get_value("AI Agent Configuration", CONFIG, list(LIMITS), as_dict=True)


class TestAgentLimitsOnConfiguration(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		provider = frappe.db.get_value("AI Provider", {}, "name")
		if not provider:
			raise unittest.SkipTest("no AI Provider on this site")
		frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": CONFIG,
				"agent_id": "zz_limits_test_agent",
				"agent_framework": "Direct API",
				"agent_type": "Background",
				"enabled": 1,
				"ai_provider": provider,
				"system_prompt": "Do the work.",
			}
		).insert(ignore_permissions=True)
		model = frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"title": MODEL,
				"process_id": "Limits_Process",
				"version": 1,
				"is_active": 1,
				"bpmn_xml": XML,
				"serialized_spec": _spec(SHAPE),
			}
		)
		model.flags.ignore_mandatory = True
		model.flags.skip_editability_check = True
		model.flags.skip_script_security_check = True
		model.insert(ignore_permissions=True, ignore_mandatory=True)
		cls.model_name = model.name

	def setUp(self):
		super().setUp()
		frappe.db.set_value(
			"AI Agent Configuration", CONFIG, dict.fromkeys(LIMITS, 0), update_modified=False
		)
		frappe.db.set_value(
			"BPMN Process Model",
			self.model_name,
			{"bpmn_xml": XML, "serialized_spec": _spec(SHAPE)},
			update_modified=False,
		)

	def _set_limits(self, **values):
		frappe.db.set_value("AI Agent Configuration", CONFIG, values, update_modified=False)

	def test_limits_on_the_configuration_override_the_shape_at_dispatch(self):
		self._set_limits(timeout_seconds=45, max_retries=3, max_tool_calls=7, top_p=0.5)

		overrides = resolve_dispatch_overrides(CONFIG)

		self.assertEqual(overrides["aiTimeout"], 45)
		self.assertEqual(overrides["aiMaxRetries"], 3)
		self.assertEqual(overrides["aiMaxToolCalls"], 7)
		self.assertEqual(overrides["aiTopP"], 0.5)

	def test_a_zero_leaves_the_shape_in_charge(self):
		overrides = resolve_dispatch_overrides(CONFIG)

		for attribute in ("aiTimeout", "aiMaxRetries", "aiMaxToolCalls", "aiTopP"):
			self.assertNotIn(attribute, overrides)

	def test_a_limit_that_differs_from_the_configuration_is_drift(self):
		self._set_limits(timeout_seconds=45, top_p=0.5)
		live = {k: v for k, v in resolve_dispatch_overrides(CONFIG).items() if k in ("aiTimeout", "aiTopP")}

		drift = {d["field"]: d for d in shape_config_drift(SHAPE, live)}
		self.assertEqual(set(drift), {"aiTimeout", "aiTopP"})
		self.assertEqual(drift["aiTimeout"]["live"], 45)
		self.assertEqual(shape_config_drift({"aiTimeout": "45", "aiTopP": "0.50"}, live), [])

	def test_sync_writes_the_limits_onto_the_shape_and_the_spec(self):
		self._set_limits(timeout_seconds=45, max_retries=3, max_tool_calls=7, top_p=0.5)

		self.assertEqual(sync_shapes_to_config(CONFIG), [self.model_name])
		xml, spec = frappe.db.get_value("BPMN Process Model", self.model_name, ["bpmn_xml", "serialized_spec"])
		for attribute, value in (("aiTimeout", "45"), ("aiMaxRetries", "3"), ("aiMaxToolCalls", "7"), ("aiTopP", "0.5")):
			self.assertIn(f'spiffworkflow:{attribute}="{value}"', xml)
			self.assertEqual(json.loads(spec)["service_task_extensions"]["Agent_1"][attribute], value)

	def test_saving_a_new_timeout_reaches_the_map(self):
		config = frappe.get_doc("AI Agent Configuration", CONFIG)
		config.timeout_seconds = 45
		config.save(ignore_permissions=True)

		self.assertIn('spiffworkflow:aiTimeout="45"', frappe.db.get_value("BPMN Process Model", self.model_name, "bpmn_xml"))

	def test_the_editor_writes_limits_back_to_the_configuration(self):
		update_agent_config_from_shape(
			CONFIG, {"aiTimeout": "60", "aiMaxRetries": "4", "aiMaxToolCalls": "9", "aiTopP": "0.8"}
		)

		self.assertEqual(dict(_limits()), {"timeout_seconds": 60, "max_retries": 4, "max_tool_calls": 9, "top_p": 0.8})

	def test_a_top_p_above_one_is_refused(self):
		config = frappe.get_doc("AI Agent Configuration", CONFIG)
		config.top_p = 1.5

		with self.assertRaises(frappe.ValidationError):
			config.save(ignore_permissions=True)

	def test_the_patch_fills_a_blank_record_from_its_shape(self):
		p.execute()

		self.assertEqual(dict(_limits()), {"timeout_seconds": 300, "max_retries": 1, "max_tool_calls": 30, "top_p": 1.0})

	def test_the_patch_keeps_a_value_already_on_the_record(self):
		self._set_limits(timeout_seconds=45)
		p.execute()

		self.assertEqual(_limits().timeout_seconds, 45)

	def test_the_patch_finds_the_record_when_the_shape_spells_it_in_another_case(self):
		frappe.db.set_value(
			"BPMN Process Model",
			self.model_name,
			"serialized_spec",
			_spec({**SHAPE, "aiAgentConfig": CONFIG.lower()}),
			update_modified=False,
		)
		p.execute()

		self.assertEqual(_limits().timeout_seconds, 300)

	def test_shapes_that_disagree_leave_the_record_blank(self):
		frappe.db.set_value(
			"BPMN Process Model",
			self.model_name,
			"serialized_spec",
			_spec(SHAPE, {**SHAPE, "aiTimeout": "120"}),
			update_modified=False,
		)
		p.execute()

		limits = _limits()
		self.assertEqual(limits.timeout_seconds, 0)
		self.assertEqual(limits.max_retries, 1)
