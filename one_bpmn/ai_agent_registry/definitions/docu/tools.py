"""Docu's tool functions: read, diff and validate DocType definitions in the Docu IR shape.

docu's form builder reads and diffs through the same functions.
"""

import json
import time
from contextlib import contextmanager

import frappe
from frappe.utils import now_datetime

from one_bpmn.ai_agent_registry.definitions.docu.validators import validate_doctype_ir
from one_bpmn.ai_agent_registry.definitions.shared.helpers import tool_envelope


@contextmanager
def timed(timings: list, call: str):
	"""Append when the block started and ended, and its length in ms, to timings."""
	started_at = now_datetime()
	t0 = time.perf_counter()
	try:
		yield
	finally:
		timings.append(
			{
				"call": call,
				"started_at": str(started_at),
				"ended_at": str(now_datetime()),
				"ms": round((time.perf_counter() - t0) * 1000),
			}
		)


@tool_envelope("Docu Tool - list_doctypes", lambda search: json.dumps([]))
def list_doctypes(search: str = "") -> str:
	"""List existing DocTypes (name + module), optionally filtered by *search*."""
	filters = {"istable": 0}
	if search:
		filters["name"] = ["like", f"%{search}%"]
	rows = frappe.get_all(
		"DocType", filters=filters, fields=["name", "module", "custom"],
		order_by="modified desc", limit_page_length=50,
	)
	return json.dumps(rows)


@tool_envelope("Docu Tool - doctype_exists", lambda doctype: json.dumps({"exists": False, "custom": False}))
def doctype_exists(doctype: str) -> str:
	"""Return whether a DocType exists and whether it is a custom DocType."""
	exists = bool(frappe.db.exists("DocType", doctype))
	is_custom = bool(frappe.db.get_value("DocType", doctype, "custom")) if exists else False
	return json.dumps({"exists": exists, "custom": is_custom})


# Field boolean attributes (stored 0/1 in DocField).
DOCFIELD_FLAGS = (
	"reqd", "unique", "in_list_view", "in_standard_filter", "in_global_search",
	"in_preview", "in_filter", "allow_in_quick_entry", "bold", "translatable",
	"fetch_if_empty", "hidden", "read_only", "search_index", "set_only_once",
	"allow_bulk_edit", "ignore_user_permissions", "allow_on_submit", "report_hide",
	"remember_last_selected_value", "ignore_xss_filter", "no_copy", "print_hide",
	"print_hide_if_no_value", "hide_days", "hide_seconds", "non_negative",
	"is_virtual", "sort_options", "show_on_timeline", "make_attachment_public",
	"collapsible",
)
# Field integer attributes.
DOCFIELD_INTS = ("length", "columns", "permlevel")
# Field free-text attributes.
DOCFIELD_STRS = (
	"options", "default", "description", "depends_on", "mandatory_depends_on",
	"read_only_depends_on", "fetch_from", "precision", "print_width", "width",
	"max_height", "documentation_url", "placeholder",
)
# Field attributes Docu carries both ways between the IR and DocField.
DOCFIELD_ATTRS = ("fieldname", "label", "fieldtype") + DOCFIELD_STRS + DOCFIELD_INTS + DOCFIELD_FLAGS

# DocType-level settings Docu can configure, both ways between the IR and DocType.
DOCTYPE_SETTING_FLAGS = (
	"is_submittable", "issingle", "editable_grid", "quick_entry", "track_changes",
	"track_seen", "track_views", "beta", "hide_toolbar", "allow_copy", "allow_rename",
	"allow_import", "allow_events_in_timeline", "allow_auto_repeat", "show_preview_popup",
	"show_name_in_global_search", "show_title_field_in_link", "translated_doctype",
	"make_attachments_public", "is_tree",
)
DOCTYPE_SETTING_INTS = ("max_attachments",)
DOCTYPE_SETTING_STRS = (
	"description", "image_field", "title_field", "search_fields",
	"default_print_format", "sort_field", "sort_order", "document_type",
)

# Every DocPerm right is carried, so writing back a DocType read in never drops one the builder hides.
DOCTYPE_PERMISSION_FLAGS = (
	"select", "read", "write", "create", "delete", "submit", "cancel", "amend",
	"report", "export", "import", "share", "print", "email", "if_owner",
)


def read_doctype_definition(doctype: str) -> dict | None:
	"""An existing DocType in the full Docu IR shape, or None when it does not exist.

	The Docu map, the get_doctype_definition tool and docu's form builder all read through it.
	"""
	if not frappe.db.exists("DocType", doctype):
		return None
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return None
	fields = []
	_layout = ("Section Break", "Column Break", "Tab Break")
	for f in meta.fields:
		# A layout break keeps an empty label, so Customize Form writes no label Property Setter for it.
		label = f.label or ("" if f.fieldtype in _layout else f.fieldname)
		row = {"fieldname": f.fieldname, "fieldtype": f.fieldtype, "label": label}
		for attr in DOCFIELD_ATTRS:
			if attr in ("fieldname", "fieldtype", "label"):
				continue
			val = getattr(f, attr, None)
			if attr in DOCFIELD_FLAGS:
				row[attr] = int(bool(val))
			elif attr in DOCFIELD_INTS:
				row[attr] = int(val or 0)
			else:
				row[attr] = val or ""
		fields.append(row)
	# Imported here because one_bpmn.api.docu imports this module at load time
	from one_bpmn.api.docu import DEFAULT_MODULE

	out = {
		"doctype_name": doctype,
		"module": getattr(meta, "module", DEFAULT_MODULE),
		"is_child_table": int(bool(getattr(meta, "istable", 0))),
		"custom": int(bool(getattr(meta, "custom", 0))),
		"autoname": getattr(meta, "autoname", "") or "",
		"fields": fields,
	}
	for attr in DOCTYPE_SETTING_FLAGS:
		out[attr] = int(bool(getattr(meta, attr, 0)))
	for attr in DOCTYPE_SETTING_INTS:
		out[attr] = int(getattr(meta, attr, 0) or 0)
	for attr in DOCTYPE_SETTING_STRS:
		out[attr] = getattr(meta, attr, "") or ""
	out["permissions"] = read_doctype_permissions(doctype)
	return out


