# Copyright (c) 2026, one-fm and contributors
"""Extending the two agent Baselines.

Pins that a second run adds no case, no assertion row and no fixture, that the
repairs land (every case answers-at-all, every Orchestrator case guards every
delegate tool including the Bug Agent, the ready-to-use regex is gone, the two
stateful cases are judged) and that a site without the suites is left alone.
No model call is made.
"""

from __future__ import annotations

from unittest.mock import patch as mock_patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import agent_baselines_cover_more as seed
from one_bpmn.one_bpmn.patches.v1_0 import connector_agent_baseline_covers_every_tool as connector
from one_bpmn.one_bpmn.patches.v1_0 import orchestrator_agent_baseline_covers_every_tool as orchestrator

CONNECTOR = frappe.db.get_value("AI Eval Suite", {"title": connector.SUITE_TITLE}, "name")
ORCHESTRATOR = frappe.db.get_value("AI Eval Suite", {"title": orchestrator.SUITE_TITLE}, "name")


def _cases(suite):
	return frappe.get_all("AI Eval Case", filters={"suite": suite}, fields=["name", "title", "case_type", "input_context"])


def _assertions(case):
	return frappe.get_all("AI Eval Assertion", filters={"parent": case}, fields=["assertion_type", "value"])


class TestBaselinesCoverMore(FrappeTestCase):
	def test_a_site_without_the_suites_is_left_alone(self):
		before = frappe.db.count("AI Eval Case")
		with mock_patch.object(connector, "SUITE_TITLE", "No Such Suite"), mock_patch.object(
			orchestrator, "SUITE_TITLE", "No Such Suite"
		):
			seed.execute()
		self.assertEqual(frappe.db.count("AI Eval Case"), before)

	def test_seeding_twice_adds_nothing_and_the_repairs_hold(self):
		if not (CONNECTOR and ORCHESTRATOR):
			self.skipTest("the agent Baselines are not on this site")
		seed.execute()
		snapshot = {
			"cases": frappe.db.count("AI Eval Case", {"suite": ["in", [CONNECTOR, ORCHESTRATOR]]}),
			"assertions": frappe.db.count("AI Eval Assertion", {"parenttype": "AI Eval Case"}),
			"tasks": frappe.db.count("A2A Task"),
			"items": frappe.db.count("Work Item"),
		}
		titles = {c["title"] for c in _cases(CONNECTOR)}
		self.assertTrue({s["title"] for s in seed.CONNECTOR_CASES} <= titles)
		titles = {c["title"] for c in _cases(ORCHESTRATOR)}
		self.assertTrue({s["title"] for s in seed.ORCHESTRATOR_CASES} <= titles)

		parks = {s["title"] for s in seed.ORCHESTRATOR_CASES if seed.GUARD not in s["assertions"]}
		for suite in (CONNECTOR, ORCHESTRATOR):
			for case in _cases(suite):
				rows = _assertions(case["name"])
				if case["title"] not in parks:
					self.assertTrue(any(a.assertion_type == "regex" and a.value == r"\S" for a in rows), case["title"])
				for a in rows:
					if a.assertion_type == "no_tool_call" and a.value.startswith("delegate_"):
						self.assertIn("delegate_bug_agent", a.value, case["title"])
					self.assertFalse("ready to use" in (a.value or "") and "now enabled" in (a.value or ""), case["title"])
					if suite == CONNECTOR and a.assertion_type == "llm_judge":
						self.assertTrue(a.value.startswith(seed.JSON_NOTE), case["title"])
				if case["title"] in seed.STATEFUL:
					self.assertEqual(case["case_type"], "Output")
					self.assertFalse(frappe.db.count("AI Eval Expected Tool Call", {"parent": case["name"]}))

		seed.execute()

		self.assertEqual(
			frappe.db.count("AI Eval Case", {"suite": ["in", [CONNECTOR, ORCHESTRATOR]]}), snapshot["cases"]
		)
		self.assertEqual(frappe.db.count("AI Eval Assertion", {"parenttype": "AI Eval Case"}), snapshot["assertions"])
		self.assertEqual(frappe.db.count("A2A Task"), snapshot["tasks"])
		self.assertEqual(frappe.db.count("Work Item"), snapshot["items"])
