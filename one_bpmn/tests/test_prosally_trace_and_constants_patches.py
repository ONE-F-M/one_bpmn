# Copyright (c) 2026, one-fm and contributors
"""ProsAlly Baseline stops expecting finalize; stage scripts move from hard-coded skill names to constants."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import prosally_baseline_trace_ends_at_stage_tool as trace_patch
from one_bpmn.one_bpmn.patches.v1_0 import prosally_stage_skills as stage
from one_bpmn.one_bpmn.patches.v1_0 import prosally_stage_skills_read_constants as constants_patch
from one_bpmn.one_bpmn.patches.v1_0 import seed_prosally_baseline_suite as seed

PROSALLY = frappe.db.get_value("AI Agent Configuration", {"agent_id": stage.AGENT_ID}, "name")


class TestProsAllyBaselineTrace(FrappeTestCase):
	def test_the_seeded_trace_ends_at_generate_process(self):
		tools = [c["tool_name"] for c in seed.GENERATE_TRACE]
		self.assertEqual(tools, ["classify_intent", "generate_process"])

	def test_finalize_is_removed_from_every_baseline_case_and_the_other_calls_stay(self):
		suite = frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE_TITLE}, "name")
		if not suite:
			suite = frappe.get_doc(
				{
					"doctype": "AI Eval Suite",
					"title": seed.SUITE_TITLE,
					"eval_type": "Agent",
					"suite_type": "Baseline",
				}
			).insert(ignore_permissions=True, ignore_links=True).name
		case = frappe.get_doc(
			{
				"doctype": "AI Eval Case",
				"title": "zz trace case",
				"suite": suite,
				"input_user_prompt": "Yes, build it.",
				"expected_tool_calls": [
					{"call_order": 1, "tool_name": "classify_intent"},
					{"call_order": 2, "tool_name": "generate_process"},
					{"call_order": 3, "tool_name": "finalize"},
				],
			}
		).insert(ignore_permissions=True, ignore_links=True)

		trace_patch.execute()
		trace_patch.execute()

		tools = frappe.get_all(
			"AI Eval Expected Tool Call",
			filters={"parent": case.name},
			pluck="tool_name",
			order_by="call_order asc",
		)
		self.assertEqual(tools, ["classify_intent", "generate_process"])


class TestProsAllyStageSkillsReadConstants(FrappeTestCase):
	def test_the_hard_coded_line_becomes_the_constants_line_once(self):
		if not PROSALLY:
			self.skipTest("ProsAlly is not on this site")
		scripts = {}
		for sub_agent_id, pattern in stage.STAGES.items():
			name = frappe.db.get_value("Server Script", {"name": ["like", pattern]}, "name")
			if not name:
				self.skipTest("ProsAlly's stage scripts are not on this site")
			anchor = f'_system = (_subs.get("{sub_agent_id}") or {{}}).get("prompt") or ""'
			frappe.db.set_value(
				"Server Script", name, "script", f"{anchor}\n{constants_patch.HARD_CODED_LINE}\nresult = {{}}"
			)
			scripts[sub_agent_id] = name

		constants_patch.execute()
		constants_patch.execute()

		for sub_agent_id, name in scripts.items():
			script = frappe.db.get_value("Server Script", name, "script")
			self.assertNotIn(constants_patch.HARD_CODED_LINE, script)
			self.assertEqual(script.count(stage.skill_line(stage.STAGE_CONSTANTS[sub_agent_id])), 1)
		for constant in stage.STAGE_CONSTANTS.values():
			values = frappe.get_all(
				"AI Agent Constant",
				filters={"parent": PROSALLY, "constant_name": constant},
				pluck="constant_value",
			)
			self.assertEqual(values, [stage.STAGE_SKILLS])
