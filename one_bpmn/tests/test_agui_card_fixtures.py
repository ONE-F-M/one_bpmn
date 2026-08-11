# Copyright (c) 2026, one-fm and contributors
# WI-001673: every card renders from a recorded fixture; fixtures stay in
# lock-step with the contract examples and the frontend registry.

from __future__ import annotations

import json
import re
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import agui_contract

APP_ROOT = Path(__file__).resolve().parents[2]
CHAT_DIR = APP_ROOT / "spiff" / "src" / "components" / "chat"
FIXTURES = CHAT_DIR / "fixtures"
REGISTRY = CHAT_DIR / "cards" / "registry.js"

# Panel chrome — deliberately not cards, so not in the registry.
CHROME_EVENTS = {"onefm.choice", "onefm.conversation_title", "onefm.mode_transition"}
# Owned by the one-ai surface, not the generic registry.
SURFACE_EVENTS = {"onefm.lucrusher_result"}


class TestCardFixtures(FrappeTestCase):
	def test_every_fixture_validates_against_the_contract(self):
		fixtures = sorted(FIXTURES.glob("*.json"))
		self.assertTrue(fixtures, "no card fixtures found")
		for path in fixtures:
			event = json.loads(path.read_text())
			self.assertEqual(event.get("type"), "CUSTOM", path.name)
			problems = agui_contract.validate_event(event["name"], event["value"])
			self.assertEqual(problems, [], f"{path.name}: {problems}")

	def test_fixtures_match_contract_examples_exactly(self):
		# Fixtures are generated from the contract examples — drift between
		# the two means someone edited one side only.
		for path in FIXTURES.glob("*.json"):
			event = json.loads(path.read_text())
			example = agui_contract.get_event(event["name"])["example"]
			self.assertEqual(event["value"], example, f"{path.name} drifted from the contract example")

	def test_registry_covers_every_card_event(self):
		registry_src = REGISTRY.read_text()
		registered = set(re.findall(r'"(onefm\.[a-z_]+)"', registry_src))
		expected = set(agui_contract.list_events()) - CHROME_EVENTS - SURFACE_EVENTS
		self.assertEqual(
			registered,
			expected,
			"registry.js and the contract disagree about which events are cards",
		)
