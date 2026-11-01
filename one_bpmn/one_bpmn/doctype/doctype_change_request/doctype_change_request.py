# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A proposed DocType change logged for Process Owner approval.

Created by ``one_bpmn.api.docu_api.apply_doctype`` when the requesting user is
not a Process Owner of any process whose Process Doctypes table lists the
DocType. Applied by ``docu_api.approve_doctype_change``.
"""

import frappe
from frappe.model.document import Document
from frappe.query_builder import DocType


class DoctypeChangeRequest(Document):
	pass


def get_permission_query_conditions(user: str | None = None) -> str:
	"""List only requests the user raised or is an approver for."""
	user = user or frappe.session.user
	if "System Manager" in frappe.get_roles(user):
		return ""
	return (
		f"(`tabDoctype Change Request`.`requested_by` = {frappe.db.escape(user)}"
		f" or `tabDoctype Change Request`.`name` in ({_requests_approvable_by(user).get_sql()}))"
	)


def has_permission(doc, ptype=None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	if "System Manager" in roles or doc.requested_by == user:
		return True
	return any(r.approver == user or r.approver_role in roles for r in doc.get("approvers") or [])


def _requests_approvable_by(user: str):
	"""Names of requests whose approvers table lists the user, or one of their roles."""
	row = DocType("Doctype Change Approver")
	return (
		frappe.qb.from_(row)
		.select(row.parent)
		.where(
			(row.parenttype == "Doctype Change Request")
			& ((row.approver == user) | row.approver_role.isin(frappe.get_roles(user)))
		)
	)
