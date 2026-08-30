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


# Fieldtypes that can plausibly hold an email address as free text. Link is
# deliberately absent: a Link holds a key, not an address, and the only Link
# worth offering is one pointing at User — handled separately below.
_EMAIL_TEXT_FIELDTYPES = ("Data", "Small Text", "Read Only", "Text", "Long Text")


def _looks_like_an_email_field(df) -> bool:
	"""True when a text field's NAME says it holds an email.

	Frappe marks a proper email field with ``options="Email"``, but that is a
	validation opt-in and plenty of real fields never set it — a doctype that
	stores ``personal_email`` as a bare Data field is ordinary, not broken.
	Excluding those would leave a genuine recipient field unpickable, which is the
	complaint this endpoint exists to fix, so the name is treated as evidence too.

	The cost of a false positive here is one extra row in a picker; the cost of a
	false negative is a field the user cannot select at all. So this leans
	inclusive — but only among field types that could hold an address at all.
	"""
	# Only short field types. A field that MENTIONS email but holds prose — a
	# signature, a template body, an alert subject — is Small Text or Text, and
	# reading its name as an address is how "email_signature" ends up offered as a
	# recipient. An actual address is Data (or Read Only when it is derived).
	if df.fieldtype not in ("Data", "Read Only"):
		return False
	for text in (df.fieldname or "", df.label or ""):
		if "email" in text.lower() or "e-mail" in text.lower():
			return True
	return False


@frappe.whitelist()
def get_recipient_docfields(doctype: str, search_text: str = "") -> list:
	"""Return the fields of *doctype* that can name an email recipient.

	The notification service task used to populate this picker from
	``get_doctype_fields`` filtered only by fieldtype, which was wrong in both
	directions. It offered every Data and Link field — on Visa Request that is 36
	fields including Place of Birth and Passport Number, none of which can hold an
	address — while omitting the two that matter: ``owner`` and ``modified_by`` are
	real columns on every table but are absent from ``meta.fields``, so a picker
	built from the schema can never show them. On a doctype with no user or email
	field of its own, ``owner`` is the ONLY possible recipient, so the one thing
	you needed was the one thing missing.

	Two kinds of field qualify, and the caller is told which is which because they
	behave differently at send time:

	  * ``user``  — ``owner``, ``modified_by``, and any Link to User. Holds a user
	                id, which the dispatcher resolves to that user's email.
	  * ``email`` — a text field holding an address directly.

	Reads through ``frappe.get_meta`` rather than querying ``DocField``, so Custom
	Fields are included. The old query saw only the standard schema, which meant a
	custom email field added to a doctype was invisible here.
	"""
	if not doctype:
		return []

	try:
		meta = frappe.get_meta(doctype)
	except frappe.DoesNotExistError:
		return []

	# Every table has these, and on many doctypes they are the only recipient
	# available. Listed first so the common choice is the obvious one.
	results = [
		{
			"fieldname": "owner",
			"label": _("Owner (created by)"),
			"fieldtype": "Link",
			"options": "User",
			"kind": "user",
		},
		{
			"fieldname": "modified_by",
			"label": _("Last Modified By"),
			"fieldtype": "Link",
			"options": "User",
			"kind": "user",
		},
	]

	for df in meta.get("fields") or []:
		if df.fieldtype == "Link" and df.options == "User":
			kind = "user"
		elif df.fieldtype in _EMAIL_TEXT_FIELDTYPES and (
			(df.options or "") == "Email" or _looks_like_an_email_field(df)
		):
			kind = "email"
		else:
			continue

		results.append({
			"fieldname": df.fieldname,
			"label": df.label or df.fieldname,
			"fieldtype": df.fieldtype,
			"options": df.options or "",
			"kind": kind,
		})

	if search_text:
		needle = str(search_text).strip().lower()
		if needle:
			results = [
				r for r in results
				if needle in r["fieldname"].lower() or needle in (r["label"] or "").lower()
			]

	return results


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
def get_system_users(query: str = "", limit: int = 0) -> list:
	"""
	Fetch active system users for the @mention autocomplete in the BPMN
	comment dialog. Any authenticated (non-Guest) user may call this.
	When query is empty, returns all active system users.

	``limit`` caps the number of rows returned — for a picker that re-queries
	per keystroke and only ever shows the first page, sending every enabled
	user (this site has ~1700) is pure waste. Omitted, the result is unbounded
	as before.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("You must be logged in to fetch system users"))

	normalized_query = (query or "").strip()
	limit = int(limit or 0)

	filters = {
		"enabled": 1,
		"user_type": "System User",
	}

	or_filters = None
	if normalized_query:
		or_filters = {
			"full_name": ["like", f"%{normalized_query}%"],
			"name": ["like", f"%{normalized_query}%"],
		}

	return frappe.get_list("User",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "full_name"],
		order_by="full_name asc",
		limit_page_length=limit or None,
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
		try:
			parsed = json.loads(fieldtype_in)
		except (json.JSONDecodeError, TypeError, ValueError):
			frappe.throw(_("Invalid JSON for fieldtype_in filter"))
		query = query.where(DocField.fieldtype.isin(parsed))
	elif fieldtype_not_in:
		try:
			parsed = json.loads(fieldtype_not_in)
		except (json.JSONDecodeError, TypeError, ValueError):
			frappe.throw(_("Invalid JSON for fieldtype_not_in filter"))
		query = query.where(DocField.fieldtype.notin(parsed))
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
