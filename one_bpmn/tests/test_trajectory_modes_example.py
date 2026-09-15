"""The EXACT and ANY_ORDER worked examples behave the way their modes promise."""
import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.eval_runner import _evaluate_assertion
from one_bpmn.one_bpmn.patches.v1_0 import seed_connector_trajectory_modes as seed

READ_AND_STOPPED = ["read_work_item", "finalize"]
A_FULL_BUILD = ["read_api_docs", "draft_connector", "review_connector", "write_connector", "finalize"]
WRITTEN_BEFORE_READ = ["write_connector", "read_api_docs"]


def _facts(case, tools):
	trace = [{"tool": t, "arguments": {}} for t in tools]
	return {
		"tool_calls": tools,
		"tool_trace": trace,
		"expected_tool_calls": [
			{"order": r.call_order, "tool": r.tool_name, "matchers": []} for r in case.expected_tool_calls
		],
	}


def _score(case, tools):
	mode = next(a.value for a in case.assertions if a.assertion_type == "tool_calls")
	return _evaluate_assertion(
		frappe._dict({"assertion_type": "tool_calls", "value": mode}), "an answer", _facts(case, tools)
	)


class TestTrajectoryModesExample(FrappeTestCase):

	def setUp(self):
		if not frappe.db.exists("AI Agent Configuration", seed.AGENT):
			self.skipTest("the Connector Agent is not on this site")
		seed.execute()
		suite = frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE}, "name")
		self.cases = {}
		for name in frappe.get_all("AI Eval Case", filters={"suite": suite}, pluck="name"):
			doc = frappe.get_doc("AI Eval Case", name)
			self.cases[next(a.value for a in doc.assertions if a.assertion_type == "tool_calls")] = doc

	def test_the_suite_cannot_block_a_release(self):
		"""A mode we are still learning is not allowed to gate a deploy."""
		suite = frappe.db.get_value(
			"AI Eval Suite", {"title": seed.SUITE}, ["gate_deployment", "min_pass_rate", "ci_role"], as_dict=True
		)
		self.assertFalse(suite.gate_deployment)
		self.assertFalse(suite.min_pass_rate)
		self.assertFalse(suite.ci_role)

	def test_exact_accepts_only_that_sequence(self):
		case = self.cases["EXACT"]
		self.assertTrue(_score(case, READ_AND_STOPPED)["passed"])
		self.assertFalse(_score(case, A_FULL_BUILD)["passed"], "extra calls must fail EXACT")
		self.assertFalse(_score(case, list(reversed(READ_AND_STOPPED)))["passed"], "order must matter")

	def test_any_order_ignores_the_order(self):
		case = self.cases["ANY_ORDER"]
		self.assertTrue(_score(case, A_FULL_BUILD)["passed"])
		self.assertTrue(
			_score(case, WRITTEN_BEFORE_READ)["passed"],
			"ANY_ORDER must accept the wrong order — that is what makes it the wrong mode for an acting agent",
		)
		self.assertFalse(_score(case, READ_AND_STOPPED)["passed"], "a missing call must still fail")

	def test_a_missing_call_says_which(self):
		message = _score(self.cases["ANY_ORDER"], READ_AND_STOPPED).get("message") or ""
		self.assertIn("read_api_docs", message)
