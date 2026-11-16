"""The Bug Programmer gets no automatic test retry.

Its first test run is meant to fail, because it proves the bug. The retry runs the same
suite again after a failed run, which only repeats that expected failure.
"""

import frappe

AGENT = "Bug Programmer"


def execute():
	if frappe.db.exists("AI Agent Configuration", AGENT):
		frappe.db.set_value("AI Agent Configuration", AGENT, "sandbox_retry_on_test_failure", 0)
