# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""run_logix_test_case replays the BPMN engine runtime, not the HTTP one.

Logix scripts follow the engine's injected-variable contract (doc / task_data
/ result — see fix_logix_script_task_injected_vars), so the old
execute_method() replay failed EVERY check with a NameError on `doc` before
the script's logic ran: three "Something went wrong" verdicts on a correct
script, observed live 2026-08-10."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.server_script_api import run_logix_test_case

SCRIPT_NAME = "ZZ Logix Runner Probe"

# The exact style Logix is taught to write: reads the injected doc, throws a
# validation on missing input, writes a record, reports through result.
SCRIPT_BODY = """\
if not doc.employee:
	frappe.throw("Employee is required")
note = frappe.get_doc({"doctype": "Note", "title": "logix check probe", "content": doc.employee})
note.insert(ignore_permissions=True)
result["note"] = note.name
result["employee"] = doc.employee
"""


class TestLogixTestRunner(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("Server Script", SCRIPT_NAME):
			script = frappe.new_doc("Server Script")
			# setattr dodges the class-body name mangling __newname would get here
			setattr(script, "__newname", SCRIPT_NAME)
			script.script_type = "API"
			script.api_method = "zz_logix_runner_probe"
			script.script = SCRIPT_BODY
			script.insert(ignore_permissions=True)

	def test_doc_contract_script_passes_with_sample_doc(self):
		out = run_logix_test_case(
			SCRIPT_NAME, inputs='{"doc": {"employee": "HR-EMP-00001"}}'
		)
		self.assertTrue(out["passed"], out["summary"])
		self.assertEqual(out["result"]["employee"], "HR-EMP-00001")

	def test_validation_stop_is_reported_as_the_scripts_own_message(self):
		out = run_logix_test_case(SCRIPT_NAME, inputs='{"doc": {}}')
		self.assertFalse(out["passed"])
		self.assertIn("Employee is required", out["summary"])

	def test_checks_are_dry_runs(self):
		out = run_logix_test_case(
			SCRIPT_NAME, inputs='{"doc": {"employee": "HR-EMP-00001"}}'
		)
		self.assertTrue(out["passed"])
		# The Note the script inserted was rolled back with the savepoint.
		self.assertFalse(frappe.db.exists("Note", out["result"]["note"]))

	def test_workflow_variables_reach_task_data(self):
		script = frappe.get_doc("Server Script", SCRIPT_NAME)
		script.script = 'result["days"] = task_data.get("days_requested")'
		script.save(ignore_permissions=True)
		out = run_logix_test_case(SCRIPT_NAME, inputs='{"days_requested": 5}')
		self.assertTrue(out["passed"], out["summary"])
		self.assertEqual(out["result"]["days"], 5)
