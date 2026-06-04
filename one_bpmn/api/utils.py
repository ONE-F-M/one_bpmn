# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _


def _is_bpmn_super_user(user: str = None) -> bool:
	"""Return True if *user* holds the Super User Role defined in OneFM General Setting."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	try:
		super_user_role = frappe.db.get_single_value("OneFM General Setting", "super_user_role")
	except Exception:
		return False
	if not super_user_role:
		return False
	return super_user_role in frappe.get_roles(user)


@frappe.whitelist()
def get_assignee_docfields(doctype: str) -> list:
	"""
	Safe endpoint for the BPMN editor to get all User-linked fields
	for a specific Target DocType. Includes standard fields like 'owner'.

	Args:
		doctype: Target DocType name

	Returns:
		list of dicts with fieldname and label
	"""
	if not doctype:
		return []

	# Use frappe.get_meta to get fields safely without querying DocField directly
	try:
		meta = frappe.get_meta(doctype)
	except frappe.DoesNotExistError:
		return []

	# Start with standard User fields available on all DocTypes
	res = [
		{"fieldname": "owner", "label": _("Owner")},
		{"fieldname": "modified_by", "label": _("Modified By")},
	]

	# Add all Link fields pointing to User
	for f in meta.get("fields"):
		if f.fieldtype == "Link" and f.options == "User":
			res.append({"fieldname": f.fieldname, "label": f.label})

	return res


@frappe.whitelist()
def get_workflow_states_for_doctype(doctype: str) -> list:
	"""
	Return the workflow states (name + style) for the Workflow configured on
	the given DocType.  Used by the BPMN editor's Service Task "Apply Workflow"
	properties panel to populate the Workflow State autocomplete.

	Args:
		doctype: The Frappe DocType name (e.g. 'Employee Daily Action')

	Returns:
		list of dicts: [{"state": "Draft", "style": "Danger"}, ...]
		Empty list if no active workflow is configured for the DocType.
	"""
	if not doctype:
		return []

	# Find the active Workflow for this DocType
	workflows = frappe.get_all(
		"Workflow",
		filters={"document_type": doctype, "is_active": 1},
		fields=["name"],
		limit=1,
	)
	if not workflows:
		return []

	workflow_name = workflows[0]["name"]

	# Fetch the workflow states child table
	states = frappe.get_all(
		"Workflow Document State",
		filters={"parent": workflow_name},
		fields=["state", "doc_status", "style", "allow_edit"],
		order_by="idx asc",
	)

	return [
		{
			"state": s.get("state", ""),
			"style": s.get("style", ""),
			"doc_status": s.get("doc_status", ""),
			"allow_edit": s.get("allow_edit", ""),
		}
		for s in states
	]


@frappe.whitelist()
def get_users_by_role(role: str) -> list:
	"""
	Fetch all users who have a specific role.
	"""
	if not role:
		return []

	# Get users who have the specified role
	user_list = frappe.get_all("Has Role", filters={"role": role}, fields=["parent as name"])

	user_names = list(set([u.name for u in user_list]))

	if not user_names:
		return []

	return frappe.get_list(
		"User",
		filters={"name": ["in", user_names], "enabled": 1, "user_type": "System User"},
		fields=["name", "full_name"],
		order_by="full_name asc",
	)


@frappe.whitelist()
def get_system_users(query: str = "") -> list:
	"""
	Fetch active system users for the @mention autocomplete in the BPMN
	comment dialog. Any authenticated (non-Guest) user may call this.
	When query is empty, returns all active system users (up to limit).
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("You must be logged in to fetch system users"))

	normalized_query = (query or "").strip()

	base_filters: list = [
		["User", "enabled", "=", 1],
		["User", "user_type", "=", "System User"],
	]

	if normalized_query:
		# Search both full_name and name (email) — combined safely within the
		# base filter set so enabled/user_type guards always apply.
		base_filters.append([
			"User", "full_name", "like", f"%{normalized_query}%",
			"or",
			"User", "name", "like", f"%{normalized_query}%",
		])

	return frappe.get_list("User",
		filters=base_filters,
		fields=["name", "full_name"],
		order_by="full_name asc",
	)


@frappe.whitelist()
def get_doctype_fields(
	doctype: str,
	search_text: str = "",
	fieldtype_in: str = "",
	fieldtype_not_in: str = "",
	include_options: bool = False,
) -> list:
	"""Return fields for a given DocType.

	Used by the BPMN properties panel to populate field autocompletes.
	Bypasses the parent-permission restriction on the DocField REST API.

	Args:
		doctype: The DocType to fetch fields from.
		search_text: Optional search filter on fieldname.
		fieldtype_in: JSON array of fieldtypes to include (e.g. '["Data","Link"]').
		fieldtype_not_in: JSON array of fieldtypes to exclude.
		include_options: If true, also return the ``options`` column.
	"""
	from frappe.query_builder import DocType as QBDocType

	DocField = QBDocType("DocField")

	select_cols = [DocField.fieldname, DocField.label, DocField.fieldtype]
	if include_options:
		select_cols.append(DocField.options)

	query = (
		frappe.qb.from_(DocField)
		.select(*select_cols)
		.where(DocField.parent == doctype)
		.where(DocField.parenttype == "DocType")
		.orderby(DocField.idx)
		.limit(100)
	)

	if fieldtype_in:
		query = query.where(DocField.fieldtype.isin(json.loads(fieldtype_in)))
	elif fieldtype_not_in:
		query = query.where(DocField.fieldtype.notin(json.loads(fieldtype_not_in)))
	else:
		# Default: exclude layout fields
		query = query.where(
			DocField.fieldtype.notin(
				("Section Break", "Column Break", "Tab Break", "Table")
			)
		)

	if search_text:
		query = query.where(DocField.fieldname.like(f"%{search_text}%"))

	return query.run(as_dict=True)


@frappe.whitelist()
def get_context_doctypes(query: str = None) -> list:
	"""
	Get unique DocTypes used as context in Process Instances, filtered by query.
	Used by the InstanceList filter autocomplete.
	"""
	filters = {}
	if query:
		filters["context_doctype"] = ["like", f"%{query}%"]

	results = frappe.get_all(
		"BPMN Process Instance",
		filters=filters,
		fields=["context_doctype"],
		distinct=True,
		order_by="context_doctype",
		limit=50
	)
	return [{"label": r.context_doctype, "value": r.context_doctype} for r in results if r.context_doctype]


@frappe.whitelist()
def get_context_documents(doctype: str, query: str = None) -> list:
	"""
	Get documents for a specific DocType, filtered by query.
	Used by the InstanceList filter autocomplete.
	"""
	if not doctype:
		return []

	# Use Search Criteria if available, otherwise fallback to name-based filtering
	# get_list respects permissions automatically
	filters = {}
	if query:
		filters["name"] = ["like", f"%{query}%"]

	results = frappe.get_list(
		doctype,
		filters=filters,
		fields=["name"],
		limit=50,
		order_by="modified desc",
	)
	return [{"label": r.name, "value": r.name} for r in results]
