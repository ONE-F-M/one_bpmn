# Copyright (c) 2026, one-fm and contributors
"""What the first Docu baseline run caught: a naming rule that repeats, a vague request designed, a ceiling no turn meets."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import docu_greeting_token_ceiling as ceiling
from one_bpmn.one_bpmn.patches.v1_0 import docu_vague_request_disambiguates as vague
from one_bpmn.one_bpmn.patches.v1_0.seed_docu_agent_config import _INLINE_SUB_PROMPTS
from one_bpmn.security.doctype_validator import validate_doctype_ir


def _ir(autoname):
	return {
		"doctype_name": "Safety Incident",
		"module": "ONE BPMN",
		"autoname": autoname,
		"fields": [{"fieldname": "location", "label": "Location", "fieldtype": "Data"}],
	}


class TestNamingRule(FrappeTestCase):
	def test_a_counter_outside_the_braces_of_a_format_rule_is_refused(self):
		result = validate_doctype_ir(_ir("format:INC-.#####"))
		self.assertFalse(result["valid"])
		self.assertIn("outside braces", " ".join(result["violations"]))

	def test_a_braced_counter_and_a_naming_series_both_pass(self):
		for autoname in ("format:INC-{#####}", "INC-.#####", "format:SC-{subcontractor_name}-{#####}", ""):
			self.assertTrue(validate_doctype_ir(_ir(autoname))["valid"], autoname)


class TestPatches(FrappeTestCase):
	def setUp(self):
		self.agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": vague.AGENT_ID}, "name")
		if not self.agent:
			self.skipTest("Docu is not on this site")

	def test_the_seeded_classifier_carries_the_rule(self):
		self.assertIn(vague.RULE, _INLINE_SUB_PROMPTS["intent_classifier"])

	def test_the_vague_request_rule_is_added_once_after_the_anchor(self):
		row = frappe.db.get_value(
			"AI Agent Sub Prompt", {"parent": self.agent, "sub_agent_id": "intent_classifier"}, "name"
		)
		frappe.db.set_value("AI Agent Sub Prompt", row, "prompt_text", "rules\\n" + vague.ANCHOR + "rest")
		vague.execute()
		vague.execute()
		text = frappe.db.get_value("AI Agent Sub Prompt", row, "prompt_text")
		self.assertEqual(text, "rules\\n" + vague.ANCHOR + vague.RULE + "rest")

	def test_the_greeting_ceiling_rises_and_other_ceilings_stay(self):
		suite = frappe.get_doc(
			{
				"doctype": "AI Eval Suite",
				"title": "_Test Docu ceiling",
				"eval_type": "Agent",
				"suite_type": "Baseline",
				"agent_configuration": self.agent,
			}
		).insert(ignore_permissions=True, ignore_links=True)
		for other in frappe.get_all(
			"AI Eval Suite",
			filters={"agent_configuration": self.agent, "suite_type": "Baseline", "name": ["!=", suite.name]},
			pluck="name",
		):
			frappe.db.set_value("AI Eval Suite", other, "suite_type", "Adversarial")
		case = frappe.get_doc(
			{
				"doctype": "AI Eval Case",
				"title": "_Test greeting ceiling",
				"suite": suite.name,
				"input_user_prompt": "hi",
				"assertions": [
					{"assertion_type": "max_tokens", "value": "500"},
					{"assertion_type": "max_tokens", "value": "30000"},
				],
			}
		).insert(ignore_permissions=True, ignore_links=True)
		ceiling.execute()
		values = frappe.get_all("AI Eval Assertion", filters={"parent": case.name}, pluck="value", order_by="idx")
		self.assertEqual(values, ["2500", "30000"])
