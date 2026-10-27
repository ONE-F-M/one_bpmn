# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Give each Pending Doctype Change Request the approvers table it did not have when logged."""

import frappe

from one_bpmn.api.docu_api import _approvers_for


def execute():
	for name in frappe.get_all("Doctype Change Request", filters={"status": "Pending"}, pluck="name"):
		request = frappe.get_doc("Doctype Change Request", name)
		if request.approvers:
			continue
		for row in _approvers_for(request.target_doctype):
			request.append("approvers", row)
		request.save(ignore_permissions=True)
