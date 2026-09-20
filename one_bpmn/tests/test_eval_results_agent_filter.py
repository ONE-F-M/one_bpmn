# Copyright (c) 2026, one-fm and contributors
"""Filtering the eval results page by agent.

A run knows its agent either from its own field or from its suite. The page
showed the suite's answer on the row but filtered on the run's own field, so
picking an agent in the dropdown made every run that only knew its agent
through the suite disappear — five of them on the dev site the day this was
found. The dropdown was also built from the rows left after filtering, so once
one agent was chosen it was the only agent offered.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from one_bpmn.agents._eval_test_factories import make_eval_suite
from one_bpmn.api.eval_api import scheduled_results


def _run_without_its_own_agent(suite: str) -> str:
	"""A run that names its suite and nothing else, the way older rows do."""
	return frappe.get_doc({
		"doctype": "AI Eval Run",
		"suite": suite,
		"status": "Passed",
		"started_at": now_datetime(),
		"total_cases": 1,
		"passed_cases": 1,
	}).insert(ignore_permissions=True).name


class TestEvalResultsAgentFilter(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.first = make_eval_suite(process_model=None, title="_Test filter first " + frappe.generate_hash(length=6))
		self.second = make_eval_suite(process_model=None, title="_Test filter second " + frappe.generate_hash(length=6))
		self.first_run = _run_without_its_own_agent(self.first.name)
		self.second_run = _run_without_its_own_agent(self.second.name)

	def _runs(self, **kwargs):
		return {row["run"]: row for row in scheduled_results(days=1, **kwargs)["runs"]}

	def test_a_run_that_knows_its_agent_only_through_its_suite_survives_the_filter(self):
		rows = self._runs(agent=self.first.agent_configuration)
		self.assertIn(self.first_run, rows)
		self.assertNotIn(self.second_run, rows)
		self.assertEqual(rows[self.first_run]["agent"], self.first.agent_configuration)

	def test_the_row_and_the_filter_agree_on_the_agent(self):
		"""Whatever agent a row shows is the agent that filter finds it under."""
		for row in scheduled_results(days=1)["runs"]:
			if not row["agent"]:
				continue
			self.assertIn(row["run"], self._runs(agent=row["agent"]))

	def test_the_dropdown_offers_every_agent_even_while_one_is_chosen(self):
		agents = scheduled_results(days=1, agent=self.first.agent_configuration)["agents"]
		self.assertIn(self.first.agent_configuration, agents)
		self.assertIn(self.second.agent_configuration, agents)
