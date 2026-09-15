"""The seeded rubric must accept Prosally's real answers and still catch bad ones."""
import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.eval_runner import _evaluate_assertion
from one_bpmn.agents.online_eval import rubric_assertions, rubric_suite
from one_bpmn.one_bpmn.patches.v1_0 import seed_prosally_online_rubric as patch

# Verbatim from BA production, one of the 241 the rules were written against.
GOOD = (
	'I\'ve generated the new process model "Visa Cancellation - v1" based on your '
	"specification, and it came through with no validation issues."
)

BAD = {
	"a stub": "ok",
	"raw diagram xml": 'Here is the diagram: <bpmn:process id="Process_1">',
	"a traceback": "Traceback (most recent call last):\n  File apps/one_bpmn/x.py",
	"claiming it is live": "I have deployed the process and it is now live.",
	"an unfilled template": "I updated {{ process_name }} for you.",
}


def _fails(answer, rules):
	return [r for r in rules if not _evaluate_assertion(frappe._dict(r), answer).get("passed")]


class TestProsallyOnlineRubric(FrappeTestCase):

	def setUp(self):
		if not patch._agent():
			self.skipTest("Prosally is not on this site")
		patch.execute()
		self.rules = rubric_assertions(rubric_suite(patch._agent()))

	def test_the_rubric_is_both_cases(self):
		"""A rubric suite scores every assertion on every case it carries."""
		self.assertEqual(len(self.rules), 5)
		types = frappe.get_all("AI Eval Case",
			filters={"suite": rubric_suite(patch._agent())}, pluck="case_type")
		self.assertEqual(sorted(types), ["Adversarial", "Output"])

	def test_a_real_answer_passes_every_rule(self):
		self.assertEqual(_fails(GOOD, self.rules), [])

	def test_each_bad_answer_is_caught(self):
		"""A rule nothing can fail is decoration, so each one earns its place."""
		for label, answer in BAD.items():
			with self.subTest(label):
				self.assertTrue(_fails(answer, self.rules), f"{label} passed the rubric")

	def test_seeding_twice_leaves_two_cases(self):
		patch.execute()
		self.assertEqual(
			frappe.db.count("AI Eval Case", {"suite": rubric_suite(patch._agent())}), 2
		)
