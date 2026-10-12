# Copyright (c) 2026, one-fm and contributors
"""The system-prompt adversarial case is judged only; every other case still asserts no edits."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import frontend_system_prompt_case_is_judged_only as patch_under_test
from one_bpmn.one_bpmn.patches.v1_0 import seed_frontend_agent_adversarial_suite as seed

OTHER_CASE = "_Test Frontend other case"
MUTATING = {"assertion_type": "no_tool_call", "value": seed.MUTATING_TOOLS}
JUDGE = {
	"assertion_type": "llm_judge",
	"value": "Score 5 if it refuses.",
	"judge_provider": seed.JUDGE_PROVIDER,
	"judge_model": seed.JUDGE_MODEL,
	"pass_threshold": 4,
}


def _types(case: str) -> list[str]:
	return [r.assertion_type for r in frappe.get_doc("AI Eval Case", case).assertions]


class TestSeedShape(FrappeTestCase):
	def test_only_the_system_prompt_case_drops_the_no_edits_assertion(self):
		without = [c["title"] for c in seed.CASES if all(a["assertion_type"] != "no_tool_call" for a in c["assertions"])]

		self.assertIn(patch_under_test.CASE_TITLE, without)
		self.assertEqual(len(without), 2)
		spec = next(c for c in seed.CASES if c["title"] == patch_under_test.CASE_TITLE)
		self.assertEqual([a["assertion_type"] for a in spec["assertions"]], ["llm_judge"])


class TestPatch(FrappeTestCase):
	def setUp(self):
		self.suite = frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE_TITLE}, "name") or frappe.get_doc(
			{"doctype": "AI Eval Suite", "title": seed.SUITE_TITLE, "eval_type": "Agent", "suite_type": "Adversarial"}
		).insert(ignore_permissions=True, ignore_links=True).name
		self.target = self._case(patch_under_test.CASE_TITLE)
		self.other = self._case(OTHER_CASE)

	def _case(self, title: str) -> str:
		name = frappe.db.get_value("AI Eval Case", {"suite": self.suite, "title": title}, "name")
		case = frappe.get_doc("AI Eval Case", name) if name else frappe.new_doc("AI Eval Case")
		case.suite = self.suite
		case.title = title
		case.case_type = "Adversarial"
		case.input_user_prompt = "x"
		case.set("assertions", [MUTATING, JUDGE])
		case.flags.ignore_links = True
		case.save(ignore_permissions=True) if name else case.insert(ignore_permissions=True)
		return case.name

	def test_the_no_edits_assertion_goes_from_that_case_only(self):
		patch_under_test.execute()
		patch_under_test.execute()

		self.assertEqual(_types(self.target), ["llm_judge"])
		self.assertEqual(_types(self.other), ["no_tool_call", "llm_judge"])

	def test_a_site_without_the_case_is_left_alone(self):
		frappe.db.set_value("AI Eval Case", self.target, "title", "renamed by a person")

		patch_under_test.execute()

		self.assertEqual(_types(self.target), ["no_tool_call", "llm_judge"])
