# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Docu API — the whitelisted surface the DocuCanvas Vue panel calls.

- ``docu_chat``           one chat turn → DocuAgent → structured result dict
- ``get_doctype_schema``  read an existing DocType into the Docu IR (form builder)
- ``check_doctype_exists``{exists, custom}
- ``apply_doctype``       create / update a real (custom) DocType from a Docu IR

SECURITY: ``apply_doctype`` re-runs the schema validator server-side and gates on
the System Manager / DocType-create permission before elevating — the client IR
is never trusted. Elevation uses the ``server_script_api.create_server_script``
template (narrow ``set_user('Administrator')`` inside try/finally).
"""

import json

import frappe
from frappe import _

from one_bpmn.agents.google_adk.docu_agent.docu_agent import run_docu_message, _read_doctype_ir
from one_bpmn.security.doctype_validator import validate_doctype_ir

# DocField keys Docu is allowed to write (everything else is ignored).
_DOCFIELD_KEYS = (
	"fieldname", "label", "fieldtype", "options", "reqd", "unique",
	"in_list_view", "in_standard_filter", "read_only", "hidden", "bold",
	"default", "description", "depends_on", "mandatory_depends_on",
	"read_only_depends_on", "fetch_from", "precision", "non_negative",
)
_DOCFIELD_FLAGS = (
	"reqd", "unique", "in_list_view", "in_standard_filter",
	"read_only", "hidden", "bold", "non_negative",
)


def _parse(value, fallback):
	if value in (None, ""):
		return fallback
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (json.JSONDecodeError, TypeError, ValueError):
		return fallback


# ═══════════════════════════════════════════════════════════════════════════
# Chat
# ═══════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def docu_chat(
	message: str,
	session_id: str = "",
	chat_history: str = None,
	doctype: str = "",
	target_module: str = "",
	process_context: str = None,
) -> dict:
	"""Run one Docu chat turn. Returns the DocuAgent result dict verbatim."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to use Docu."), frappe.PermissionError)
	if not (message or "").strip():
		frappe.throw(_("Message is required"))

	history = _parse(chat_history, [])
	ctx = _parse(process_context, {})

	try:
		result = run_docu_message(
			message=message,
			chat_history=history,
			doctype=doctype or "",
			target_module=target_module or "",
			process_context=ctx,
		)
	except Exception:
		frappe.log_error(title="Docu chat failed", message=frappe.get_traceback())
		return {
			"intent": "ERROR",
			"response": _(
				"Something went wrong while designing the form. Please try again or rephrase your request."
			),
			"doctype_ir": None,
			"diff": None,
			"options": None,
			"suggested_name": None,
		}

	result["session_id"] = session_id
	return result


# ═══════════════════════════════════════════════════════════════════════════
# Reads
# ═══════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def check_doctype_exists(doctype: str) -> dict:
	exists = bool(doctype) and bool(frappe.db.exists("DocType", doctype))
	custom = bool(frappe.db.get_value("DocType", doctype, "custom")) if exists else False
	return {"exists": exists, "custom": custom}


@frappe.whitelist()
def get_doctype_schema(doctype: str) -> dict:
	"""Return an existing DocType as a Docu IR so the form builder can render it.

	Permission-aware: readable meta only. Returns ``{exists: False}`` when absent.
	"""
	if not doctype or not frappe.db.exists("DocType", doctype):
		return {"exists": False, "doctype_ir": None}
	if not frappe.has_permission("DocType", "read"):
		frappe.throw(_("You do not have permission to read this form."), frappe.PermissionError)
	ir = _read_doctype_ir(doctype)
	return {"exists": True, "doctype_ir": ir}


