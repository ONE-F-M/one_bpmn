"""
Endpoints behind the Processa memory browser at ``/processa/memory``.

Reading is scoped by the ``AI Memory`` permission hooks
(``agents.memory.permissions``), so every query here goes through
``frappe.get_list`` and inherits the rule instead of restating it. Nothing in
this module passes ``ignore_permissions``.

Two actions are offered on a memory, and the difference matters:

- **Retire** sets ``expires_on`` to now. The row stays, its history stays, and
  it stops being recalled. This is the everyday action, and it is what the
  nightly prune does on its own.
- **Delete** removes the row for good. Rare, and it belongs to the purge story.

Reading somebody else's memories is itself a privacy event, so a listing that
returns rows belonging to anyone other than the reader is written to Frappe's
own ``Access Log``. A person listing only their own memories is not logged:
that is a page refresh, not a disclosure, and logging it would bury the events
that matter under noise.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from one_bpmn.agents.memory.permissions import is_system_manager

# A page of memories. The browser offers 20/50/100; anything larger is a report,
# not a page someone reads.
MAX_PAGE_LENGTH = 100

LIST_FIELDS = (
	"name",
	"content",
	"memory_scope",
	"agent_element",
	"process_model",
	"reference_doctype",
	"reference_name",
	"user",
	"importance",
	"source_type",
	"confidence",
	"corroboration_count",
	"last_corroborated",
	"user_directed",
	"expires_on",
	"modified",
	"creation",
)


def _scope_key_label(row: dict) -> str:
	"""What this memory is keyed on, as one readable string, because the key is
	polymorphic and three separate mostly-empty columns read badly in a table."""
	scope = row.get("memory_scope")
	if scope == "Process":
		return row.get("process_model") or ""
	if scope == "Entity":
		doctype, name = row.get("reference_doctype"), row.get("reference_name")
		return f"{doctype} {name}".strip() if doctype else ""
	return row.get("agent_element") or ""


def _is_retired(row: dict, now) -> bool:
	expires_on = row.get("expires_on")
	return bool(expires_on and expires_on <= now)


def _shape(row: dict, now) -> dict:
	row = dict(row)
	row["scope_key"] = _scope_key_label(row)
	row["retired"] = _is_retired(row, now)
	row["owner_label"] = row.get("user") or _("Shared")
	return row


def _log_read(filters: dict, rows: list[dict]) -> None:
	"""Record a listing that returned somebody else's memories. Never raises:
	an audit failure must not take the page down with it."""
	me = frappe.session.user
	others = sorted({r.get("user") for r in rows if r.get("user") and r.get("user") != me})
	if not others:
		return
	try:
		from frappe.core.doctype.access_log.access_log import make_access_log

		make_access_log(
			doctype="AI Memory",
			method="memory_browser_list",
			filters=json.dumps({"filters": filters, "users_read": others, "rows": len(rows)}),
		)
	except Exception:
		frappe.log_error(title="AI Memory browser: read not logged", message=frappe.get_traceback())


@frappe.whitelist()
def list_memories(
	search: str | None = None,
	memory_scope: str | None = None,
	agent_element: str | None = None,
	user: str | None = None,
	source_type: str | None = None,
	include_retired: int | bool = 0,
	start: int = 0,
	page_length: int = 20,
) -> dict:
	"""A page of memories the caller may read, newest first.

	``include_retired`` is off by default so expired and pruned rows stay out of
	the way without being hidden for good. ``user`` filters to one person's
	memories and is what a System Manager uses before purging them; it cannot
	widen what the caller may see, because the permission hook still applies.
	"""
	page_length = min(max(cint(page_length) or 20, 1), MAX_PAGE_LENGTH)
	start = max(cint(start), 0)

	filters: list = []
	if memory_scope:
		filters.append(["memory_scope", "=", memory_scope])
	if agent_element:
		filters.append(["agent_element", "=", agent_element])
	if source_type:
		filters.append(["source_type", "=", source_type])
	if user:
		# "Shared" is the browser's word for a row with no user; the column holds
		# NULL on rows written before the field existed and "" on newer ones.
		filters.append(["user", "in", ["", None]] if user == "Shared" else ["user", "=", user])
	if search:
		filters.append(["content", "like", f"%{search}%"])
	if not cint(include_retired):
		filters.append(["expires_on", "is", "not set"])

	rows = frappe.get_list(
		"AI Memory",
		filters=filters,
		fields=list(LIST_FIELDS),
		order_by="modified desc",
		limit_start=start,
		limit_page_length=page_length,
	)
	total = frappe.get_list("AI Memory", filters=filters, limit_page_length=0, as_list=True)

	applied = {
		"search": search,
		"memory_scope": memory_scope,
		"agent_element": agent_element,
		"user": user,
		"source_type": source_type,
		"include_retired": bool(cint(include_retired)),
	}
	_log_read(applied, rows)

	now = now_datetime()
	return {
		"memories": [_shape(r, now) for r in rows],
		"total": len(total),
		"start": start,
		"page_length": page_length,
		"can_see_everyone": is_system_manager(),
	}


@frappe.whitelist()
def get_memory(name: str) -> dict:
	"""One memory in full, for the detail drawer. ``get_doc`` plus
	``check_permission`` applies the same rule as the listing."""
	doc = frappe.get_doc("AI Memory", name)
	doc.check_permission("read")
	_log_read({"name": name}, [{"user": doc.user}])

	metadata = None
	if doc.metadata:
		try:
			metadata = json.loads(doc.metadata)
		except (ValueError, TypeError):
			metadata = {"raw": doc.metadata}

	now = now_datetime()
	row = _shape(doc.as_dict(), now)
	row["metadata"] = metadata
	row["source_run"] = doc.source_run
	row["dedup_key"] = doc.dedup_key
	return row


@frappe.whitelist()
def filter_options() -> dict:
	"""The values actually present in the memories the caller may read, so the
	filters offer what is there instead of every value the schema allows."""
	rows = frappe.get_list(
		"AI Memory",
		fields=["memory_scope", "agent_element", "source_type", "user"],
		limit_page_length=0,
	)
	return {
		"scopes": sorted({r["memory_scope"] for r in rows if r.get("memory_scope")}),
		"agents": sorted({r["agent_element"] for r in rows if r.get("agent_element")}),
		"source_types": sorted({r["source_type"] for r in rows if r.get("source_type")}),
		"users": ["Shared", *sorted({r["user"] for r in rows if r.get("user")})],
	}


@frappe.whitelist()
def retire_memory(name: str) -> dict:
	"""Stop a memory being recalled, keeping the row and its history.

	Saved through the document, not ``db.set_value``, so the change lands
	as a Frappe Version, which is the same way reconciliation and the nightly
	prune retire a memory. Already-retired is not an error; it is the state the
	caller asked for.
	"""
	doc = frappe.get_doc("AI Memory", name)
	doc.check_permission("write")
	if doc.expires_on and doc.expires_on <= now_datetime():
		return {"name": doc.name, "retired": True, "already": True}

	metadata = {}
	if doc.metadata:
		try:
			metadata = json.loads(doc.metadata) or {}
		except (ValueError, TypeError):
			metadata = {}
	stamp = now_datetime()
	metadata["retired"] = {"by": frappe.session.user, "on": str(stamp)}
	doc.metadata = json.dumps(metadata)
	doc.expires_on = stamp
	doc.save(ignore_version=False)
	return {"name": doc.name, "retired": True, "already": False}


@frappe.whitelist()
def restore_memory(name: str) -> dict:
	"""Undo a retirement. The row was never deleted, so putting it back into
	circulation is clearing one field. Without this, Retire is as final as
	delete from the reader's point of view, which is not what it means."""
	doc = frappe.get_doc("AI Memory", name)
	doc.check_permission("write")

	metadata = {}
	if doc.metadata:
		try:
			metadata = json.loads(doc.metadata) or {}
		except (ValueError, TypeError):
			metadata = {}
	metadata.pop("retired", None)
	metadata.pop("pruned", None)
	doc.metadata = json.dumps(metadata) if metadata else None
	doc.expires_on = None
	doc.save(ignore_version=False)
	return {"name": doc.name, "retired": False}
