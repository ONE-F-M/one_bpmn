# Copyright (c) 2026, one-fm and contributors
"""The rules block lands once on each configuration and a second run adds nothing."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import agent_prompts_for_awkward_orders as patch
from one_bpmn.one_bpmn.patches.v1_0 import seed_connector_agent_config as seed


class TestAwkwardOrders(FrappeTestCase):
	def setUp(self):
		self.agents = [a for a in patch.RULES if frappe.db.exists("AI Agent Configuration", a)]
		if not self.agents:
			self.skipTest("neither agent is on this site")
		self.before = {a: frappe.db.get_value("AI Agent Configuration", a, "system_prompt") for a in self.agents}

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _prompt(self, agent):
		return frappe.db.get_value("AI Agent Configuration", agent, "system_prompt") or ""

	def test_the_rules_land_once_and_keep_the_prompt_before_them(self):
		for agent in self.agents:
			stripped = self.before[agent].split(patch.marker(patch.RULES[agent]))[0].rstrip()
			frappe.db.set_value("AI Agent Configuration", agent, "system_prompt", stripped, update_modified=False)
		patch.execute()
		for agent in self.agents:
			prompt = self._prompt(agent)
			self.assertEqual(prompt.count(patch.marker(patch.RULES[agent])), 1, agent)
			self.assertTrue(prompt.startswith(self.before[agent].split(patch.marker(patch.RULES[agent]))[0].rstrip()), agent)
		patch.execute()
		for agent in self.agents:
			self.assertEqual(self._prompt(agent).count(patch.marker(patch.RULES[agent])), 1, agent)

	def test_a_reworded_rule_replaces_the_block(self):
		agent = self.agents[0]
		stale = patch.RULES[agent].strip() + "\n- an old rule nobody wants any more\n"
		frappe.db.set_value(
			"AI Agent Configuration", agent, "system_prompt",
			"Do the job.\n\n" + stale, update_modified=False,
		)
		patch.execute()
		prompt = self._prompt(agent)
		self.assertNotIn("an old rule nobody wants", prompt)
		self.assertTrue(prompt.startswith("Do the job."))
		self.assertTrue(prompt.rstrip().endswith(patch.RULES[agent].strip()))

	def test_a_fresh_seed_carries_the_connector_rules(self):
		self.assertIn(patch.marker(patch.RULES["Connector Agent"]), seed._SYSTEM_PROMPT)
		self.assertTrue(seed._SYSTEM_PROMPT.rstrip().endswith(seed._AWKWARD_ORDERS.rstrip()))

	def test_the_sharpened_rubric_lands_on_every_copy_of_the_case(self):
		title = next(iter(patch.RUBRICS))
		cases = frappe.get_all("AI Eval Case", filters={"title": title}, pluck="name")
		if not cases:
			self.skipTest("the case is not on this site")
		judges = frappe.get_all(
			"AI Eval Assertion", filters={"parent": ["in", cases], "assertion_type": "llm_judge"}, pluck="name"
		)
		for name in judges:
			frappe.db.set_value("AI Eval Assertion", name, "value", "an older standard", update_modified=False)
		patch.execute()
		for name in judges:
			self.assertEqual(frappe.db.get_value("AI Eval Assertion", name, "value"), patch.RUBRICS[title])

	def test_the_tracking_item_is_made_once_and_the_brief_names_it(self):
		cases = frappe.get_all("AI Eval Case", filters={"title": patch.ALREADY_DELEGATED}, pluck="name")
		if not cases:
			self.skipTest("the case is not on this site")
		patch.execute()
		before = frappe.db.count("Work Item")
		patch.execute()
		self.assertEqual(frappe.db.count("Work Item"), before)
		tracking = frappe.get_all("Work Item", filters={"title": patch.TRACKING_ITEM["title"]}, pluck="name")
		self.assertEqual(len(tracking), 1)
		for case in cases:
			item = frappe.parse_json(frappe.db.get_value("AI Eval Case", case, "input_context"))["context_docname"]
			self.assertIn(tracking[0], frappe.db.get_value("Work Item", item, "description"))

	def test_the_patch_is_declared(self):
		with open(frappe.get_app_path("one_bpmn", "patches.txt")) as f:
			self.assertIn("agent_prompts_for_awkward_orders", f.read())