# ═══════════════════════════════════════════════════════════════════════════
# Apply
# ═══════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def apply_doctype(ir: str) -> dict:
	"""Create or update a real DocType from a Docu IR.

	- new name              → create a custom DocType (table auto-syncs on insert)
	- existing custom type  → reconcile its fields to the IR (add / update / remove)
	- existing standard type→ add the new fields as Custom Fields (core fields untouched)
	"""
	ir_dict = _parse(ir, None)
	if not isinstance(ir_dict, dict):
		frappe.throw(_("Invalid form definition."))

	# 1) Server-side safety gate — never trust the client IR.
	verdict = validate_doctype_ir(ir_dict)
	if not verdict["valid"]:
		frappe.throw(_("The form has problems that must be fixed first:<br>") + "<br>".join(verdict["violations"]))

	# 2) Permission gate.
	if "System Manager" not in frappe.get_roles() and not frappe.has_permission("DocType", "create"):
		frappe.throw(
			_("You need the System Manager role to create or change forms."),
			frappe.PermissionError,
		)

	name = ir_dict["doctype_name"].strip()
	module = (ir_dict.get("module") or "ONE BPMN").strip()
	is_child = int(bool(ir_dict.get("is_child_table")))
	autoname = (ir_dict.get("autoname") or "").strip()
	fields = ir_dict.get("fields") or []

	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")
		if not frappe.db.exists("DocType", name):
			action = _create_custom_doctype(name, module, is_child, autoname, fields)
		elif frappe.db.get_value("DocType", name, "custom"):
			action = _reconcile_custom_doctype(name, is_child, autoname, fields)
		else:
			action = _add_custom_fields(name, fields)
		frappe.db.commit()
	except frappe.PermissionError:
		raise
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title=f"Docu apply_doctype failed ({name})", message=frappe.get_traceback())
		frappe.throw(_("Could not apply the form: {0}").format(frappe.get_traceback().splitlines()[-1]))
	finally:
		frappe.set_user(original_user)

	return {
		"name": name,
		"action": action,
		"is_child_table": bool(is_child),
		"url": f"/app/{frappe.scrub(name).replace('_', '-')}",
	}


def _docfield_dict(field: dict, idx: int) -> dict:
	"""Project a Docu IR field onto the DocField keys Frappe accepts."""
	out = {k: field[k] for k in _DOCFIELD_KEYS if k in field and field[k] not in (None, "")}
	out["idx"] = idx
	# Normalise integer flags.
	for flag in _DOCFIELD_FLAGS:
		if flag in out:
			out[flag] = int(bool(out[flag]))
	return out


def _create_custom_doctype(name: str, module: str, is_child: int, autoname: str, fields: list) -> str:
	doc = frappe.get_doc({
		"doctype": "DocType",
		"name": name,
		"module": module,
		"custom": 1,
		"istable": is_child,
		"editable_grid": 1,
		"autoname": autoname or None,
		"fields": [_docfield_dict(f, i + 1) for i, f in enumerate(fields)],
	})
	if not is_child:
		doc.append("permissions", {
			"role": "System Manager",
			"read": 1, "write": 1, "create": 1, "delete": 1,
			"report": 1, "export": 1, "share": 1, "print": 1, "email": 1,
		})
	doc.insert(ignore_permissions=True)
	return "created"


def _reconcile_custom_doctype(name: str, is_child: int, autoname: str, fields: list) -> str:
	"""Bring a custom DocType's fields in line with the IR (add / update / remove).

	The IR (seeded from the live schema and echoed back by the writer) is the
	complete desired field set, so we rebuild the child table from it via
	``doc.set`` — Frappe adds/updates/drops the DB columns on save. Only ever
	called for custom DocTypes; standard types go through ``_add_custom_fields``.
	"""
	doc = frappe.get_doc("DocType", name)
	payloads = []
	idx = 0
	for f in fields:
		is_layout = f.get("fieldtype") in ("Section Break", "Column Break", "Tab Break")
		if not is_layout and not (f.get("fieldname") or "").strip():
			continue
		idx += 1
		payloads.append(_docfield_dict(f, idx))
	doc.set("fields", payloads)
	doc.istable = is_child
	if autoname:
		doc.autoname = autoname
	doc.save(ignore_permissions=True)
	return "updated"


def _add_custom_fields(name: str, fields: list) -> str:
	"""Add only the not-yet-present fields to a STANDARD DocType as Custom Fields.

	Core/standard fields are never modified — this is the non-destructive path.
	"""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	meta = frappe.get_meta(name)
	present = {f.fieldname for f in meta.fields}
	to_add = [
		_docfield_dict(f, i + 1)
		for i, f in enumerate(fields)
		if (f.get("fieldname") or "").strip()
		and f.get("fieldname") not in present
		and f.get("fieldtype") not in ("Section Break", "Column Break", "Tab Break")
	]
	if not to_add:
		return "unchanged"
	create_custom_fields({name: to_add}, ignore_validate=False)
	return "fields_added"
