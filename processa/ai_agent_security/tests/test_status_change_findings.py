# Copyright (c) 2026, one-fm and contributors
"""Logix's review sends back a script that sets a workflow state, and leaves copying or reading one alone."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_security.code_checks.script_validator import request_findings, status_change_findings

SETS = (
	'doc.db_set("workflow_state", "Completed")',
	'doc.workflow_state = "Accommodation Cleared"',
	'frappe.db.set_value("Overtime Request", doc.name, "workflow_state", "Completed")',
	'frappe.db.set_value("Overtime Request", doc.name, {"workflow_state": "Completed"})',
	'doc.db_set({"docstatus": 1})',
	"doc.docstatus = 1",
)
COPIES = (
	"offboarding.workflow_state_of_clearance = clearance.workflow_state",
	'frappe.db.set_value("Clearance Row", row, {"workflow_state": s.workflow_state, "cleared_on": cleared})',
	'state = doc.workflow_state or "Draft"',
	'if doc.workflow_state != "Completed":\n\tresult["done"] = False',
)
STATE = "Status Check Completed"


class TestStatusChangeFindings(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_each_way_of_setting_a_fixed_status_is_a_finding(self):
		for code in SETS:
			with self.subTest(code=code):
				findings = status_change_findings(code)
				self.assertEqual(len(findings), 1, findings)
				self.assertIn("Apply Workflow service task", findings[0]["rule"])
				self.assertEqual((findings[0]["line"], findings[0]["code"]), (1, code))

	def test_copying_or_reading_a_status_is_not_a_finding(self):
		for code in COPIES:
			with self.subTest(code=code):
				self.assertEqual(status_change_findings(code), [])

	def test_the_review_reports_it(self):
		rules = [
			f["rule"]
			for f in request_findings('doc.db_set("workflow_state", "Completed")', "mark it as completed")
		]
		self.assertTrue(any("Apply Workflow" in rule for rule in rules), rules)

	def test_the_finding_names_the_workflow_and_doc_status_of_the_state(self):
		# A state row on its own; inserting a Workflow would add a field to its DocType outside the rollback.
		frappe.get_doc(
			{
				"doctype": "Workflow Document State",
				"parent": "Status Check Workflow",
				"parenttype": "Workflow",
				"parentfield": "states",
				"state": STATE,
				"doc_status": "1",
			}
		).db_insert()
		(finding,) = status_change_findings(f'doc.db_set("workflow_state", "{STATE}")')
		self.assertIn("Status Check Workflow (doc status 1)", finding["rule"])

	def test_code_that_does_not_parse_has_no_status_finding(self):
		self.assertEqual(status_change_findings('doc.workflow_state = ("Completed"'), [])
