# Copyright (c) 2026, one-fm and contributors
"""Seeding the Connector Agent's eval suite.

A seed patch runs on every migrate, so the two things worth pinning are that a
second run re-seeds rather than duplicates the suite, its cases and the A2A Task
fixtures they point at, and that a site without the Connector Agent is left
alone — the patch reaches production, where the agent may not exist.

No LLM call is made: seeding writes records, running the suite is a separate act.
"""

from __future__ import annotations

import json
from unittest.mock import patch as mock_patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import seed_connector_agent_eval_suite as seed

AGENT_PRESENT = frappe.db.exists("AI Agent Configuration", seed.AGENT) and frappe.db.exists(
	"BPMN Process Model", seed.MAP
)


class TestConnectorEvalSuiteSeed(FrappeTestCase):
	def _suite(self) -> str:
		return frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE_TITLE}, "name")

	def _cases(self, suite: str) -> list[dict]:
		return frappe.get_all(
			"AI Eval Case", filters={"suite": suite}, fields=["name", "title", "bpmn_id", "input_context"]
		)

	def test_a_site_without_the_connector_agent_is_left_alone(self):
		suites_before = frappe.db.count("AI Eval Suite")
		with mock_patch.object(seed, "AGENT", "No Such Connector Agent"):
			seed.execute()
		self.assertEqual(frappe.db.count("AI Eval Suite"), suites_before)

	def test_seeding_twice_leaves_one_suite_and_three_cases(self):
		if not AGENT_PRESENT:
			self.skipTest(f"{seed.AGENT} is not on this site")

		seed.execute()
		suite = self._suite()
		self.assertTrue(suite)
		cases = self._cases(suite)
		self.assertEqual(len(cases), len(seed.CASES))

		fixtures = {json.loads(c["input_context"])["context_docname"] for c in cases}
		self.assertEqual(len(fixtures), len(seed.CASES), "each case needs its own work order")
		for case in cases:
			self.assertEqual(case["bpmn_id"], seed.SHAPE)
			context = json.loads(case["input_context"])
			self.assertEqual(context["context_doctype"], "A2A Task")

		seed.execute()

		self.assertEqual(self._suite(), suite)
		self.assertEqual(len(self._cases(suite)), len(seed.CASES))
		self.assertEqual(
			{json.loads(c["input_context"])["context_docname"] for c in self._cases(suite)},
			fixtures,
			"a re-seed must reuse the fixtures, not mint new ones",
		)

	def test_a_used_fixture_is_still_reused(self):
		"""The agent writes its answer onto the work order's status_message when a
		run finishes. A fixture identified by that field stops matching the moment
		the suite is used, and every migrate afterwards mints another one."""
		if not AGENT_PRESENT:
			self.skipTest(f"{seed.AGENT} is not on this site")

		seed.execute()
		cases = self._cases(self._suite())
		fixtures = {json.loads(c["input_context"])["context_docname"] for c in cases}

		for task in fixtures:
			frappe.db.set_value(
				"A2A Task", task,
				{"status_message": "Successfully built the connector.", "state": "completed"},
				update_modified=False,
			)

		seed.execute()

		self.assertEqual(
			{json.loads(c["input_context"])["context_docname"] for c in self._cases(self._suite())},
			fixtures,
		)

	def test_every_case_carries_at_least_one_assertion(self):
		if not AGENT_PRESENT:
			self.skipTest(f"{seed.AGENT} is not on this site")

		seed.execute()
		for case in self._cases(self._suite()):
			doc = frappe.get_doc("AI Eval Case", case["name"])
			self.assertTrue(doc.assertions, f"{case['title']} would pass on anything")
			for assertion in doc.assertions:
				self.assertTrue((assertion.value or "").strip())
