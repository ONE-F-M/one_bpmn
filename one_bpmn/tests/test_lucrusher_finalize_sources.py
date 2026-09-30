# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""LuCrusher's finalize refuses an analysis item that does not say where it came from.

Production feedback showed checklist fields that exist in no document. The schema on the
map's finalize shape is what the argument check enforces, so these read it from the map.
"""

import html
import json
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor.tool_bounds import validate_tool_arguments
from one_bpmn.one_bpmn.patches.v1_0.migrate_lucrusher_agent_to_generic_path import PROCESS_MODEL as MAP


class TestFinalizeRequiresSources(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("BPMN Process Model", MAP):
			self.skipTest(f"{MAP} ships by export and is not on this site")
		xml = frappe.db.get_value("BPMN Process Model", MAP, "bpmn_xml")
		match = re.search(r'<bpmn:scriptTask id="finalize"[^>]*?spiffworkflow:aiToolParams="([^"]*)"', xml)
		self.assertIsNotNone(match, "the finalize shape has no aiToolParams")
		self.schema = json.loads(html.unescape(match.group(1)))

	def _check(self, **arguments):
		return validate_tool_arguments(
			"finalize", self.schema["properties"], self.schema["required"],
			{"intent": "MIGRATION_TASKS_DRAFT", "response": "Drafted.", **arguments},
		)

	def test_task_without_references_is_rejected_by_name(self):
		error = self._check(migration_tasks={"processes": [{
			"process_name": "Submit Leave Request",
			"tasks": [{"category": "SCRIPT TASK", "task": "Check balance", "detail": "", "is_new": True}],
		}]})
		self.assertIn("references", error)

	def test_task_with_empty_references_is_rejected(self):
		error = self._check(migration_tasks={"processes": [{
			"process_name": "Submit Leave Request",
			"tasks": [{"category": "SCRIPT TASK", "task": "Check balance", "references": []}],
		}]})
		self.assertIn("references", error)

	def test_topology_process_without_source_is_rejected_by_name(self):
		error = self._check(topology={"processes": [{"process_name": "Submit Leave Request"}]})
		self.assertIn("source", error)

	def test_prompt_block_without_source_is_rejected_by_name(self):
		error = self._check(prosally_prompts={"processes": [{"process_name": "Submit Leave Request", "prompt_block": "A: ..."}]})
		self.assertIn("source", error)

	def test_sourced_items_and_a_bare_confirmation_pass(self):
		self.assertIsNone(self._check(
			topology={"processes": [{"process_name": "Submit Leave Request", "source": "Page 1: Leave"}]},
			migration_tasks={"processes": [{"tasks": [{"task": "Check balance", "references": ["hrms/leave.py"]}]}]},
			prosally_prompts={"processes": [{"process_name": "Submit Leave Request", "source": "Page 1: Leave"}]},
		))
		self.assertIsNone(self._check())


class TestSkillsCiteSourcesPatch(FrappeTestCase):
	def test_each_phase_skill_gains_the_sources_rule_once(self):
		from one_bpmn.one_bpmn.patches.v1_0 import lucrusher_skills_cite_sources as patch
		from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_skills import SKILLS
		from one_bpmn.one_bpmn.patches.v1_0.seed_prosally_and_frontend_skills import _upsert_skill

		for skill in SKILLS:
			_upsert_skill(skill)
			frappe.db.set_value("AI Skill", {"skill_name": skill["skill_name"]}, "body", skill["body"])

		patch.execute()
		patch.execute()

		bodies = {s["skill_name"]: frappe.db.get_value("AI Skill", {"skill_name": s["skill_name"]}, "body") for s in SKILLS}
		for name, body in bodies.items():
			self.assertEqual(body.count(patch.MARKER), 1, name)
			self.assertIn("is not listed", body, name)
		self.assertIn("shapes, source}", bodies[patch.TOPOLOGY_SKILL])
		self.assertIn("prompt_block, source}", bodies[patch.PROSALLY_SKILL])


class TestBaselineStateInSessionStatePatch(FrappeTestCase):
	def test_hidden_state_note_moves_into_session_state(self):
		from one_bpmn.one_bpmn.patches.v1_0 import lucrusher_baseline_state_in_session_state as patch
		from one_bpmn.one_bpmn.patches.v1_0.seed_lucrusher_eval_suite import SUITE_TITLE

		suite = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name") or frappe.get_doc(
			{"doctype": "AI Eval Suite", "title": SUITE_TITLE}
		).insert(ignore_permissions=True).name
		case = frappe.get_doc({
			"doctype": "AI Eval Case",
			"suite": suite,
			"title": "_Test state note",
			"input_user_prompt": "now write the ProsAlly prompts",
			"input_context": json.dumps({
				"conversation_messages": [
					{"message_type": "User", "text": "approved"},
					{"message_type": "Tool", "text": "__lucrusher_state__", "metadata": {
						"intent": "MIGRATION_TASKS_CONFIRMED",
						"topology": {"processes": [{"process_name": "Visa Request"}]},
						"codebase_scan": None,
					}},
				],
				"session_state": {"lucid_doc:abc": {"summary": "two pages"}},
			}),
		}).insert(ignore_permissions=True)

		patch.execute()

		context = json.loads(frappe.db.get_value("AI Eval Case", case.name, "input_context"))
		self.assertEqual([m["text"] for m in context["conversation_messages"]], ["approved"])
		self.assertEqual(context["session_state"]["topology"], {"processes": [{"process_name": "Visa Request"}]})
		self.assertEqual(context["session_state"]["lucid_doc:abc"], {"summary": "two pages"})
		self.assertNotIn("codebase_scan", context["session_state"])
