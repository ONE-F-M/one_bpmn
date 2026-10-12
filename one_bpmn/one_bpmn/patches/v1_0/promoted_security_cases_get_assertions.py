"""Eval cases promoted from a security event before promotion seeded assertions get the same ones now. Idempotent."""

import frappe

from one_bpmn.api.security_events import seed_assertions


def execute():
	for name in frappe.get_all(
		"AI Eval Case", filters={"source_security_event": ["is", "set"]}, pluck="name"
	):
		case = frappe.get_doc("AI Eval Case", name)
		if case.assertions:
			continue
		seed_assertions(case, frappe.get_doc("AI Security Event", case.source_security_event))
		case.save(ignore_permissions=True)
