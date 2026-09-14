"""
WI-000366: whitelisted endpoints backing the AI Memory browser.

Every read goes through frappe.get_list (never frappe.get_all / raw SQL /
ignore_permissions) so the AI Memory permission scoping
(one_bpmn.agents.memory_permissions) applies automatically: a caller sees
their own memories plus memories for processes they own; System Manager sees
everything. Retire/restore go through frappe.get_doc(...).save(), which runs
the doctype's own has_permission("write") check before anything is written.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, now_datetime

# Columns shown in the memory browser's list view.
MEMORY_LIST_FIELDS = [
	"name",
	"content",
	"memory_scope",
	"agent_element",
	"process_model",
	"reference_doctype",
	"reference_name",
	"source_type",
	"confidence",
	"importance",
	"corroboration_count",
	"last_corroborated",
	"creation",
	"expires_on",
	"source_run",
]

# Full detail fields for a single memory (superset of the list fields).
MEMORY_DETAIL_FIELDS = MEMORY_LIST_FIELDS + [
	"user",
	"dedup_key",
	"metadata",
	"user_directed",
]

_SOURCE_RUN_FIELDS = [
	"name", "bpmn_id", "bpmn_label", "status", "backend", "provider", "model",
	"started_at", "ended_at",
]


def _scope_key(row: dict) -> str:
	"""The one scope-key value to display for ``row``, picked from whichever
	field is populated for that row's memory_scope."""
	scope = row.get("memory_scope")
	if scope == "Agent":
		return row.get("agent_element") or ""
	if scope == "Process":
		return row.get("process_model") or ""
	if scope == "Entity":
		ref_doctype = row.get("reference_doctype") or ""
		ref_name = row.get("reference_name") or ""
		if ref_doctype or ref_name:
			return f"{ref_doctype}: {ref_name}"
		return ""
	return ""


def _with_scope_key(rows: list[dict]) -> list[dict]:
	for row in rows:
		row["scope_key"] = _scope_key(row)
	return rows


def _build_filters(
	scope: str, agent_element: str, process_model: str, source_type: str, text: str
) -> list:
	filters: list = []
	if scope:
		filters.append(["memory_scope", "=", scope])
	if agent_element:
		filters.append(["agent_element", "=", agent_element])
	if process_model:
		filters.append(["process_model", "=", process_model])
	if source_type:
		filters.append(["source_type", "=", source_type])
	if text:
		filters.append(["content", "like", f"%{text}%"])
	return filters


def _not_retired_or_filters() -> list:
	"""OR-group excluding retired rows: no expiry set, or the expiry is still
	in the future. ANDed with everything else via frappe.get_list's
	``or_filters`` parameter."""
	return [["expires_on", "is", "not set"], ["expires_on", ">", now_datetime()]]


@frappe.whitelist()
def list_memories(
	text: str = "",
	scope: str = "",
	agent_element: str = "",
	process_model: str = "",
	source_type: str = "",
	include_retired: bool = False,
	start: int = 0,
	page_length: int = 20,
) -> dict:
	"""Paged, filtered list of AI Memory rows for the memory browser.

	``text`` searches ``content`` (substring). ``include_retired`` defaults to
	False: rows whose ``expires_on`` has already passed are hidden unless the
	caller asks to see them. Permission scoping happens inside frappe.get_list
	via memory_permissions.memory_query_conditions.
	"""
	filters = _build_filters(scope, agent_element, process_model, source_type, text)
	or_filters = None if cint(include_retired) else _not_retired_or_filters()

	total_rows = frappe.get_list(
		"AI Memory",
		filters=filters,
		or_filters=or_filters,
		fields=["count(name) as total"],
	)
	total = total_rows[0]["total"] if total_rows else 0

	rows = frappe.get_list(
		"AI Memory",
		filters=filters,
		or_filters=or_filters,
		fields=MEMORY_LIST_FIELDS,
		order_by="creation desc",
		limit_start=cint(start),
		limit_page_length=cint(page_length) or 20,
	)
	_with_scope_key(rows)

	return {"memories": rows, "total": cint(total)}


@frappe.whitelist()
def get_memory(name: str) -> dict:
	"""Full metadata for one memory, plus its source run's own details (when
	the caller may see that run \u2014 AI Agent Run is System-Manager-only, so a
	memory with a source_run the caller cannot read simply omits the detail
	rather than failing the whole request).
	"""
	doc = frappe.get_doc("AI Memory", name)
	doc.check_permission("read")

	source_run_details = None
	if doc.source_run:
		runs = frappe.get_list(
			"AI Agent Run", filters={"name": doc.source_run}, fields=_SOURCE_RUN_FIELDS
		)
		source_run_details = runs[0] if runs else None

	data = {field: doc.get(field) for field in MEMORY_DETAIL_FIELDS}
	data["scope_key"] = _scope_key(data)
	data["source_run_details"] = source_run_details
	return data


def _distinct_values(fieldname: str) -> list:
	rows = frappe.get_list(
		"AI Memory",
		filters=[[fieldname, "is", "set"]],
		fields=[fieldname],
		distinct=True,
		order_by=f"{fieldname} asc",
		limit_page_length=0,
	)
	return [r[fieldname] for r in rows]


@frappe.whitelist()
def get_filter_options() -> dict:
	"""Distinct agents, processes and source types the caller may filter on,
	for the browser's dropdowns. Scoped by the same permission conditions as
	``list_memories`` \u2014 a value nobody has stored a visible memory under
	never appears."""
	return {
		"scopes": ["Agent", "Process", "Entity"],
		"agents": _distinct_values("agent_element"),
		"processes": _distinct_values("process_model"),
		"source_types": _distinct_values("source_type"),
	}


@frappe.whitelist()
def retire_memory(name: str) -> None:
	"""Soft-retire a memory: set expires_on to now. The row is kept, not
	deleted, so it stays visible with include_retired=True."""
	doc = frappe.get_doc("AI Memory", name)
	doc.check_permission("write")
	doc.expires_on = now_datetime()
	doc.save()


@frappe.whitelist()
def restore_memory(name: str) -> None:
	"""Undo a retire: clear expires_on so the memory is live again."""
	doc = frappe.get_doc("AI Memory", name)
	doc.check_permission("write")
	doc.expires_on = None
	doc.save()
