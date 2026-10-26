# Copyright (c) 2026, one-fm and contributors
"""Seeding the Orchestrator Agent's eval suite.

The property that matters most here is not that the suite exists — it is that
every case forbids the delegate tools. The Orchestrator's delegations are real:
each one runs a specialist in a Cloud Run sandbox and opens a pull request, so a
case seeded without that guard turns a Run button into a sandbox run nobody
asked for.

The rest is what any seed patch has to survive: it runs on every migrate, so a
second pass must re-seed rather than duplicate, and a site without the agent must
be left alone.

No LLM call is made: seeding writes records, running the suite is a separate act.
"""

from __future__ import annotations

import json
from unittest.mock import patch as mock_patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import seed_orchestrator_agent_eval_suite as seed

AGENT_PRESENT = frappe.db.exists("AI Agent Configuration", seed.AGENT) and frappe.db.exists(
	"BPMN Process Model", seed.MAP
)


class TestOrchestratorEvalSuiteSeed(FrappeTestCase):
	def setUp(self):
		if not AGENT_PRESENT:
			self.skipTest(f"{seed.AGENT} is not on this site")

	def _suite(self) -> str:
		return frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE_TITLE}, "name")

	def _cases(self, suite: str) -> list[dict]:
		return frappe.get_all(
			"AI Eval Case", filters={"suite": suite}, fields=["name", "title", "bpmn_id", "input_context"]
		)

	def test_every_case_forbids_the_delegate_tools(self):
		"""The one assertion that keeps a Run from spending a sandbox run."""
		seed.execute()
		expected = set(seed.DELEGATE_TOOLS.split(","))

		for case in self._cases(self._suite()):
			doc = frappe.get_doc("AI Eval Case", case["name"])
			guards = [a for a in doc.assertions if a.assertion_type == "no_tool_call"]
			self.assertTrue(guards, f"{case['title']} could delegate for real")
			forbidden = set()
			for guard in guards:
				forbidden |= {t.strip() for t in (guard.value or "").split(",") if t.strip()}
			self.assertEqual(expected - forbidden, set(), f"{case['title']} leaves a delegate tool open")

	def test_a_site_without_the_orchestrator_is_left_alone(self):
		suites_before = frappe.db.count("AI Eval Suite")
		with mock_patch.object(seed, "AGENT", "No Such Orchestrator"):
			seed.execute()
		self.assertEqual(frappe.db.count("AI Eval Suite"), suites_before)

	def test_seeding_twice_leaves_one_suite_and_one_sprint(self):
		seed.execute()
		suite = self._suite()
		cases = self._cases(suite)
		self.assertEqual(len(cases), len(seed.CASES))

		items = {json.loads(c["input_context"])["context_docname"] for c in cases}
		self.assertEqual(len(items), len(seed.CASES), "each case needs its own work item")
		for case in cases:
			self.assertEqual(case["bpmn_id"], seed.SHAPE)
			self.assertEqual(json.loads(case["input_context"])["context_doctype"], "Work Item")

		seed.execute()

		self.assertEqual(self._suite(), suite)
		self.assertEqual(len(self._cases(suite)), len(seed.CASES))
		self.assertEqual(
			{json.loads(c["input_context"])["context_docname"] for c in self._cases(suite)}, items
		)
		self.assertEqual(frappe.db.count("Sprint", {"sprint_prefix": seed.SPRINT_PREFIX}), 1)

	def test_a_used_fixture_is_still_reused(self):
		"""A run rewrites the work item — it is assigned, its orchestrator flag is
		cleared and a comment is added — so nothing on the item itself stays
		recognisable. The case is what remembers which item is its own."""
		seed.execute()
		items = {json.loads(c["input_context"])["context_docname"] for c in self._cases(self._suite())}

		for item in items:
			frappe.db.set_value(
				"Work Item", item,
				{"assignee_user": frappe.session.user, "orchestrator": 0, "status": "In Progress"},
				update_modified=False,
			)

		seed.execute()

		self.assertEqual(
			{json.loads(c["input_context"])["context_docname"] for c in self._cases(self._suite())}, items
		)
