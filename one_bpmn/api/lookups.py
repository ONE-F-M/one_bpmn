# Copyright (c) 2026, one-fm and contributors
"""Field and user lookups for the BPMN editor pickers and the instance list filters."""

import json

import frappe
from frappe import _

# Text fieldtypes that can hold an email address; a Link holds a key, so only a Link to User counts, separately.
_EMAIL_TEXT_FIELDTYPES = ("Data", "Small Text", "Read Only", "Text", "Long Text")


@frappe.whitelist()
def get_assignee_docfields(doctype: str) -> list:
	"""User-linked fields of a Target DocType for the BPMN editor, with owner and modified_by first."""
	if not doctype:
		return []

	try:
		meta = frappe.get_meta(doctype)
	except frappe.DoesNotExistError:
		return []

	res = [
		{"fieldname": "owner", "label": _("Owner")},
		{"fieldname": "modified_by", "label": _("Modified By")},
	]

	for f in meta.get("fields"):
		if f.fieldtype == "Link" and f.options == "User":
			res.append({"fieldname": f.fieldname, "label": f.label})

	return res


@frappe.whitelist()
def get_recipient_docfields(doctype: str, search_text: str = "") -> list:
	"""Fields of *doctype* that can name an email recipient, Custom Fields included.
	kind "user" (owner, modified_by, a Link to User) resolves to that user's email at send time;
	kind "email" is a text field holding an address."""
	if not doctype:
		return []

	try:
		meta = frappe.get_meta(doctype)
	except frappe.DoesNotExistError:
		return []

	# Every table has these and they are not in meta.fields; on many doctypes they are the only recipient.
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


def _looks_like_an_email_field(df) -> bool:
	"""True when a Data or Read Only field's name or label says it holds an email, even without options="Email".
	Longer text types are excluded: a field that mentions email there holds prose, such as a signature."""
	if df.fieldtype not in ("Data", "Read Only"):
		return False
	for text in (df.fieldname or "", df.label or ""):
		if "email" in text.lower() or "e-mail" in text.lower():
			return True
	return False


@frappe.whitelist()
def get_push_recipient_fields(doctype: str, search_text: str = "") -> list:
	"""Recipient fields for a push: the doctype's own, plus "link.user_field" for each Link to a record with a User link."""
	frappe.has_permission("BPMN Process Model", "write", throw=True)
	fields = get_recipient_docfields(doctype)
	for link_df in frappe.get_meta(doctype).fields:
		if link_df.fieldtype != "Link" or link_df.options == "User":
			continue
		for df in frappe.get_meta(link_df.options).fields:
			if df.fieldtype == "Link" and df.options == "User":
				fields.append({
					"fieldname": f"{link_df.fieldname}.{df.fieldname}",
					"label": f"{link_df.label or link_df.fieldname} > {df.label or df.fieldname}",
				})
	needle = search_text.strip().lower()
	return [f for f in fields if needle in f["fieldname"].lower() or needle in f["label"].lower()]


@frappe.whitelist()
def get_system_users(query: str = "", limit: int = 0) -> list:
	"""Active system users matching query for the @mention and user pickers; any logged-in user may call it.
	limit caps the rows returned; 0 returns every match."""
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
	"""Fields of a DocType for the properties panel autocompletes, Custom Fields included, at most 100.
	fieldtype_in and fieldtype_not_in are JSON arrays; with neither, layout fields are left out."""
	if not doctype:
		return []

	include = exclude = None
	if fieldtype_in:
		try:
			include = json.loads(fieldtype_in)
		except (json.JSONDecodeError, TypeError, ValueError):
			frappe.throw(_("Invalid JSON for fieldtype_in filter"))
	elif fieldtype_not_in:
		try:
			exclude = json.loads(fieldtype_not_in)
		except (json.JSONDecodeError, TypeError, ValueError):
			frappe.throw(_("Invalid JSON for fieldtype_not_in filter"))
	else:
		exclude = ["Section Break", "Column Break", "Tab Break", "Table"]

	try:
		meta = frappe.get_meta(doctype)
	except frappe.DoesNotExistError:
		return []

	needle = (search_text or "").strip().lower()
	fields = []
	for df in meta.get("fields") or []:
		if include is not None:
			if df.fieldtype not in include:
				continue
		elif df.fieldtype in exclude:
			continue
		if needle and needle not in (df.fieldname or "").lower():
			continue
		field = {
			"fieldname": df.fieldname,
			"label": df.label or df.fieldname,
			"fieldtype": df.fieldtype,
		}
		if include_options:
			field["options"] = df.options or ""
		fields.append(field)
		if len(fields) == 100:
			break

	return fields


@frappe.whitelist()
def get_email_fields(doctype: str) -> dict:
	"""Fields an email can show: the doctype's own, and per Link field the linked doctype's, with Arabic candidates."""
	from frappe.model import no_value_fields

	from one_bpmn.processa_engine.notifications.fields import FORMATTED_FIELDTYPES

	frappe.has_permission(doctype, "read", throw=True)
	own = [
		(df.fieldname, df) for df in frappe.get_meta(doctype).fields if df.fieldtype not in no_value_fields
	]

	linked = []
	for link_fieldname, link_df in own:
		if link_df.fieldtype != "Link" or not frappe.has_permission(link_df.options, "read"):
			continue
		fields = [
			(f"{link_fieldname}.{df.fieldname}", df)
			for df in frappe.get_meta(link_df.options).fields
			if df.fieldtype not in no_value_fields
		]
		linked.append(
			{
				"link_field": link_fieldname,
				"label": link_df.label,
				"doctype": link_df.options,
				"fields": fields,
			}
		)

	candidates = [
		fieldname
		for fieldname, df in own + [pair for group in linked for pair in group["fields"]]
		if df.fieldtype in ("Data", "Small Text")
		and ("arabic" in df.fieldname or df.fieldname.endswith("_ar"))
	]

	def describe(fieldname, df):
		needs_arabic = df.fieldtype not in FORMATTED_FIELDTYPES
		return {
			"fieldname": fieldname,
			"label": df.label or df.fieldname,
			"fieldtype": df.fieldtype,
			"needs_arabic": needs_arabic,
			"arabic_candidates": candidates if needs_arabic else [],
		}

	return {
		"fields": [describe(*pair) for pair in own],
		"linked": [{**group, "fields": [describe(*pair) for pair in group["fields"]]} for group in linked],
	}


@frappe.whitelist()
def get_doctype_email_thread(doctype: str) -> dict:
	"""Whether a DocType keeps an email thread, and the field that holds the sender's address."""
	frappe.has_permission("BPMN Process Model", "write", throw=True)
	meta = frappe.get_meta(doctype)
	return {"email_append_to": bool(meta.email_append_to), "sender_field": meta.sender_field or ""}


@frappe.whitelist()
def get_context_doctypes(query: str = None) -> list:
	"""Distinct context DocTypes of process instances matching query, for the instance list filter."""
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
	"""Documents of a DocType whose name matches query, for the instance list filter; get_list applies permissions."""
	if not doctype:
		return []

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