def compact_ir(ir: dict | None) -> dict | None:
	"""The IR without properties that hold 0 or an empty string, for a prompt the model echoes back.

	Applying an IR reads a missing property as its default, so nothing is lost.
	"""
	if not isinstance(ir, dict):
		return ir

	def _set(row: dict) -> dict:
		return {k: v for k, v in row.items() if v not in (0, "", None)}

	out = _set({k: v for k, v in ir.items() if k not in ("fields", "permissions")})
	out["fields"] = [_set(f) for f in ir.get("fields") or []]
	if "permissions" in ir:
		out["permissions"] = [_set(p) for p in ir["permissions"] or []]
	return out


def read_doctype_permissions(doctype: str) -> list:
	"""The permission rules in force, in IR shape: Custom DocPerm when the DocType has any, else DocPerm."""
	source = "Custom DocPerm" if frappe.db.exists("Custom DocPerm", {"parent": doctype}) else "DocPerm"
	filters = {"parent": doctype}
	if source == "DocPerm":
		filters["parenttype"] = "DocType"
	rows = []
	for p in frappe.get_all(
		source,
		filters=filters,
		fields=["role", "permlevel", *DOCTYPE_PERMISSION_FLAGS],
		order_by="idx asc",
	):
		row = {"role": p.get("role") or "", "permlevel": int(p.get("permlevel") or 0)}
		for flag in DOCTYPE_PERMISSION_FLAGS:
			row[flag] = int(bool(p.get(flag)))
		rows.append(row)
	return rows


@tool_envelope(
	"Docu Tool - list_roles", lambda search: json.dumps({"roles": [], "error": "Could not read the role list."})
)
def list_roles(search: str = "") -> str:
	"""Role names a permission rule may name, as JSON, filtered by the search substring."""
	filters = {"disabled": 0, "name": ["not in", ("All", "Guest")]}
	if (search or "").strip():
		filters["name"] = ["like", f"%{search.strip()}%"]
	names = frappe.get_all("Role", filters=filters, pluck="name", order_by="name asc", limit=400)
	return json.dumps({"roles": names})


@tool_envelope(
	"Docu Tool - get_doctype_definition",
	lambda doctype: json.dumps({"error": f"Failed to read DocType '{doctype}'."}),
)
def get_doctype_definition(doctype: str) -> str:
	"""Full definition (every field + all its properties + naming) of a DocType, as JSON."""
	ir = read_doctype_definition(doctype)
	if ir is None:
		return json.dumps({"error": f"DocType '{doctype}' does not exist."})
	return json.dumps(ir)


def validate_doctype_json(ir: str = "{}") -> str:
	"""Tool wrapper: parse the IR JSON string and run the schema-safety gate."""
	try:
		data = json.loads(ir) if isinstance(ir, str) else ir
	except (json.JSONDecodeError, TypeError, ValueError) as exc:
		return json.dumps({"valid": False, "violations": [f"Not valid JSON: {exc}"], "fix_hints": []})
	return json.dumps(validate_doctype_ir(data))


def _field_index(ir: dict) -> dict:
	"""Map fieldname to field dict for the data fields of an IR, layout breaks skipped."""
	out = {}
	for f in (ir.get("fields") or []):
		fn = (f.get("fieldname") or "").strip()
		if fn:
			out[fn] = f
	return out


# Field attributes worth surfacing in a diff (label/type/options/flags).
_DIFF_ATTRS = ("label", "fieldtype", "options", "reqd", "unique", "in_list_view", "read_only", "default")


def diff_ir(original: dict, modified: dict) -> dict:
	"""Field-level diff between two DocType IRs: added, removed, changed and a short summary for a chat bubble."""
	orig = _field_index(original or {})
	new = _field_index(modified or {})

	added = [new[fn] for fn in new if fn not in orig]
	removed = [orig[fn] for fn in orig if fn not in new]
	changed = []
	for fn in new:
		if fn not in orig:
			continue
		before, after = orig[fn], new[fn]
		attr_changes = {}
		for attr in _DIFF_ATTRS:
			b, a = before.get(attr), after.get(attr)
			if (b or "") != (a or "") and b != a:
				attr_changes[attr] = {"from": b, "to": a}
		if attr_changes:
			changed.append({"fieldname": fn, "changes": attr_changes})

	lines = []
	for f in added:
		lines.append(f"+ add field '{f.get('label') or f.get('fieldname')}' ({f.get('fieldtype')})")
	for f in removed:
		lines.append(f"- remove field '{f.get('label') or f.get('fieldname')}'")
	for c in changed:
		attrs = ", ".join(f"{k}: {v['from']!r}→{v['to']!r}" for k, v in c["changes"].items())
		lines.append(f"~ change '{c['fieldname']}' ({attrs})")

	return {"added": added, "removed": removed, "changed": changed, "summary": "\n".join(lines)}
