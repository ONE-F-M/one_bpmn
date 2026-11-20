# Copyright (c) 2026, one-fm and contributors
"""Build Context still preloads a phase skill when the last turn recorded no phase intent."""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_conversations import session_state
from processa.ai_agent_skills import skill_tools

AGENT = "lucrusher"
PROPOSED = {
	"intent": "TOPOLOGY_PROPOSAL",
	"document": {"title": "Visa", "page_count": 3},
	"topology": {"processes": []},
}


class TestPreloadFallsBackToProgress(FrappeTestCase):
	"""Runs the live Build Context Server Script; it reaches a site with the LuCrusher map by export."""

	def setUp(self):
		self.script = frappe.db.get_value(
			"Server Script", {"name": ["like", "LuCrusher%Build Context"]}, "script"
		)
		if not self.script:
			self.skipTest("the LuCrusher Build Context script is not on this site")
		self.conversation = f"_test-fallback-{frappe.generate_hash(length=6)}"

	def _preloaded(self, state, user_text="next"):
		activated, result = [], {}
		with (
			patch.object(session_state, "get_state", return_value=state),
			patch.object(
				skill_tools, "activate_skill", side_effect=lambda s, a, i: activated.append(s) or "body"
			),
			patch.object(skill_tools, "deactivate_skill", return_value="unloaded"),
		):
			exec(
				self.script,
				{
					"frappe": frappe,
					"task_data": {"conversation_id": self.conversation, "user_text": user_text},
					"context_docname": self.conversation,
					"agent_configuration": AGENT,
					"instance": SimpleNamespace(
						name="_t", context_doctype="Chat Conversation", context_docname=self.conversation
					),
					"result": result,
				},
			)
		self.result = result
		return activated, result["preloaded_skill"]

	def test_a_recorded_phase_intent_still_wins(self):
		activated, chosen = self._preloaded(
			{"intent": "TOPOLOGY_CONFIRMED", "migration_tasks": {"processes": []}}
		)
		self.assertEqual(chosen, "lucrusher-migration-tasks")
		self.assertEqual(activated, ["lucrusher-migration-tasks"])

	def test_tasks_confirmed_in_words_still_preload_the_prompts_skill(self):
		activated, chosen = self._preloaded(
			{
				"intent": "CLARIFY",
				"topology": {"processes": []},
				"migration_tasks": {"processes": [{"tasks": []}]},
			}
		)
		self.assertEqual(chosen, "lucrusher-prosally-prompts")
		self.assertEqual(activated, ["lucrusher-prosally-prompts"])

	def test_a_fetched_document_alone_preloads_the_topology_skill(self):
		_, chosen = self._preloaded({"intent": "CLARIFY", "document": {"title": "Absence", "page_count": 7}})
		self.assertEqual(chosen, "lucrusher-topology-analysis")

	def test_nothing_fetched_yet_preloads_nothing(self):
		activated, chosen = self._preloaded({"intent": "CLARIFY"})
		self.assertEqual((activated, chosen), ([], ""))


class TestTheRequestChoosesThePhase(FrappeTestCase):
	"""The latest message names the phase; the stored state only predicts one."""

	setUp = TestPreloadFallsBackToProgress.setUp
	_preloaded = TestPreloadFallsBackToProgress._preloaded

	def test_a_migration_list_request_loads_the_migration_skill_before_the_topology_is_confirmed(self):
		_, chosen = self._preloaded(PROPOSED, "give me the migration list")
		self.assertEqual(chosen, "lucrusher-migration-tasks")
		self.assertEqual(self.result["requested_phase"], "MIGRATION_TASKS")
		self.assertIn("Requested now: the migration task list", self.result["state_block"])

	def test_a_code_removal_request_has_its_own_path(self):
		_, chosen = self._preloaded(PROPOSED, "which code should we remove?")
		self.assertEqual(chosen, "lucrusher-migration-tasks")
		self.assertEqual(self.result["requested_phase"], "CODE_REMOVAL")
		self.assertIn("only CODE REMOVAL tasks", self.result["state_block"])

	def test_a_topology_request_loads_the_topology_skill_after_tasks_were_drafted(self):
		_, chosen = self._preloaded(
			{"intent": "MIGRATION_TASKS_DRAFT", "document": {"title": "Visa", "page_count": 3}},
			"show me the topology again",
		)
		self.assertEqual(chosen, "lucrusher-topology-analysis")
		self.assertEqual(self.result["requested_phase"], "TOPOLOGY")

	def test_a_request_naming_two_phases_or_none_is_asked_about(self):
		for text in ("do the topology and the migration tasks", "what's next?"):
			self._preloaded(PROPOSED, text)
			self.assertEqual(self.result["requested_phase"], "UNCLEAR", text)
			self.assertIn("intent CLARIFY", self.result["state_block"])

	def test_a_confirmation_follows_the_stored_phase(self):
		_, chosen = self._preloaded({"intent": "TOPOLOGY_CONFIRMED"}, "yes, the topology looks good")
		self.assertEqual(self.result["requested_phase"], "")
		self.assertEqual(chosen, "lucrusher-migration-tasks")
