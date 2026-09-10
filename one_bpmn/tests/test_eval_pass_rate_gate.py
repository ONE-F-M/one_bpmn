# Copyright (c) 2026, one-fm and contributors
"""The go-live gate, and the consistency report behind it.

The eval gate used to warn and let the deploy through, which meant a suite could
be red for a week and nothing stopped the map going live. A suite that declares
a minimum pass rate is making a stronger claim, so activation is refused below
it — and refused with the suite named and the rate quoted, because "eval gate
failed" tells a deployer nothing they can act on.

The report is the other half: one run says whether a case passed, and only the
history says whether it agrees with itself.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import compile_process_model
from one_bpmn.api.eval_api import case_consistency

PREFIX = "ZZ PassRate"

XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    id="Defs_PassRate" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="PROCESS_ID" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1"><bpmn:outgoing>Flow_1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="EndEvent_1" />
    <bpmn:endEvent id="EndEvent_1"><bpmn:incoming>Flow_1</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""


class TestEvalPassRateGate(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		suffix = frappe.generate_hash(length=6)
		process = frappe.get_doc({
			"doctype": "Process",
			"process_name": f"{PREFIX} process {suffix}",
			"description": "Pass-rate gate test",
			"process_owner": "Administrator",
		}).insert(ignore_permissions=True)

		process_id = f"Process_PassRate_{suffix}"
		model = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"title": f"{PREFIX} model {suffix}",
			"process_id": process_id,
			"version": 1,
			"process_name": process.name,
			"bpmn_xml": XML.replace("PROCESS_ID", process_id),
		})
		model.flags.skip_editability_check = True
		self.model = model.insert(ignore_permissions=True)

		self.suite = frappe.get_doc({
			"doctype": "AI Eval Suite",
			"title": f"{PREFIX} suite {suffix}",
			"eval_type": "Direct",
			"process_model": self.model.name,
			"gate_deployment": 1,
			"min_pass_rate": 90,
		})
		self.suite.flags.ignore_mandatory = True
		self.suite.flags.ignore_links = True
		self.suite.insert(ignore_permissions=True)

	def _run(self, pass_rate, executions=20, status="Passed"):
		run = frappe.get_doc({
			"doctype": "AI Eval Run",
			"suite": self.suite.name,
			"status": status,
			"backend": "live",
			"scope": "Suite",
			"started_at": frappe.utils.now_datetime(),
			"total_cases": 5,
			"passed_cases": 5,
			"failed_cases": 0,
			"total_executions": executions,
			"pass_rate": pass_rate,
		})
		run.flags.ignore_mandatory = True
		run.flags.ignore_links = True
		return run.insert(ignore_permissions=True)

	def test_activation_is_refused_below_the_declared_rate(self):
		self._run(pass_rate=85)
		with self.assertRaises(frappe.ValidationError) as ctx:
			compile_process_model(self.model.name)
		message = str(ctx.exception)
		self.assertIn(self.suite.title, message, "the deployer must be told which suite")
		self.assertIn("85", message, "and the rate it is at")
		self.assertIn("90", message, "and the rate it needs")

	def test_activation_proceeds_at_or_above_the_rate(self):
		self._run(pass_rate=90)
		result = compile_process_model(self.model.name)
		self.assertTrue(result["success"])
		self.model.reload()
		self.assertEqual(self.model.is_active, 1)

	def test_a_gating_suite_that_never_ran_refuses_activation(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			compile_process_model(self.model.name)
		self.assertIn("never been run", str(ctx.exception))

	def test_a_suite_declaring_no_rate_still_only_warns(self):
		"""Unchanged for every suite that has not opted in: the old advisory
		warning, and the deploy goes through."""
		self.suite.db_set("min_pass_rate", 0, update_modified=False)
		result = compile_process_model(self.model.name)
		self.assertTrue(result["success"])

	def test_a_non_gating_suite_below_its_rate_does_not_block(self):
		self.suite.db_set("gate_deployment", 0, update_modified=False)
		self._run(pass_rate=10)
		result = compile_process_model(self.model.name)
		self.assertTrue(result["success"])


class TestConsistencyReport(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		suffix = frappe.generate_hash(length=6)
		self.suite = frappe.get_doc({
			"doctype": "AI Eval Suite",
			"title": f"{PREFIX} report suite {suffix}",
			"eval_type": "Direct",
		})
		self.suite.flags.ignore_mandatory = True
		self.suite.flags.ignore_links = True
		self.suite.insert(ignore_permissions=True)

		self.steady = frappe.get_doc({
			"doctype": "AI Eval Case", "suite": self.suite.name,
			"title": "steady case", "input_user_prompt": "hi",
		})
		self.flaky = frappe.get_doc({
			"doctype": "AI Eval Case", "suite": self.suite.name,
			"title": "flaky case", "input_user_prompt": "hi",
		})
		for case in (self.steady, self.flaky):
			case.flags.ignore_mandatory = True
			case.flags.ignore_links = True
			case.insert(ignore_permissions=True)

	def _run_with(self, rows, minutes_ago: int = 0):
		"""``minutes_ago`` separates runs in time: the report orders by
		started_at, and fixtures created in the same second tie."""
		run = frappe.get_doc({
			"doctype": "AI Eval Run",
			"suite": self.suite.name,
			"status": "Passed",
			"backend": "live",
			"scope": "Suite",
			"started_at": frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-minutes_ago),
			"results": rows,
		})
		run.flags.ignore_mandatory = True
		run.flags.ignore_links = True
		return run.insert(ignore_permissions=True)

	def test_a_case_that_flips_is_listed_with_its_history(self):
		self._run_with([
			{"eval_case": self.steady.name, "status": "Passed", "runs": 2, "passes": 2, "consistency_rate": 100},
			{"eval_case": self.flaky.name, "status": "Passed", "runs": 2, "passes": 2, "consistency_rate": 100},
		], minutes_ago=30)
		self._run_with([
			{"eval_case": self.steady.name, "status": "Passed", "runs": 2, "passes": 2, "consistency_rate": 100},
			{"eval_case": self.flaky.name, "status": "Failed", "runs": 2, "passes": 1, "consistency_rate": 50},
		])

		report = case_consistency(self.suite.name)
		by_case = {c["case"]: c for c in report["cases"]}

		flaky = by_case[self.flaky.name]
		self.assertEqual(flaky["executions"], 4)
		self.assertEqual(flaky["passes"], 3)
		self.assertEqual(flaky["consistency_rate"], 75)
		self.assertTrue(flaky["flips"])
		self.assertEqual(len(flaky["history"]), 2)

		steady = by_case[self.steady.name]
		self.assertEqual(steady["consistency_rate"], 100)
		self.assertFalse(steady["flips"])

	def test_the_worst_case_is_listed_first(self):
		self._run_with([
			{"eval_case": self.steady.name, "status": "Passed", "runs": 1, "passes": 1, "consistency_rate": 100},
			{"eval_case": self.flaky.name, "status": "Failed", "runs": 1, "passes": 0, "consistency_rate": 0},
		])
		report = case_consistency(self.suite.name)
		self.assertEqual(report["cases"][0]["case"], self.flaky.name)

	def test_history_reads_oldest_to_newest(self):
		first = self._run_with([
			{"eval_case": self.flaky.name, "status": "Failed", "runs": 1, "passes": 0, "consistency_rate": 0},
		], minutes_ago=30)
		second = self._run_with([
			{"eval_case": self.flaky.name, "status": "Passed", "runs": 1, "passes": 1, "consistency_rate": 100},
		])
		history = case_consistency(self.suite.name)["cases"][0]["history"]
		self.assertEqual([h["run"] for h in history], [first.name, second.name])

	def test_rows_written_before_this_feature_count_as_one_execution(self):
		"""Old results have no runs count; they were one execution each."""
		self._run_with([
			{"eval_case": self.steady.name, "status": "Passed"},
			{"eval_case": self.flaky.name, "status": "Failed"},
		])
		by_case = {c["case"]: c for c in case_consistency(self.suite.name)["cases"]}
		self.assertEqual(by_case[self.steady.name]["executions"], 1)
		self.assertEqual(by_case[self.steady.name]["consistency_rate"], 100)
		self.assertEqual(by_case[self.flaky.name]["consistency_rate"], 0)

	def test_a_suite_with_no_runs_reports_nothing_rather_than_failing(self):
		report = case_consistency(self.suite.name)
		self.assertEqual(report["cases"], [])
		self.assertEqual(report["runs"], [])
