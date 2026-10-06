# Copyright (c) 2026, one-fm and contributors
"""Build Context still preloads a phase skill when the last turn recorded no phase intent."""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.memory import session_state
from one_bpmn.api import skill_tools

AGENT = "lucrusher"


class TestPreloadFallsBackToProgress(FrappeTestCase):
	"""Runs the live Build Context Server Script; it reaches a site with the LuCrusher map by export."""

	def setUp(self):
		self.script = frappe.db.get_value(
			"Server Script", {"name": ["like", "LuCrusher%Build Context"]}, "script"
		)
		if not self.script:
			self.skipTest("the LuCrusher Build Context script is not on this site")
		self.conversation = f"_test-fallback-{frappe.generate_hash(length=6)}"

	def _preloaded(self, state):
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
					"task_data": {"conversation_id": self.conversation, "user_text": "next"},
					"context_docname": self.conversation,
					"agent_configuration": AGENT,
					"instance": SimpleNamespace(
						name="_t", context_doctype="Chat Conversation", context_docname=self.conversation
					),
					"result": result,
				},
			)
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
