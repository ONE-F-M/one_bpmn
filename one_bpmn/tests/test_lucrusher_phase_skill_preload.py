# Copyright (c) 2026, one-fm and contributors
"""Loading a phase skill before the turn: the shared skill helpers, the prompt and Baseline patches, and the skill_in_prompt assertion."""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.eval_runner import _evaluate_skill_in_prompt
from one_bpmn.api import skill_tools
from one_bpmn.one_bpmn.patches.v1_0 import lucrusher_phase_skill_preloaded as prompt_patch
from one_bpmn.one_bpmn.patches.v1_0 import lucrusher_skill_cases_check_the_prompt as cases_patch
from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_eval_suite import SUITE_TITLE
from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_skills import SYSTEM_PROMPT, TASKS_SKILL, TOPOLOGY_SKILL

AGENT = "lucrusher"


def _instance(conversation):
	return SimpleNamespace(
		name="_test-instance", context_doctype="Chat Conversation", context_docname=conversation
	)


def _loaded(conversation):
	return frappe.cache().get_value(skill_tools._skill_names_cache_key(conversation, AGENT)) or []


class TestActivateAndDeactivateSkill(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("AI Agent Configuration", AGENT):
			self.skipTest("the LuCrusher agent is not on this site")
		self.conversation = f"_test-preload-{frappe.generate_hash(length=6)}"
		self.addCleanup(skill_tools.clear_conversation_skills, self.conversation)
		logger = patch.object(skill_tools, "log_activation")
		self.log_activation = logger.start()
		self.addCleanup(logger.stop)

	def test_a_loaded_skill_reaches_the_cache_the_dispatcher_reads(self):
		body = skill_tools.activate_skill(TOPOLOGY_SKILL, AGENT, _instance(self.conversation))
		self.assertEqual(body, frappe.db.get_value("AI Skill", TOPOLOGY_SKILL, "body"))
		bodies = frappe.cache().get_value(skill_tools._skills_cache_key(self.conversation, AGENT))
		self.assertEqual(bodies, [body])
		self.assertEqual(_loaded(self.conversation), [TOPOLOGY_SKILL])

	def test_loading_it_again_logs_no_second_activation(self):
		instance = _instance(self.conversation)
		skill_tools.activate_skill(TOPOLOGY_SKILL, AGENT, instance)
		skill_tools.activate_skill(TOPOLOGY_SKILL, AGENT, instance)
		self.assertEqual(self.log_activation.call_count, 1)

	def test_unloading_drops_it_and_leaves_the_other(self):
		instance = _instance(self.conversation)
		skill_tools.activate_skill(TOPOLOGY_SKILL, AGENT, instance)
		skill_tools.activate_skill(TASKS_SKILL, AGENT, instance)
		self.assertEqual(
			skill_tools.deactivate_skill(TOPOLOGY_SKILL, AGENT, instance),
			f"Skill '{TOPOLOGY_SKILL}' unloaded.",
		)
		self.assertEqual(_loaded(self.conversation), [TASKS_SKILL])

	def test_a_skill_the_agent_may_not_use_is_refused(self):
		result = skill_tools.activate_skill(
			TOPOLOGY_SKILL, "_Test No Such Agent", _instance(self.conversation)
		)
		self.assertEqual(result, "Error: Skill is not enabled for this agent.")
		self.assertEqual(_loaded(self.conversation), [])


class TestSkillInPromptAssertion(FrappeTestCase):
	def setUp(self):
		self.body = frappe.db.get_value("AI Skill", TOPOLOGY_SKILL, "body")
		if not self.body:
			self.skipTest("the LuCrusher topology skill is not on this site")

	def test_passes_when_the_body_was_in_a_prompt(self):
		result = _evaluate_skill_in_prompt(
			TOPOLOGY_SKILL, {"prompts": ["## Loaded Skills\n" + self.body + "\n\nUser message: go"]}
		)
		self.assertTrue(result["passed"])

	def test_fails_when_no_prompt_carried_it(self):
		result = _evaluate_skill_in_prompt(TOPOLOGY_SKILL, {"prompts": ["User message: go"]})
		self.assertFalse(result["passed"])
		self.assertIn(TOPOLOGY_SKILL, result["message"])

	def test_a_replay_or_an_unknown_skill_is_an_error(self):
		self.assertTrue(_evaluate_skill_in_prompt(TOPOLOGY_SKILL, None)["error"])
		self.assertTrue(_evaluate_skill_in_prompt("_test no such skill", {"prompts": []})["error"])


class TestPromptPatch(FrappeTestCase):
	def setUp(self):
		self.name = frappe.db.get_value("AI Agent Configuration", {"agent_id": prompt_patch.AGENT_ID}, "name")
		if not self.name:
			self.skipTest("the LuCrusher agent is not on this site")

	def test_the_seeded_prompt_gets_the_fallback_wording(self):
		frappe.db.set_value("AI Agent Configuration", self.name, "system_prompt", SYSTEM_PROMPT)
		prompt_patch.execute()
		prompt = frappe.db.get_value("AI Agent Configuration", self.name, "system_prompt")
		self.assertIn(prompt_patch.NEW_LOAD, prompt)
		self.assertNotIn("call unload_skill on the previous phase's skill", prompt)
		prompt_patch.execute()
		self.assertEqual(frappe.db.get_value("AI Agent Configuration", self.name, "system_prompt"), prompt)

	def test_an_edited_prompt_is_left_alone(self):
		frappe.db.set_value("AI Agent Configuration", self.name, "system_prompt", "A prompt a person wrote.")
		prompt_patch.execute()
		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", self.name, "system_prompt"),
			"A prompt a person wrote.",
		)


class TestBaselineCasesPatch(FrappeTestCase):
	def setUp(self):
		suite = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
		if not suite:
			self.skipTest("the LuCrusher Baseline suite is not on this site")
		title = next(iter(cases_patch.DRAFTING_CASES))
		existing = frappe.db.get_value("AI Eval Case", {"suite": suite, "title": title}, "name")
		case = frappe.get_doc("AI Eval Case", existing) if existing else frappe.new_doc("AI Eval Case")
		case.update({"suite": suite, "title": title, "input_user_prompt": "analyse the topology"})
		case.set(
			"expected_tool_calls",
			[
				{
					"call_order": 1,
					"tool_name": "load_skill",
					"argument": "skill_name",
					"matcher": "equals",
					"expected_value": TOPOLOGY_SKILL,
				},
				{
					"call_order": 2,
					"tool_name": "finalize",
					"argument": "intent",
					"matcher": "equals",
					"expected_value": "TOPOLOGY_PROPOSAL",
				},
			],
		)
		case.set("assertions", [{"assertion_type": "tool_calls", "value": "IN_ORDER"}])
		case.save() if existing else case.insert()
		self.case = case.name

	def test_the_case_expects_finalize_first_and_the_skill_in_the_prompt(self):
		cases_patch.execute()
		cases_patch.execute()
		case = frappe.get_doc("AI Eval Case", self.case)
		self.assertEqual([(r.call_order, r.tool_name) for r in case.expected_tool_calls], [(1, "finalize")])
		self.assertEqual(
			[(a.assertion_type, a.value) for a in case.assertions],
			[("tool_calls", "IN_ORDER"), ("skill_in_prompt", TOPOLOGY_SKILL), ("no_tool_call", "load_skill")],
		)
