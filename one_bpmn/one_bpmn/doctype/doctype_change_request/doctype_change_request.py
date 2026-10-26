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
	"""List only requests the user raised or can decide as a Process Owner."""
	user = user or frappe.session.user
	if "System Manager" in frappe.get_roles(user):
		return ""
	return (
		f"(`tabDoctype Change Request`.`requested_by` = {frappe.db.escape(user)}"
		f" or `tabDoctype Change Request`.`target_doctype` in ({_owned_listings(user).get_sql()}))"
	)


def has_permission(doc, ptype=None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if "System Manager" in frappe.get_roles(user) or doc.requested_by == user:
		return True
	return doc.target_doctype in _owned_listings(user).run(pluck=True)


def _owned_listings(user: str):
	"""Doctypes listed in the Process Doctypes table of a process the user owns."""
	listing = DocType("Process Doctype")
	process = DocType("Process")
	return (
		frappe.qb.from_(listing)
		.join(process).on(process.name == listing.parent)
		.select(listing.document_type)
		.where((listing.parenttype == "Process") & (process.process_owner == user))
	)
