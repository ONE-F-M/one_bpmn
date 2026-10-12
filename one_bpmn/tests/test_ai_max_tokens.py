"""aiMaxTokens on an AI Agent Task: refused at compile when set but not above 0, and cleared from existing maps."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import compilation as comp
from one_bpmn.one_bpmn.patches.v1_0 import drop_non_positive_ai_max_tokens as patch

MAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="defs">
  <bpmn:process id="p" isExecutable="true">
    <bpmn:serviceTask id="zero" name="Zero" spiffworkflow:serviceType="ai_agent" spiffworkflow:aiMaxTokens="0" spiffworkflow:aiTimeout="300" />
    <bpmn:serviceTask id="blank" name="Blank" spiffworkflow:serviceType="ai_agent" spiffworkflow:aiMaxTokens="" />
    <bpmn:serviceTask id="negative" name="Negative" spiffworkflow:serviceType="ai_agent" spiffworkflow:aiMaxTokens="-5" />
    <bpmn:serviceTask id="set" name="Set" spiffworkflow:serviceType="ai_agent" spiffworkflow:aiMaxTokens="4096" />
  </bpmn:process>
</bpmn:definitions>
"""


def _task(max_tokens=None, service_type="ai_agent"):
	cfg = {"serviceType": service_type}
	if max_tokens is not None:
		cfg["aiMaxTokens"] = max_tokens
	return {"agent_task": cfg}


class TestCompileRefusesAMaxTokensBelowOne(FrappeTestCase):
	def test_zero_blank_negative_and_non_numbers_are_refused_and_name_the_shape(self):
		for value in ("0", "", "-5", "abc", "1.5", "  "):
			with self.subTest(value=value):
				with self.assertRaises(frappe.ValidationError) as ctx:
					comp._validate_ai_max_tokens(_task(value))
				self.assertIn("Max tokens must be a positive number", str(ctx.exception))
				self.assertIn("agent_task", str(ctx.exception))

	def test_a_positive_value_or_no_value_passes(self):
		comp._validate_ai_max_tokens(_task("4096"))
		comp._validate_ai_max_tokens(_task(4096))
		comp._validate_ai_max_tokens(_task())

	def test_only_ai_agent_tasks_are_checked(self):
		comp._validate_ai_max_tokens(_task("0", service_type="script"))

	def test_the_check_runs_on_the_parsed_map(self):
		with self.assertRaises(frappe.ValidationError):
			comp._validate_ai_max_tokens(comp._extract_service_task_config(MAP_XML))


class TestExistingMapsAreCleared(FrappeTestCase):
	def test_only_non_positive_values_are_removed(self):
		cleaned, removed = patch.strip_non_positive_max_tokens(MAP_XML)
		self.assertEqual(removed, 3)
		self.assertIn('spiffworkflow:aiMaxTokens="4096"', cleaned)
		self.assertIn('spiffworkflow:aiTimeout="300"', cleaned)
		for shape in ('id="zero"', 'id="blank"', 'id="negative"'):
			self.assertIn(shape, cleaned)
		self.assertEqual(cleaned.count("aiMaxTokens"), 1)

	def test_a_cleaned_map_compiles_past_the_check(self):
		cleaned, _ = patch.strip_non_positive_max_tokens(MAP_XML)
		comp._validate_ai_max_tokens(comp._extract_service_task_config(cleaned))

	def test_a_second_pass_changes_nothing(self):
		cleaned, _ = patch.strip_non_positive_max_tokens(MAP_XML)
		self.assertEqual(patch.strip_non_positive_max_tokens(cleaned), (cleaned, 0))

	def test_the_patch_rewrites_stored_maps_and_leaves_is_active_alone(self):
		name = f"_Test Max Tokens {frappe.generate_hash(length=6)}"
		doc = frappe.new_doc("BPMN Process Model")
		doc.update(
			{
				"name": name,
				"title": name,
				"process_id": "p",
				"version": "1",
				"bpmn_xml": MAP_XML,
				"is_active": 0,
			}
		)
		doc.db_insert()

		patch.execute()

		stored = frappe.db.get_value("BPMN Process Model", name, ["bpmn_xml", "is_active"], as_dict=True)
		self.assertEqual(stored.bpmn_xml.count("aiMaxTokens"), 1)
		self.assertEqual(stored.is_active, 0)
