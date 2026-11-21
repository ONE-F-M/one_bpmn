# Copyright (c) 2026, one-fm and contributors
"""The reported Logix requests are Baseline cases, and their checks pass and fail on the right replies."""

import json
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import seed_logix_reported_request_cases as p
from processa.patches.v1_0.seed_logix_baseline_suite import AGENT_ID, SUITE_TITLE

REFUSAL = "I was unable to generate a safe script after multiple attempts. Please rephrase your request."


def _expected(case_title: str, path: str) -> list[str]:
	spec = next(c for c in p.CASES if c["title"] == case_title)
	values = [json.loads(a["value"]) for a in spec["assertions"] if a["assertion_type"] == "tool_artifact"]
	return [v["expected"] for v in values if v["path"] == path]


class TestSeedLogixReportedRequestCases(FrappeTestCase):
	def setUp(self):
		super().setUp()
		agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
		if not agent:
			model = frappe.get_doc(
				{
					"doctype": "BPMN Process Model",
					"title": "zz-logix-stub-map",
					"process_id": "zz_logix_stub",
					"version": 1,
				}
			)
			model.flags.skip_editability_check = True
			model.flags.skip_script_security_check = True
			model.insert(ignore_permissions=True)
			agent = (
				frappe.get_doc(
					{
						"doctype": "AI Agent Configuration",
						"agent_name": "ZZ Logix Stub",
						"agent_id": AGENT_ID,
						"agent_type": "Background",
						"agent_framework": "Direct API",
						"process_model": model.name,
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		if not frappe.db.exists("AI Eval Suite", {"agent_configuration": agent, "title": SUITE_TITLE}):
			frappe.get_doc(
				{"doctype": "AI Eval Suite", "title": SUITE_TITLE, "agent_configuration": agent}
			).insert(ignore_permissions=True)
		self.suite = frappe.db.get_value(
			"AI Eval Suite", {"agent_configuration": agent, "title": SUITE_TITLE}
		)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_seeding_twice_adds_each_reported_request_once(self):
		p.execute()
		p.execute()
		for spec in p.CASES:
			with self.subTest(spec["title"]):
				names = frappe.get_all(
					"AI Eval Case", {"suite": self.suite, "title": spec["title"]}, pluck="name"
				)
				self.assertEqual(len(names), 1)
				case = frappe.get_doc("AI Eval Case", names[0])
				self.assertEqual(case.input_user_prompt, spec["prompt"])
				self.assertEqual(
					[c.tool_name for c in case.expected_tool_calls], [c["tool_name"] for c in spec["calls"]]
				)

	def test_a_refusal_fails_every_case(self):
		not_refused = json.loads(p.NOT_REFUSED["value"])["expected"]
		self.assertIsNone(re.search(not_refused, REFUSAL))
		for spec in p.CASES:
			self.assertIn(p.NOT_REFUSED, spec["assertions"])

	def test_the_medical_appointment_case_rejects_the_field_that_does_not_exist(self):
		checks = _expected(
			"A Medical Appointment attendance script uses the real date field", "modified_script"
		)
		good = "att_date = frappe.utils.getdate(doc.date_and_time_confirmation)"
		bad = "att_date = frappe.utils.getdate(doc.appointment_date)"
		self.assertTrue(all(re.search(c, good) for c in checks))
		self.assertFalse(all(re.search(c, bad) for c in checks))

	def test_the_invoice_case_wants_the_limit_of_500(self):
		(check,) = _expected(
			"A rule to approve an invoice under 500 gets a script, not a question back", "modified_script"
		)
		self.assertTrue(re.search(check, "if doc.grand_total < 500:"))
		self.assertFalse(re.search(check, "if doc.grand_total < 5000:"))
