# Copyright (c) 2026, one-fm and contributors
"""Helpers shared by the Service Task dispatchers."""

import frappe
from frappe.utils import cstr


def cfg_truthy(value) -> bool:
	"""Read a BPMN config value as a boolean: True, 1, "yes", "on" and "enabled" are true."""
	if isinstance(value, bool):
		return value
	if isinstance(value, (int, float)):
		return bool(value)
	return str(value or "").strip().lower() in ("1", "true", "yes", "on", "enabled")


def split_config(value) -> list:
	"""The trimmed, non-empty parts of a comma-separated config value."""
	return [part.strip() for part in cstr(value).split(",") if part.strip()]


def template_renderer(
	instance, error_title: str, doctype: str | None = None, data: dict | None = None, strict: bool = False
):
	"""Load the context document and return (render, jinja context).

	By default an unreadable document becomes an empty one and a failed render keeps the raw text; strict raises both.
	"""
	doctype = doctype or instance.context_doctype
	doc = frappe._dict()
	if doctype and instance.context_docname:
		if strict:
			doc = frappe.get_doc(doctype, instance.context_docname)
		else:
			try:
				doc = frappe.get_doc(doctype, instance.context_docname)
			except Exception:
				doc = frappe._dict()
	jinja_ctx = {"doc": doc, "instance": instance, "frappe": frappe, **(data or {})}

	def render(text):
		if not text:
			return ""
		if strict:
			return frappe.render_template(text, jinja_ctx)
		try:
			return frappe.render_template(text, jinja_ctx)
		except Exception:
			frappe.log_error(title=error_title, message=frappe.get_traceback())
			return text

	return render, jinja_ctx
