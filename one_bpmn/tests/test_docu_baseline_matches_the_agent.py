# Copyright (c) 2026, one-fm and contributors
"""Docu's baseline cases match what Docu does now: the classifier rule, the field-property stage, the ceiling."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import docu_baseline_matches_the_current_agent as p
from one_bpmn.one_bpmn.patches.v1_0 import docu_property_case_ends_at_the_stage as ends_at_the_stage
from one_bpmn.one_bpmn.patches.v1_0 import seed_docu_baseline_cases as seed
from one_bpmn.one_bpmn.patches.v1_0.seed_docu_agent_config import _INLINE_SUB_PROMPTS

NUMBERING, DISPLAY = p.REFRESHED_CASES
UNTOUCHED = "A question that is not about designing a DocType designs nothing"
STUB_CLASSIFIER = "Classify.\n" + p.CLASSIFIER_ANCHOR + "- PARTS: list the parts.\n"


class TestDocuBaselineMatchesTheAgent(FrappeTestCase):
	def setUp(self):
		self.agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": seed.AGENT_ID}, "name")
		model = frappe.db.get_value("BPMN Process Model", {}, "name")
		if not self.agent or not model:
			self.skipTest("Docu or a process model is not on this site")
		self.row = frappe.db.get_value(
			"AI Agent Sub Prompt", {"parent": self.agent, "sub_agent_id": "intent_classifier"}, "name"
		)
		if not self.row:
			self.skipTest("Docu has no intent_classifier sub-prompt on this site")
		# Creating a DocType commits; TestTheProbeDoctype covers it, so these tests leave it out.
		patcher = patch.object(seed, "ensure_probe_doctype")
		patcher.start()
		self.addCleanup(patcher.stop)
		frappe.db.set_value("AI Agent Configuration", self.agent, "process_model", model)
		frappe.db.set_value("AI Agent Sub Prompt", self.row, "prompt_text", STUB_CLASSIFIER)
		self.suite = frappe.db.get_value(
			"AI Eval Suite", {"agent_configuration": self.agent, "suite_type": "Baseline"}, "name"
		) or frappe.get_doc(
			{
				"doctype": "AI Eval Suite",
				"title": "_Test Docu baseline",
				"eval_type": "Agent",
				"suite_type": "Baseline",
				"agent_configuration": self.agent,
			}
		).insert(ignore_permissions=True, ignore_links=True).name
		seed.execute()

	def _case(self, title: str):
		name = frappe.db.get_value("AI Eval Case", {"suite": self.suite, "title": title}, "name")
		return frappe.get_doc("AI Eval Case", name)

	def _prompt(self) -> str:
		return frappe.db.get_value("AI Agent Sub Prompt", self.row, "prompt_text")

	def test_the_classifier_gains_the_rule_once(self):
		p.execute()
		p.execute()

		self.assertEqual(self._prompt().count(p.CLASSIFIER_RULE), 1)
		self.assertTrue(self._prompt().startswith("Classify.\n" + p.CLASSIFIER_ANCHOR + p.CLASSIFIER_RULE))

	def test_a_classifier_without_the_anchor_is_left_as_it_is(self):
		frappe.db.set_value("AI Agent Sub Prompt", self.row, "prompt_text", "Classify.")
		p.execute()

		self.assertEqual(self._prompt(), "Classify.")

	def test_the_seeded_classifier_carries_the_anchor_and_the_rule(self):
		seeded = _INLINE_SUB_PROMPTS["intent_classifier"]

		self.assertIn(p.CLASSIFIER_ANCHOR + p.CLASSIFIER_RULE, seeded)

	def test_the_display_case_expects_the_field_property_stage_on_its_own_doctype(self):
		spec = next(c for c in seed.CASES if c["title"] == DISPLAY)

		self.assertEqual(spec["context"], seed.ON_PROBE)
		self.assertEqual([c["tool_name"] for c in spec["trace"]], ["classify_intent", "edit_field_property"])

	def test_the_patch_refreshes_those_two_cases_and_no_other(self):
		numbering = self._case(NUMBERING)
		for row in numbering.assertions:
			if row.assertion_type == "max_tokens":
				row.value = "30000"
		numbering.save(ignore_permissions=True)
		display = self._case(DISPLAY)
		display.input_context = json.dumps(seed.ON_TODO)
		display.save(ignore_permissions=True)
		frappe.db.set_value("AI Eval Case", self._case(UNTOUCHED).name, "input_user_prompt", "edited by a person")

		p.execute()

		ceiling = [r.value for r in self._case(NUMBERING).assertions if r.assertion_type == "max_tokens"]
		self.assertEqual(ceiling, ["45000"])
		refreshed = self._case(DISPLAY)
		self.assertEqual(json.loads(refreshed.input_context), seed.ON_PROBE)
		self.assertEqual([r.tool_name for r in refreshed.expected_tool_calls], ["classify_intent", "edit_field_property"])
		self.assertEqual(self._case(UNTOUCHED).input_user_prompt, "edited by a person")


	def test_the_property_case_stops_expecting_a_finalize_and_no_other_case_changes(self):
		display = self._case(DISPLAY)
		display.set(
			"expected_tool_calls",
			[seed._call(1, "classify_intent"), seed._call(2, "edit_field_property"), seed._call(3, "finalize")],
		)
		display.save(ignore_permissions=True)
		frappe.db.set_value("AI Eval Case", self._case(UNTOUCHED).name, "input_user_prompt", "edited by a person")

		ends_at_the_stage.execute()
		ends_at_the_stage.execute()

		tools = [r.tool_name for r in self._case(DISPLAY).expected_tool_calls]
		self.assertEqual(tools, ["classify_intent", "edit_field_property"])
		self.assertEqual(self._case(UNTOUCHED).input_user_prompt, "edited by a person")


class TestTheProbeDoctype(FrappeTestCase):
	def test_it_has_the_fields_the_display_case_names(self):
		existed = frappe.db.exists("DocType", seed.PROBE)
		try:
			seed.ensure_probe_doctype()
			seed.ensure_probe_doctype()
			fields = {f.fieldname: f.label for f in frappe.get_meta(seed.PROBE).fields}
		finally:
			if not existed:
				frappe.delete_doc("DocType", seed.PROBE, force=True, ignore_permissions=True)
				frappe.db.commit()

		self.assertEqual(fields, {"status": "Status", "assigned_by": "Assigned By"})
