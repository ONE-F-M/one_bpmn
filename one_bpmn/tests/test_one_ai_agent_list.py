# Copyright (c) 2026, one-fm and contributors
# WI-001678: the ONE AI page offers the Lumina page's own fixed set of modes
# — General Chat, BA Agent, LuCrusher — and lists only their conversations.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import agui
from one_bpmn.api.agent_invocation import ONE_AI_AGENT_IDS, list_one_ai_agents

PREFIX = "zz_one_ai_"


def _config(agent_id: str, label: str, **overrides) -> str:
	"""An AI Agent Configuration for one of the page's agent ids."""
	values = {
		"doctype": "AI Agent Configuration",
		"agent_id": agent_id,
		"agent_name": f"ZZ {label}",
		"chat_mode_label": label,
		"agent_type": "Chat",
		"agent_framework": "Direct API",
		"lifecycle_status": "Live",
		"enabled": 1,
	}
	values.update(overrides)
	doc = frappe.get_doc(values)
	doc.insert(ignore_permissions=True)
	return doc.name


class TestOneAiAgentList(FrappeTestCase):
	"""The page's picker: fixed membership, live fields, quiet absences."""

	def setUp(self):
		for agent_id in ONE_AI_AGENT_IDS:
			frappe.db.delete("AI Agent Configuration", {"agent_id": agent_id})

	def test_the_list_is_the_lumina_set_in_order(self):
		_config("lucrusher_agent", "LuCrusher", icon="💥")
		_config("lumina_general_chat", "General Chat", icon="💬")
		_config("ba_architect", "BA Agent", icon="📋")

		agents = list_one_ai_agents()

		self.assertEqual(
			[a["agent_id"] for a in agents],
			["lumina_general_chat", "ba_architect", "lucrusher_agent"],
			"the picker follows ONE_AI_AGENT_IDS order, not insertion order",
		)
		self.assertEqual([a["icon"] for a in agents], ["💬", "📋", "💥"])

	def test_other_agents_are_never_offered(self):
		_config("lumina_general_chat", "General Chat")
		_config(f"{PREFIX}prosally", "ProsAlly Probe")

		labels = {a["label"] for a in list_one_ai_agents()}

		self.assertEqual(labels, {"General Chat"})

	def test_label_and_icon_come_from_the_record(self):
		# WI-001634: LuCrusher's label IS its map's start trigger, so a
		# hardcoded copy that drifts from the record breaks every chat.
		_config("lucrusher_agent", "lucrusher", icon="🛠️")

		agent = list_one_ai_agents()[0]

		self.assertEqual(agent["value"], "lucrusher")
		self.assertEqual(agent["label"], "lucrusher")
		self.assertEqual(agent["icon"], "🛠️")

	def test_a_missing_or_dormant_agent_is_simply_absent(self):
		_config("lumina_general_chat", "General Chat", lifecycle_status="Draft")
		_config("ba_architect", "BA Agent", enabled=0)
		# lucrusher_agent has no configuration on this site at all

		self.assertEqual(list_one_ai_agents(), [])

	def test_a_map_driven_agent_needs_its_diagram_deployed(self):
		model = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"title": f"{PREFIX}dormant_map",
			"process_id": f"{PREFIX}dormant_map",
			"version": "1.0",
			"is_active": 0,
		}).insert(ignore_permissions=True)
		_config("lumina_general_chat", "General Chat", process_model=model.name)

		self.assertEqual(list_one_ai_agents(), [])

		frappe.db.set_value("BPMN Process Model", model.name, "is_active", 1)
		self.assertEqual([a["agent_id"] for a in list_one_ai_agents()], ["lumina_general_chat"])

	def test_an_agent_without_a_map_is_still_offered(self):
		# These modes may run on the langgraph or direct-api runner, which
		# need no diagram — gating them on one would empty the page.
		_config("ba_architect", "BA Agent", agent_framework="LangGraph")

		self.assertEqual([a["agent_id"] for a in list_one_ai_agents()], ["ba_architect"])


class TestOneAiConversationList(FrappeTestCase):
	"""The history sidebar shows this page's conversations and no others."""

	def setUp(self):
		for agent_id in ONE_AI_AGENT_IDS:
			frappe.db.delete("AI Agent Configuration", {"agent_id": agent_id})
		_config("lumina_general_chat", "General Chat")

	def _conversation(self, agent_mode: str) -> str:
		doc = frappe.get_doc({
			"doctype": "Chat Conversation",
			"title": f"{PREFIX}{agent_mode}",
			"agent_mode": agent_mode,
		}).insert(ignore_permissions=True)
		return doc.name

	def test_only_this_pages_conversations_are_listed(self):
		mine_by_label = self._conversation("General Chat")
		mine_by_id = self._conversation("lumina_general_chat")
		someone_elses = self._conversation("ProsAlly")

		listed = {c["name"] for c in agui.list_conversations()}

		self.assertIn(mine_by_label, listed)
		self.assertIn(mine_by_id, listed, "conversations recorded by agent id count too")
		self.assertNotIn(someone_elses, listed)
