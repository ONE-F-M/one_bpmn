"""The nightly sweep must have suites to pick up, and only ones it can run."""
import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.eval_ci import select_suites
from one_bpmn.one_bpmn.patches.v1_0 import agent_baselines_run_nightly as patch


def _role(title):
	return frappe.db.get_value("AI Eval Suite", {"title": title}, "ci_role")


class TestAgentBaselinesRunNightly(FrappeTestCase):

	def setUp(self):
		self.present = [t for t in patch.SUITES if frappe.db.exists("AI Eval Suite", {"title": t})]
		if not self.present:
			self.skipTest("neither agent baseline is on this site")
		patch.execute()

	def test_the_baselines_carry_the_nightly_role(self):
		for title in self.present:
			with self.subTest(title):
				self.assertEqual(_role(title), "Nightly")

	def test_the_sweep_now_selects_them(self):
		"""select_suites is what the 02:30 script calls; an empty list is an empty night."""
		picked = {s["title"] for s in select_suites(role="Nightly")}
		for title in self.present:
			self.assertIn(title, picked)

	def test_a_suite_that_is_not_here_is_not_invented(self):
		patch.execute()
		self.assertEqual(
			frappe.db.count("AI Eval Suite", {"title": ["in", patch.SUITES]}), len(self.present)
		)

	def test_running_it_again_changes_nothing(self):
		before = {t: _role(t) for t in self.present}
		patch.execute()
		self.assertEqual({t: _role(t) for t in self.present}, before)
