"""Permission scoping for DocType.

System Manager sees and edits every DocType. Anyone else, a Process Owner, sees only the DocTypes they created
and the ones listed in the Process Doctypes table of a process they own.
"""

import frappe
from frappe.query_builder import DocType


def _is_unrestricted(user: str) -> bool:
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def _owned_doctypes(user: str):
	"""Subquery of the DocType names listed on processes the user owns."""
	listed = DocType("Process Doctype")
	process = DocType("Process")
	return (
		frappe.qb.from_(listed)
		.join(process).on(process.name == listed.parent)
		.select(listed.document_type)
		.where((listed.parenttype == "Process") & (process.process_owner == user))
	)


def doctype_query_conditions(user: str | None = None) -> str:
	user = user or frappe.session.user
	if _is_unrestricted(user):
		return ""
	return f"(`tabDocType`.`owner` = {frappe.db.escape(user)} or `tabDocType`.`name` in ({_owned_doctypes(user).get_sql()}))"


def doctype_has_permission(doc, ptype: str | None = None, user: str | None = None) -> bool | None:
	user = user or frappe.session.user
	if _is_unrestricted(user) or doc.is_new() or doc.owner == user:
		return None
	return bool(_owned_doctypes(user).where(DocType("Process Doctype").document_type == doc.name).run())
