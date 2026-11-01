"""Field builders for email content.

``build_attachment_links`` turns the files attached to a document into
signed download links that work without an ERPNext session. ``build_field_rows``,
``default_fact_fields`` and ``build_kick`` fill the layout emails' facts, details
and context line.
"""

from __future__ import annotations

from urllib.parse import urlencode

import frappe
from frappe.model import no_value_fields
from frappe.utils import cint, cstr, strip_html

from one_bpmn.utils.token import generate_file_token

DOWNLOAD_METHOD = "/api/method/one_bpmn.api.todo_actions.download_attachment"


def build_attachment_links(doc, expiry_hours: int = 72) -> list[dict]:
	"""Return ``[{file_name, url}]`` for every file attached to ``doc``.

	Args:
		doc: The document whose attachments are linked (needs ``doctype`` and ``name``).
		expiry_hours: Hours until each signed link expires.

	Returns:
		One dict per attached file, oldest first. ``url`` is an absolute signed link.
	"""
	files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": doc.doctype,
			"attached_to_name": doc.name,
			"is_folder": 0,
		},
		fields=["name", "file_name"],
		order_by="creation asc, name asc",
	)

	links = []
	for row in files:
		token = generate_file_token(row.name, doc.doctype, doc.name, expiry_hours)
		links.append(
			{
				"file_name": row.file_name or row.name,
				"url": frappe.utils.get_url(f"{DOWNLOAD_METHOD}?{urlencode({'token': token})}"),
			}
		)
	return links


# Values of these types are formatted for the Arabic half; a paired Arabic field is ignored.
FORMATTED_FIELDTYPES = ("Date", "Datetime", "Time", "Int", "Float", "Currency", "Percent", "Check", "Select")
MAX_FACTS = 6


def build_field_rows(doc, entries: list) -> list[dict]:
	"""Rows of label and value in English and Arabic for the given fieldnames or [fieldname, arabic_fieldname] pairs."""
	rows = []
	for entry in entries:
		fieldname, arabic_fieldname = entry if isinstance(entry, list | tuple) else (entry, "")
		field = _resolve_field(doc, fieldname)
		if not field:
			frappe.log_error(
				title="Email field missing",
				message=f"{fieldname} is not a field of {doc.doctype}, so its row was left out of the email.",
			)
			continue

		df, value = field
		value_en = _format_in(value, df, "en")
		if df.fieldtype in FORMATTED_FIELDTYPES:
			value_ar = _format_in(value, df, "ar")
		else:
			arabic = _resolve_field(doc, arabic_fieldname) if arabic_fieldname else None
			value_ar = _format_in(arabic[1], arabic[0], "ar") if arabic and arabic[1] else value_en
		rows.append(
			{
				"label": {"en": df.label, "ar": frappe._(df.label, lang="ar")},
				"value": {"en": value_en, "ar": value_ar},
			}
		)
	return rows


def default_fact_fields(doctype: str) -> list[str]:
	"""Up to six fields for Key Facts when none are picked: In List View first, then mandatory, in form order."""
	fields = [df for df in frappe.get_meta(doctype).fields if df.fieldtype not in no_value_fields]
	picked = [df.fieldname for df in fields if df.in_list_view]
	picked += [df.fieldname for df in fields if df.reqd and df.fieldname not in picked]
	return picked[:MAX_FACTS]


def build_kick(doctype: str, task_name: str) -> dict:
	"""The context line: DocType label and task name in both languages."""
	from one_bpmn.utils.translation import TranslationError, translate_cached

	try:
		task_name_ar = translate_cached(task_name)
	except TranslationError:
		# translate_text has already logged the failure
		task_name_ar = task_name
	return {
		"en": f"{doctype} · {task_name}",
		"ar": f"{frappe._(doctype, lang='ar')} · {task_name_ar}",
	}


def _resolve_field(doc, fieldname: str):
	"""Return (docfield, value) for a field of doc or link_field.fieldname of a linked document, or None."""
	if "." not in fieldname:
		df = doc.meta.get_field(fieldname)
		return (df, doc.get(fieldname)) if df and df.fieldtype not in no_value_fields else None

	link_fieldname, linked_fieldname = fieldname.split(".", 1)
	link_df = doc.meta.get_field(link_fieldname)
	if not link_df or link_df.fieldtype != "Link":
		return None
	df = frappe.get_meta(link_df.options).get_field(linked_fieldname)
	if not df or df.fieldtype in no_value_fields:
		return None
	link_value = doc.get(link_fieldname)
	value = frappe.db.get_value(link_df.options, link_value, linked_fieldname) if link_value else None
	return df, value


def _format_in(value, df, lang: str) -> str:
	"""Format value by field type with frappe.local.lang set to lang."""
	saved_lang = frappe.local.lang
	frappe.local.lang = lang
	try:
		if df.fieldtype == "Check":
			return frappe._("Yes" if cint(value) else "No")
		return strip_html(cstr(frappe.format_value(value, df)))
	finally:
		frappe.local.lang = saved_lang
