# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001931: Agent Card generation and discovery.

The card is generated fresh from AI Agent Configuration on every
request and served guest-readable. The invariants under test:

- a card exists ONLY for an enabled + Live + a2a_exposed agent;
- every card validates against the contract's agent_card schema;
- unknown, unexposed, and non-Live agents are indistinguishable (404);
- no private field (prompt, credentials, model) ever appears;
- exposure cannot be flagged on a disabled agent.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import a2a_contract
from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.agents.a2a.card import build_agent_card
from one_bpmn.api.a2a_api import agent_card


def make_exposed_agent(**kwargs):
	defaults = {
		"a2a_exposed": 1,
		"a2a_skill_tags": "backend, frappe",
		"description": "A test agent exposed over A2A.",
	}
	defaults.update(kwargs)
	return make_agent_configuration(**defaults)


class TestA2AAgentCard(FrappeTestCase):
	def test_card_validates_against_contract(self):
		config = make_exposed_agent()
		card = build_agent_card(config.agent_id)
		self.assertIsNotNone(card)
		self.assertEqual(a2a_contract.validate("agent_card", card), [])
		self.assertEqual(card["protocolVersion"], a2a_contract.PROTOCOL_VERSION)
		self.assertFalse(card["capabilities"]["streaming"])
		# Push IS advertised: a caller with slow work can register a callback
		# instead of polling us. Streaming stays off — holding a connection for
		# hours is the wrong shape for long work.
		self.assertTrue(card["capabilities"]["pushNotifications"])
		self.assertIn(config.agent_id, card["url"])

	def test_skill_comes_from_config_data(self):
		config = make_exposed_agent()
		card = build_agent_card(config.agent_id)
		self.assertEqual(len(card["skills"]), 1)
		skill = card["skills"][0]
		self.assertEqual(skill["id"], config.agent_id)
		self.assertEqual(skill["tags"], ["backend", "frappe"])

	def test_unexposed_live_agent_has_no_card(self):
		config = make_agent_configuration()
		self.assertIsNone(build_agent_card(config.agent_id))

	def test_non_live_exposed_agent_has_no_card(self):
		config = make_exposed_agent(lifecycle_status="Draft")
		self.assertIsNone(build_agent_card(config.agent_id))

	def test_unknown_agent_has_no_card(self):
		self.assertIsNone(build_agent_card("no_such_agent_anywhere"))

	def test_no_private_fields_on_card(self):
		config = make_exposed_agent(system_prompt="TOP SECRET PROMPT")
		card = build_agent_card(config.agent_id)
		self.assertNotIn("TOP SECRET PROMPT", frappe.as_json(card))
		for private in ("system_prompt", "ai_model", "ai_provider", "temperature"):
			self.assertNotIn(private, card)

	def test_guest_can_fetch_card_and_gets_404_for_hidden(self):
		config = make_exposed_agent()
		hidden = make_agent_configuration()
		with self.set_user("Guest"):
			card = agent_card(config.agent_id)
			self.assertEqual(card["skills"][0]["id"], config.agent_id)
			self.assertRaises(frappe.DoesNotExistError, agent_card, hidden.agent_id)
			self.assertRaises(frappe.DoesNotExistError, agent_card, "no_such_agent_anywhere")

	def test_cannot_expose_disabled_agent(self):
		config = make_agent_configuration()
		config.enabled = 0
		config.a2a_exposed = 1
		self.assertRaises(frappe.ValidationError, config.save)
