"""A site that seeded the Connector suite after the case patch still ends up whole."""
import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import (
	add_tool_call_cases_to_agent_suites as cases_patch,
	connector_trajectory_case_after_its_suite as heal_patch,
	seed_connector_agent_eval_suite as connector_seed,
)

SUITE = connector_seed.SUITE_TITLE
CASE = cases_patch.CONNECTOR_CASE


def _trajectory_cases():
	suite = frappe.db.get_value("AI Eval Suite", {"title": SUITE}, "name")
	return frappe.get_all("AI Eval Case", filters={"suite": suite, "title": CASE}, pluck="name") if suite else []


class TestConnectorTrajectoryCaseHeals(FrappeTestCase):

	def setUp(self):
		if not frappe.db.exists("AI Agent Configuration", connector_seed.AGENT) or not frappe.db.exists(
			"BPMN Process Model", connector_seed.MAP
		):
			self.skipTest("Connector Agent is not on this site")

	def test_the_case_arrives_when_the_patch_runs_after_the_seed(self):
		"""Seed first, then the cases: the order sites migrate in from now on."""
		connector_seed.execute()
		heal_patch.execute()
		self.assertEqual(len(_trajectory_cases()), 1)

	def test_running_it_again_adds_nothing(self):
		"""The heal is the same code as the original, so a whole site stays whole."""
		heal_patch.execute()
		before = _trajectory_cases()
		heal_patch.execute()
		self.assertEqual(_trajectory_cases(), before)
		self.assertEqual(len(before), 1)
