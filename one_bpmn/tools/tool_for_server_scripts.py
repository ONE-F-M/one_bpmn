"""
Read-only Frappe tools for the agent maps' Server Scripts.

Two families live here:

  Server Script tools (Logix) — read and enumerate Server Scripts.
  DocType schema tools (Docu)  — read, diff and validate DocType definitions.

A BPMN AI Agent Task hands these to the LLM by building ``ToolSpec(fn=…)``
inline in its own Server Script, so every ``fn`` must be an importable
module-level function: an AI Agent shape tool runs under SPLIT globals/locals,
where a function defined in the script body cannot see the script's imports.
That is the whole reason this module exists — it holds the callables, while all
agent semantics (prompts, routing, response shaping) live in the map.

``read_doctype_definition`` / ``diff_ir`` / the DOCFIELD_* + DOCTYPE_SETTING_*
attribute tuples are also the IR ⇄ DocField contract used by
``one_bpmn.api.docu_api`` (the DocuCanvas form builder), which is why they are
plain functions returning dicts rather than JSON-string tool wrappers.

They run inside the Frappe request context, so `frappe` is always available.
"""

import json
import frappe

from one_bpmn.security.doctype_validator import validate_doctype_ir


def get_server_script_content(script_name: str) -> str:
	"""
	Fetch the full Python source code of a Frappe Server Script by name.

	Use this tool when the user asks to modify, review, or extend an existing
	Server Script so you can read the current implementation before making changes.

	Args:
		script_name: The exact name (document ID) of the Server Script to fetch.

	Returns:
		The Python script content as a string, or an error message prefixed with
		"# Error:" if the script does not exist or cannot be read.
	"""
	try:
		doc = frappe.get_doc("Server Script", script_name)
		if not doc.script:
			return f"# Script '{script_name}' exists but has no content yet."
		return doc.script
	except frappe.DoesNotExistError:
		return f"# Error: Server Script '{script_name}' not found."
	except frappe.PermissionError:
		return f"# Error: No permission to read Server Script '{script_name}'."
	except Exception:
		frappe.log_error(
			title="Logix Tool - get_server_script_content",
			message=frappe.get_traceback(),
		)
		return f"# Error: Failed to fetch Server Script '{script_name}'."


def get_server_script_meta(script_name: str) -> str:
	"""
	Fetch the metadata (type, doctype, method, disabled status) of a Server Script.

	Use this when you need to understand the script's configuration (e.g. which
	DocType event it's bound to) without reading the full code.

	Args:
		script_name: The exact name (document ID) of the Server Script.

	Returns:
		A JSON string with keys: name, script_type, reference_doctype,
		doctype_event, api_method, disabled.  Returns an error string on failure.
	"""
	try:
		doc = frappe.get_doc("Server Script", script_name)
		return json.dumps({
			"name": doc.name,
			"script_type": doc.script_type,
			"reference_doctype": doc.reference_doctype or "",
			"doctype_event": doc.doctype_event or "",
			"api_method": doc.api_method or "",
			"disabled": bool(doc.disabled),
		})
	except frappe.DoesNotExistError:
		return json.dumps({"error": f"Server Script '{script_name}' not found."})
	except Exception:
		frappe.log_error(
			title="Logix Tool - get_server_script_meta",
			message=frappe.get_traceback(),
		)
		return json.dumps({"error": f"Failed to fetch metadata for '{script_name}'."})


def list_api_server_scripts() -> str:
	"""
	List all enabled API-type Server Scripts available in the system.

	Use this when the user wants to see which scripts already exist, or when
	you want to check whether a script with a similar purpose already exists
	before creating a new one.

	Returns:
		A JSON array of script names (strings), e.g. ["Check Attendance", "Validate Shift"].
		Returns an empty array on failure.
	"""
	try:
		scripts = frappe.get_all(
			"Server Script",
			filters={"script_type": "API", "disabled": 0},
			fields=["name"],
			limit_page_length=100,
			order_by="name asc",
		)
		return json.dumps([s.name for s in scripts])
	except Exception:
		frappe.log_error(
			title="Logix Tool - list_api_server_scripts",
			message=frappe.get_traceback(),
		)
		return json.dumps([])


def get_doctype_fields(doctype: str) -> str:
	"""
	Get the field names and types for a Frappe DocType.

	Use this when the user asks the script to access specific fields on a document
	and you need to confirm the exact field names available on that DocType.

	Args:
		doctype: The DocType name, e.g. "Employee", "Sales Order".

	Returns:
		A JSON array of objects with keys: fieldname, fieldtype, label, reqd.
		Returns an error object on failure.
	"""
	try:
		if not frappe.db.exists("DocType", doctype):
			return json.dumps({"error": f"DocType '{doctype}' does not exist."})

		meta = frappe.get_meta(doctype)
		fields = [
			{
				"fieldname": f.fieldname,
				"fieldtype": f.fieldtype,
				"label": f.label or f.fieldname,
				"reqd": bool(f.reqd),
			}
			for f in meta.fields
			if f.fieldtype not in ("Section Break", "Column Break", "HTML", "Heading")
		]
		return json.dumps(fields)
	except Exception:
		frappe.log_error(
			title="Logix Tool - get_doctype_fields",
			message=frappe.get_traceback(),
		)
		return json.dumps({"error": f"Failed to fetch fields for DocType '{doctype}'."})


# ═══════════════════════════════════════════════════════════════════════════
# DocType schema tools (Docu)
# ═══════════════════════════════════════════════════════════════════════════

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

	Single source of truth for "read the live definition" — used as the MODIFY
	baseline by the Docu map, as the get_doctype_definition tool, and by
	docu_api's form builder. Returns None if the DocType does not exist.
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


def validate_doctype_json(ir: str = "{}") -> str:
	"""Tool wrapper: parse the IR JSON string and run the schema-safety gate."""
	try:
		data = json.loads(ir) if isinstance(ir, str) else ir
	except (json.JSONDecodeError, TypeError, ValueError) as exc:
		return json.dumps({"valid": False, "violations": [f"Not valid JSON: {exc}"], "fix_hints": []})
	return json.dumps(validate_doctype_ir(data))


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
