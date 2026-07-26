# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Docu (DocType builder) deterministic tools.

Mirrors the Logix tools.py layout: the LLM-reasoning steps (classify / clarify /
write schema / review) stay in the orchestrator, while the deterministic pieces
live here as the single source of truth shared with any future multi-turn loop:

    validate_ir      schema-safety gate + actionable fix hints
    diff_ir          human-readable field-level diff of two DocType IRs
    extract_json     pull the first JSON object out of an LLM response

Read ToolSpecs (list_doctypes / get_doctype_fields / doctype_exists) are handed
to the schema_writer/clarifier sub-agents so they can inspect the live schema
before proposing changes. Core functions return plain dicts/strings (ergonomic
for tests); ToolSpec wrappers JSON-encode results to match the tool-result
convention used across ``agents/`` (see script_task_agent/tools.py).
"""

from __future__ import annotations

import json

import frappe

from one_bpmn.agents.llm_provider.base import ToolSpec
from one_bpmn.security.doctype_validator import validate_doctype_ir as _validate_doctype_ir
from one_bpmn.tools.tool_for_server_scripts import get_doctype_fields as _get_doctype_fields


# ── Deterministic transforms ────────────────────────────────────────────────
def validate_ir(ir: dict) -> dict:
	"""Schema-safety gate. Returns ``{valid, violations, fix_hints}``."""
	return _validate_doctype_ir(ir)


def _field_index(ir: dict) -> dict:
	"""Map fieldname → field dict for the data fields of an IR (layout breaks skipped)."""
	out = {}
	for f in (ir.get("fields") or []):
		fn = (f.get("fieldname") or "").strip()
		if fn:
			out[fn] = f
	return out


# Field attributes worth surfacing in a diff (label/type/options/flags).
_DIFF_ATTRS = ("label", "fieldtype", "options", "reqd", "unique", "in_list_view", "read_only", "default")


def diff_ir(original: dict, modified: dict) -> dict:
	"""Field-level diff between two DocType IRs.

	Returns ``{added, removed, changed, summary}`` where ``changed`` items carry
	the per-attribute before/after. ``summary`` is a compact human-readable list
	suitable for a chat bubble.
	"""
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


def extract_json(response: str) -> dict:
	"""Pull the first JSON object from an LLM response (fenced or bare)."""
	import re

	text = (response or "").strip()
	fence = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", text)
	if fence:
		return json.loads(fence.group(1).strip())
	try:
		return json.loads(text)
	except (json.JSONDecodeError, ValueError):
		pass
	brace = re.search(r"\{[\s\S]*\}", text)
	if brace:
		return json.loads(brace.group(0))
	raise ValueError(f"No JSON object found in LLM response: {text[:200]}")


# ── Read helpers (backing the ToolSpecs) ─────────────────────────────────────
def list_doctypes(search: str = "") -> str:
	"""List existing DocTypes (name + module), optionally filtered by *search*."""
	try:
		filters = {"istable": 0}
		if search:
			filters["name"] = ["like", f"%{search}%"]
		rows = frappe.get_all(
			"DocType", filters=filters, fields=["name", "module", "custom"],
			order_by="modified desc", limit_page_length=50,
		)
		return json.dumps(rows)
	except Exception:
		frappe.log_error(title="Docu Tool - list_doctypes", message=frappe.get_traceback())
		return json.dumps([])


def doctype_exists(doctype: str) -> str:
	"""Return whether a DocType exists and whether it is a custom DocType."""
	try:
		exists = bool(frappe.db.exists("DocType", doctype))
		is_custom = bool(frappe.db.get_value("DocType", doctype, "custom")) if exists else False
		return json.dumps({"exists": exists, "custom": is_custom})
	except Exception:
		frappe.log_error(title="Docu Tool - doctype_exists", message=frappe.get_traceback())
		return json.dumps({"exists": False, "custom": False})


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
# Field attributes Docu understands and carries end-to-end (IR ⇄ DocField).
DOCFIELD_ATTRS = ("fieldname", "label", "fieldtype") + DOCFIELD_STRS + DOCFIELD_INTS + DOCFIELD_FLAGS

# ── DocType-level settings Docu can configure (IR ⇄ DocType) ─────────────────
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


def read_doctype_definition(doctype: str) -> dict | None:
	"""Read an existing DocType into the full Docu IR shape (all field properties).

	Single source of truth for "read the live definition" — used both as the
	MODIFY baseline (docu_agent) and as the get_doctype_definition tool.
	Returns None if the DocType does not exist.
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
		# Layout breaks carry no real label — don't fall back to the fieldname,
		# or a round-trip through Customize Form would emit spurious label
		# Property Setters (e.g. label "column_break_4").
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
	out = {
		"doctype_name": doctype,
		"module": getattr(meta, "module", "ONE BPMN"),
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
	return out


def get_doctype_definition(doctype: str) -> str:
	"""Full definition (every field + all its properties + naming) of a DocType, as JSON."""
	try:
		ir = read_doctype_definition(doctype)
		if ir is None:
			return json.dumps({"error": f"DocType '{doctype}' does not exist."})
		return json.dumps(ir)
	except Exception:
		frappe.log_error(title="Docu Tool - get_doctype_definition", message=frappe.get_traceback())
		return json.dumps({"error": f"Failed to read DocType '{doctype}'."})


# ── Read ToolSpecs (handed to the writer/clarifier sub-agents) ───────────────
TOOL_LIST_DOCTYPES = ToolSpec(
	fn=list_doctypes,
	name="list_doctypes",
	description="List existing DocTypes (name, module, custom flag). Optionally filter by a search term.",
	parameters={"search": {"type": "string", "description": "Optional substring to filter DocType names."}},
	required=[],
)
TOOL_GET_DOCTYPE_FIELDS = ToolSpec(
	fn=_get_doctype_fields,
	name="get_doctype_fields",
	description="Get the existing fields (fieldname, fieldtype, label, reqd) of a DocType. Use before modifying one.",
	parameters={"doctype": {"type": "string", "description": "The exact DocType name, e.g. 'Employee'."}},
	required=["doctype"],
)
TOOL_GET_DOCTYPE_DEFINITION = ToolSpec(
	fn=get_doctype_definition,
	name="get_doctype_definition",
	description=(
		"Get the COMPLETE definition of a DocType — every field with all its properties "
		"(options, reqd, unique, in_list_view, read_only, hidden, default, depends_on, "
		"fetch_from, precision, ...) plus naming. Use this before modifying a DocType so you "
		"preserve existing field properties exactly."
	),
	parameters={"doctype": {"type": "string", "description": "The exact DocType name, e.g. 'Employee'."}},
	required=["doctype"],
)
TOOL_DOCTYPE_EXISTS = ToolSpec(
	fn=doctype_exists,
	name="doctype_exists",
	description=(
		"Check whether a DocType exists and whether it is a custom DocType. Returns {exists, custom}. "
		"Call this on the 'options' of every Link/Table field to confirm the target really exists."
	),
	parameters={"doctype": {"type": "string", "description": "The DocType name to check."}},
	required=["doctype"],
)


def _validate_doctype_tool(ir: str = "{}") -> str:
	"""Tool wrapper: parse the IR JSON string and run the schema-safety gate."""
	try:
		data = json.loads(ir) if isinstance(ir, str) else ir
	except (json.JSONDecodeError, TypeError, ValueError) as exc:
		return json.dumps({"valid": False, "violations": [f"Not valid JSON: {exc}"], "fix_hints": []})
	return json.dumps(validate_ir(data))


TOOL_VALIDATE_DOCTYPE = ToolSpec(
	fn=_validate_doctype_tool,
	name="validate_doctype",
	description=(
		"Validate a DocType definition (JSON) against the schema-safety rules. "
		"Returns {valid, violations, fix_hints}. Call this on your design before you finalize it, "
		"and fix any violations it reports."
	),
	parameters={"ir": {"type": "string", "description": "The DocType definition as a JSON object string."}},
	required=["ir"],
)

# Sub-agent tool bundles.
# The classifier grounds intent in reality: it checks whether a named DocType
# actually exists (CREATE vs MODIFY) and can look one up by keyword.
CLASSIFIER_TOOLS = [TOOL_DOCTYPE_EXISTS, TOOL_LIST_DOCTYPES]
WRITER_TOOLS = [
	TOOL_GET_DOCTYPE_DEFINITION, TOOL_GET_DOCTYPE_FIELDS,
	TOOL_DOCTYPE_EXISTS, TOOL_LIST_DOCTYPES, TOOL_VALIDATE_DOCTYPE,
]
CLARIFIER_TOOLS = [TOOL_LIST_DOCTYPES, TOOL_DOCTYPE_EXISTS]
REVIEWER_TOOLS = [TOOL_GET_DOCTYPE_DEFINITION, TOOL_DOCTYPE_EXISTS, TOOL_VALIDATE_DOCTYPE]

# Full surface (for any future multi-turn loop).
DOCU_TOOLS: list = [
	TOOL_LIST_DOCTYPES,
	TOOL_GET_DOCTYPE_FIELDS,
	TOOL_GET_DOCTYPE_DEFINITION,
	TOOL_DOCTYPE_EXISTS,
	TOOL_VALIDATE_DOCTYPE,
]
