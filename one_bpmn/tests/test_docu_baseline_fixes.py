# Copyright (c) 2026, one-fm and contributors
"""What the first Docu baseline run caught: a naming rule that repeats, a vague request designed, a ceiling no turn meets."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import docu_child_table_case_asks_for_a_new_doctype as child_table
from one_bpmn.one_bpmn.patches.v1_0 import docu_clarify_trace_ends_at_clarify as clarify_trace
from one_bpmn.one_bpmn.patches.v1_0 import docu_greeting_token_ceiling as ceiling
from one_bpmn.one_bpmn.patches.v1_0 import docu_naming_skill_braces_the_counter as naming_skill
from one_bpmn.one_bpmn.patches.v1_0.seed_docu_skills import SKILLS
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


class TestNamingSkill(FrappeTestCase):
	def test_the_seeded_skill_teaches_a_counter_the_validator_accepts(self):
		body = next(s["body"] for s in SKILLS if s["skill_name"] == naming_skill.SKILL)
		self.assertIn(naming_skill.NEW, body)
		self.assertTrue(validate_doctype_ir(_ir("format:INSP-{#####}"))["valid"])

	def test_the_live_skill_is_corrected_once(self):
		if not frappe.db.exists("AI Skill", naming_skill.SKILL):
			self.skipTest("the naming skill is not on this site")
		frappe.db.set_value("AI Skill", naming_skill.SKILL, "body", "# Naming\n" + naming_skill.OLD + "\nrest")
		naming_skill.execute()
		naming_skill.execute()
		body = frappe.db.get_value("AI Skill", naming_skill.SKILL, "body")
		self.assertEqual(body, "# Naming\n" + naming_skill.NEW + "\nrest")


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

	def test_only_a_clarify_case_stops_expecting_finalize(self):
		suite = frappe.get_doc(
			{
				"doctype": "AI Eval Suite",
				"title": "_Test Docu clarify trace",
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

		def case(title, tools):
			return frappe.get_doc(
				{
					"doctype": "AI Eval Case",
					"title": title,
					"suite": suite.name,
					"input_user_prompt": "x",
					"expected_tool_calls": [
						{"call_order": i, "tool_name": t} for i, t in enumerate(tools, start=1)
					],
				}
			).insert(ignore_permissions=True, ignore_links=True).name

		vague = case("_Test vague", ["classify_intent", "clarify", "finalize"])
		design = case("_Test design", ["classify_intent", "write_schema", "review_schema", "finalize"])
		clarify_trace.execute()

		def tools(name):
			return frappe.get_all(
				"AI Eval Expected Tool Call", filters={"parent": name}, pluck="tool_name", order_by="call_order"
			)

		self.assertEqual(tools(vague), ["classify_intent", "clarify"])
		self.assertEqual(tools(design), ["classify_intent", "write_schema", "review_schema", "finalize"])


class TestChildTableCasePrompt(FrappeTestCase):
	def test_the_old_prompt_becomes_the_seeded_one_and_other_cases_stay(self):
		def case(title, prompt):
			return frappe.get_doc(
				{"doctype": "AI Eval Case", "title": title, "input_user_prompt": prompt}
			).insert(ignore_permissions=True, ignore_links=True).name

		target = case(child_table.TITLE, child_table.OLD_PROMPT)
		other = case("_Test other", child_table.OLD_PROMPT)
		child_table.execute()
		self.assertTrue(frappe.db.get_value("AI Eval Case", target, "input_user_prompt").startswith("Create a new DocType"))
		self.assertEqual(frappe.db.get_value("AI Eval Case", other, "input_user_prompt"), child_table.OLD_PROMPT)
