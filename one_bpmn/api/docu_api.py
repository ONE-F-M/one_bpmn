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

from one_bpmn.agents.google_adk.docu_agent.docu_agent import _read_doctype_ir
from one_bpmn.agents.google_adk.docu_agent.tools import (
	diff_ir,
	DOCFIELD_ATTRS,
	DOCFIELD_FLAGS,
	DOCFIELD_INTS,
	DOCTYPE_SETTING_FLAGS,
	DOCTYPE_SETTING_INTS,
	DOCTYPE_SETTING_STRS,
)
from one_bpmn.security.doctype_validator import validate_doctype_ir

_LAYOUT_FIELDTYPES = ("Section Break", "Column Break", "Tab Break")
_TABLE_FIELDTYPES = ("Table", "Table MultiSelect")

# DocField keys Docu is allowed to write (everything else is ignored) — the same
# attribute set the reader round-trips, so a field's full property set persists.
_DOCFIELD_KEYS = DOCFIELD_ATTRS
_DOCFIELD_FLAGS = DOCFIELD_FLAGS
_DOCFIELD_INTS = DOCFIELD_INTS
# All configurable DocType-level settings, keyed once for extraction/apply.
_DOCTYPE_SETTING_KEYS = DOCTYPE_SETTING_FLAGS + DOCTYPE_SETTING_INTS + DOCTYPE_SETTING_STRS


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
	conversation_name: str = None,
	chat_history: str = None,
	doctype: str = "",
	target_module: str = "",
	process_context=None,   # unannotated on purpose: _parse() accepts a native dict,
	                        # a JSON string, or None — so Frappe's type coercion can
	                        # never reject the wire format (avoids FrappeTypeError).
) -> dict:
	"""Run one Docu chat turn through the BPMN process instance.

	Mirrors ``server_script_api.process_logix_message``: the first turn creates a
	Chat Conversation (agent_mode="Docu"), which spawns the Docu process map's
	instance; every turn is delivered to that instance, which runs the pipeline
	(Build Context → Run Docu Agent → Save Response) and produces the Bot reply.
	The agent is NEVER invoked directly here — the map is the only execution path.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to use Docu."), frappe.PermissionError)
	if not (message or "").strip():
		frappe.throw(_("Message is required"))

	try:
		from one_bpmn.utils.chat_persistence import create_conversation
		from one_bpmn.api.server_script_api import _delegate_to_bpmn_instance

		# First message → create the conversation, which triggers the Docu map and
		# spawns the orchestrating instance (parked at "Waiting for User Message").
		if not conversation_name:
			label = doctype or "DocType"
			conversation_name = create_conversation(
				agent_mode="Docu",
				title=f"Docu: {label}",
				user=frappe.session.user,
			)

		bpmn_result = _delegate_to_bpmn_instance(
			conversation_name,
			message,
			context={
				"doctype": doctype or "",
				"target_module": target_module or "",
				"process_context": _parse(process_context, {}),
			},
		)
		if bpmn_result is None:
			return {
				"intent": "ERROR",
				"response": "The Docu process orchestration isn't running for this conversation. Please reopen the chat.",
				"conversation_name": conversation_name,
				"doctype_ir": None, "diff": None, "options": None, "suggested_name": None,
			}

		bpmn_result["conversation_name"] = conversation_name
		bpmn_result["session_id"] = session_id
		return bpmn_result

	except Exception:
		frappe.log_error(title="Docu chat failed", message=frappe.get_traceback())
		return {
			"intent": "ERROR",
			"response": _(
				"Something went wrong while designing the form. Please try again or rephrase your request."
			),
			"doctype_ir": None, "diff": None, "options": None, "suggested_name": None,
		}


# ═══════════════════════════════════════════════════════════════════════════
# Chat — asynchronous (enqueue + poll)
# ═══════════════════════════════════════════════════════════════════════════
#
# A single Docu turn runs the whole multi-stage agent pipeline (classify →
# write → review → validate, plus repair loops) — a dozen+ sequential LLM
# calls that take 25–50s. Holding one HTTP request open that long makes the
# browser request time out (the generic "Something went wrong"). Instead we
# create the conversation synchronously (fast), enqueue the slow turn on a
# worker, and let the client poll ``docu_chat_status`` for the result.

_TURN_TTL_SEC = 900  # keep a finished turn's result retrievable for 15 min


def _turn_key(turn_id: str) -> str:
	return f"docu_turn::{turn_id}"


@frappe.whitelist()
def docu_chat_async(
	message: str,
	session_id: str = "",
	conversation_name: str = None,
	chat_history: str = None,
	doctype: str = "",
	target_module: str = "",
	process_context=None,   # unannotated on purpose: _parse() accepts a native dict,
	                        # a JSON string, or None — so Frappe's type coercion can
	                        # never reject the wire format (avoids FrappeTypeError).
) -> dict:
	"""Kick off one Docu turn in the background and return a ``turn_id`` to poll.

	The conversation is created here (fast, so the client gets ``conversation_name``
	immediately); the slow BPMN delegation runs in ``_run_docu_turn`` on a worker.
	``chat_history`` is accepted for client parity but, as in ``docu_chat``, is not
	forwarded — the BPMN instance carries the conversation's own history.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to use Docu."), frappe.PermissionError)
	if not (message or "").strip():
		frappe.throw(_("Message is required"))

	from one_bpmn.utils.chat_persistence import create_conversation

	if not conversation_name:
		label = doctype or "DocType"
		conversation_name = create_conversation(
			agent_mode="Docu",
			title=f"Docu: {label}",
			user=frappe.session.user,
		)

	turn_id = frappe.generate_hash(length=14)
	frappe.cache().set_value(_turn_key(turn_id), {"status": "pending"}, expires_in_sec=_TURN_TTL_SEC)

	# enqueue_after_commit → the worker (separate process) only runs once this
	# request's conversation/instance rows are committed and visible to it.
	frappe.enqueue(
		"one_bpmn.api.docu_api._run_docu_turn",
		queue="default",
		timeout=600,
		enqueue_after_commit=True,
		turn_id=turn_id,
		conversation_name=conversation_name,
		message=message,
		context={
			"doctype": doctype or "",
			"target_module": target_module or "",
			"process_context": _parse(process_context, {}),
		},
		user=frappe.session.user,
	)

	return {"conversation_name": conversation_name, "turn_id": turn_id, "status": "pending"}


def _run_docu_turn(turn_id: str, conversation_name: str, message: str, context: dict, user: str) -> None:
	"""Background worker: run the slow BPMN turn and cache the result for polling."""
	key = _turn_key(turn_id)
	try:
		frappe.set_user(user)
		from one_bpmn.api.server_script_api import _delegate_to_bpmn_instance

		bpmn_result = _delegate_to_bpmn_instance(conversation_name, message, context=context)
		if bpmn_result is None:
			result = {
				"intent": "ERROR",
				"response": _("The Docu process orchestration isn't running for this conversation. Please reopen the chat."),
				"conversation_name": conversation_name,
				"doctype_ir": None, "diff": None, "options": None, "suggested_name": None,
			}
		else:
			bpmn_result["conversation_name"] = conversation_name
			result = bpmn_result

		frappe.cache().set_value(key, {"status": "done", "result": result}, expires_in_sec=_TURN_TTL_SEC)
	except Exception:
		frappe.log_error(title="Docu async turn failed", message=frappe.get_traceback())
		frappe.cache().set_value(
			key,
			{"status": "error", "error": _("Something went wrong while designing the form. Please try again or rephrase your request.")},
			expires_in_sec=_TURN_TTL_SEC,
		)


@frappe.whitelist()
def docu_chat_status(turn_id: str) -> dict:
	"""Poll a turn started by ``docu_chat_async``.

	Returns ``{status: 'pending'|'done'|'error'|'unknown'}``; ``done`` carries the
	agent ``result`` dict, ``error`` an ``error`` message. ``unknown`` means the
	turn id is not (or no longer) known — expired, or never started.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to use Docu."), frappe.PermissionError)
	if not (turn_id or "").strip():
		return {"status": "unknown"}
	data = frappe.cache().get_value(_turn_key(turn_id))
	return data or {"status": "unknown"}


# ═══════════════════════════════════════════════════════════════════════════
# Reads
# ═══════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def check_doctype_exists(doctype: str) -> dict:
	exists = bool(doctype) and bool(frappe.db.exists("DocType", doctype))
	custom = bool(frappe.db.get_value("DocType", doctype, "custom")) if exists else False
	return {"exists": exists, "custom": custom}


@frappe.whitelist()
def list_modules() -> list:
	"""Module Def names — for the DocType-settings module picker."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to use Docu."), frappe.PermissionError)
	return frappe.get_all("Module Def", pluck="name", order_by="name asc")


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


def _fld_label(f: dict) -> str:
	return (f.get("label") or f.get("fieldname") or "?") if isinstance(f, dict) else "?"


@frappe.whitelist()
def preview_doctype(ir: str) -> dict:
	"""Read-only preview of what ``apply_doctype`` would do.

	Returns a plain-language ``summary``, a field-level ``diff`` for existing
	DocTypes, any child lists that would be created, and — crucially — a
	``destructive`` flag + ``warnings`` when applying would delete stored data.
	The client shows this before calling ``apply_doctype(confirm=1)``.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to use Docu."), frappe.PermissionError)

	ir_dict = _parse(ir, None)
	if not isinstance(ir_dict, dict):
		return {"valid": False, "violations": [_("Invalid form definition.")]}
	verdict = validate_doctype_ir(ir_dict)
	if not verdict["valid"]:
		return {"valid": False, "violations": verdict["violations"]}

	name = ir_dict["doctype_name"].strip()
	fields = ir_dict.get("fields") or []
	content = [f for f in fields if f.get("fieldtype") not in _LAYOUT_FIELDTYPES]

	child_tables = []
	for f in fields:
		if f.get("fieldtype") in _TABLE_FIELDTYPES and isinstance(f.get("child_fields"), list) and f["child_fields"]:
			opt = (f.get("options") or "").strip()
			if not (opt and frappe.db.exists("DocType", opt)):
				child_tables.append(opt or _child_doctype_name(name, f))

	exists = bool(frappe.db.exists("DocType", name))
	custom = bool(frappe.db.get_value("DocType", name, "custom")) if exists else False
	child_note = (
		" " + _("It also creates {0} linked list(s): {1}.").format(len(child_tables), ", ".join(child_tables))
		if child_tables else ""
	)

	out = {
		"valid": True, "doctype_name": name, "exists": exists, "custom": custom,
		"is_child_table": bool(ir_dict.get("is_child_table")),
		"field_count": len(content), "child_tables": child_tables,
		"destructive": False, "warnings": [], "diff": None,
	}

	if not exists:
		out["action"] = "create"
		out["summary"] = _("Creates a new DocType “{0}” with {1} field(s). Nothing else changes.{2}").format(
			name, len(content), child_note)
	elif custom:
		d = diff_ir(_read_doctype_ir(name) or {}, ir_dict)
		out["action"] = "update"
		out["diff"] = {
			"added": [_fld_label(x) for x in d["added"]],
			"removed": [_fld_label(x) for x in d["removed"]],
			"changed": [c["fieldname"] for c in d["changed"]],
		}
		out["destructive"] = bool(d["removed"])
		out["warnings"] = [_("Removing “{0}” will delete its stored data.").format(_fld_label(r)) for r in d["removed"]]
		parts = []
		if d["added"]:
			parts.append(_("{0} added").format(len(d["added"])))
		if d["changed"]:
			parts.append(_("{0} changed").format(len(d["changed"])))
		if d["removed"]:
			parts.append(_("{0} removed").format(len(d["removed"])))
		out["summary"] = _("Updates the existing DocType “{0}”: {1}.{2}").format(
			name, ", ".join(parts) or _("no field changes"), child_note)
	else:
		try:
			present = {f.fieldname for f in frappe.get_meta(name).fields}
		except Exception:
			present = set()
		new_fields = [f for f in content if (f.get("fieldname") or "") not in present]
		out["action"] = "add_fields"
		out["diff"] = {"added": [_fld_label(x) for x in new_fields], "removed": [], "changed": []}
		out["summary"] = _(
			"Adds {0} new field(s) to the standard DocType “{1}” as Custom Fields. "
			"Existing fields are untouched.{2}").format(len(new_fields), name, child_note)
	return out


# ═══════════════════════════════════════════════════════════════════════════
# Apply
# ═══════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def apply_doctype(ir: str, confirm: int = 0) -> dict:
	"""Create or update a real DocType from a Docu IR.

	- new name              → create a custom DocType (table auto-syncs on insert)
	- existing custom type  → reconcile its fields to the IR (add / update / remove)
	- existing standard type→ add the new fields as Custom Fields (core fields untouched)

	Repeating-list ("Table") fields that define their rows inline via ``child_fields``
	get a child DocType created automatically and wired up.

	``confirm`` must be truthy to proceed when the change would REMOVE fields from an
	existing custom DocType (which drops their stored data). The client calls
	``preview_doctype`` first, shows the user what will happen, then re-calls with
	``confirm=1``.
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
	# The module must be a real Frappe Module — the agent can mistake the business
	# process name for a module. Fall back to ONE BPMN rather than fail on a bogus one.
	if not module or not frappe.db.exists("Module Def", module):
		module = "ONE BPMN"
	is_child = int(bool(ir_dict.get("is_child_table")))
	autoname = (ir_dict.get("autoname") or "").strip()
	fields = ir_dict.get("fields") or []
	settings = _extract_settings(ir_dict)

	# 3) Data-loss guard: block destructive field removals on an existing custom
	#    DocType unless the client explicitly confirmed (via preview_doctype). This
	#    runs BEFORE elevation so the message reaches the user cleanly.
	if (
		not int(confirm or 0)
		and frappe.db.exists("DocType", name)
		and frappe.db.get_value("DocType", name, "custom")
	):
		current = _read_doctype_ir(name) or {}
		removed = diff_ir(current, ir_dict).get("removed") or []
		if removed:
			labels = ", ".join((r.get("label") or r.get("fieldname") or "?") for r in removed)
			frappe.throw(
				_("This change removes {0} field(s) — {1} — and would delete their stored data. "
				  "Confirm the change to proceed.").format(len(removed), labels),
				title=_("Confirm data loss"),
			)

	original_user = frappe.session.user
	child_tables: list[str] = []
	try:
		frappe.set_user("Administrator")
		# Create any inline child DocTypes first and point the Table fields at them.
		child_tables = _ensure_child_doctypes(name, module, fields)
		if not frappe.db.exists("DocType", name):
			action = _create_custom_doctype(name, module, is_child, autoname, fields, settings)
		elif frappe.db.get_value("DocType", name, "custom"):
			action = _reconcile_custom_doctype(name, is_child, autoname, fields, settings)
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
		"child_tables": child_tables,
		"url": f"/app/{frappe.scrub(name).replace('_', '-')}",
	}


def _docfield_dict(field: dict, idx: int) -> dict:
	"""Project a Docu IR field onto the DocField keys Frappe accepts."""
	out = {k: field[k] for k in _DOCFIELD_KEYS if k in field and field[k] not in (None, "")}
	out["idx"] = idx
	# Normalise boolean flags to 0/1 and integer attrs to ints.
	for flag in _DOCFIELD_FLAGS:
		if flag in out:
			out[flag] = int(bool(out[flag]))
	for attr in _DOCFIELD_INTS:
		if attr in out:
			try:
				out[attr] = int(out[attr])
			except (TypeError, ValueError):
				del out[attr]
	return out


def _extract_settings(ir_dict: dict) -> dict:
	"""Pull the DocType-level settings the client sent (only keys actually present)."""
	return {k: ir_dict[k] for k in _DOCTYPE_SETTING_KEYS if k in ir_dict}


def _apply_doctype_settings(doc, settings: dict) -> None:
	"""Set the whitelisted DocType-level attributes on a DocType doc.

	Only ever touches the curated settings keys — never name/module/custom/istable
	(those are handled explicitly by the caller), so a posted IR can't flip a
	DocType to standard or rename it. Frappe validates each on save (e.g. a bad
	title_field), and apply_doctype surfaces the error.
	"""
	if not isinstance(settings, dict):
		return
	for k in DOCTYPE_SETTING_FLAGS:
		if k in settings:
			setattr(doc, k, int(bool(settings[k])))
	for k in DOCTYPE_SETTING_INTS:
		if k in settings:
			try:
				setattr(doc, k, int(settings[k] or 0))
			except (TypeError, ValueError):
				pass
	for k in DOCTYPE_SETTING_STRS:
		if k in settings:
			val = settings[k]
			setattr(doc, k, val.strip() if isinstance(val, str) else (val or ""))


def _uniquify_fieldnames(fields: list) -> list:
	"""Give every field a unique, non-empty fieldname before it reaches Frappe.

	Layout breaks (Section/Column/Tab Break) in the IR carry no fieldname (or a
	generic one). Frappe's own auto-naming derives from the label, so several
	breaks that share a label collide (``Fieldname section_break_section appears
	multiple times``). We assign each break a unique ``section_break_<hash>`` up
	front — the same shape Frappe uses — and defensively de-duplicate any repeated
	data fieldname too. Returns copies; the input dicts are not mutated.
	"""
	seen: set[str] = set()
	out = []
	for f in fields:
		if not isinstance(f, dict):
			continue
		f = dict(f)
		ft = (f.get("fieldtype") or "").strip()
		fn = (f.get("fieldname") or "").strip()
		if ft in _LAYOUT_FIELDTYPES:
			base = frappe.scrub(ft)  # section_break / column_break / tab_break
			if not fn or fn in seen:
				fn = f"{base}_{frappe.generate_hash(length=6)}"
				while fn in seen:
					fn = f"{base}_{frappe.generate_hash(length=6)}"
			f["fieldname"] = fn
		elif fn and fn in seen:
			new = f"{fn}_{frappe.generate_hash(length=4)}"
			while new in seen:
				new = f"{fn}_{frappe.generate_hash(length=4)}"
			fn = new
			f["fieldname"] = fn
		if fn:
			seen.add(fn)
		out.append(f)
	return out


import re as _re


def _child_doctype_name(parent: str, field: dict) -> str:
	"""Derive a child-table DocType name for an inline repeating list."""
	base = f"{parent} {(field.get('label') or field.get('fieldname') or 'Item').strip()}"
	# Frappe DocType names: letters/digits/spaces, start with a letter.
	base = _re.sub(r"[^A-Za-z0-9 ]+", " ", base)
	base = _re.sub(r"\s+", " ", base).strip()
	if not base or not base[0].isalpha():
		base = f"Docu {base}".strip()
	base = base[:55].strip()
	if not base.lower().endswith("item"):
		base = f"{base} Item"[:61].strip()
	return base


def _ensure_child_doctypes(parent: str, module: str, fields: list) -> list:
	"""For each Table/Table MultiSelect field defining rows inline via ``child_fields``,
	create (or reuse) a child DocType and point the field's ``options`` at it.

	Returns the list of child DocType names that were newly created.
	"""
	created = []
	for f in fields:
		if not isinstance(f, dict) or f.get("fieldtype") not in _TABLE_FIELDTYPES:
			continue
		child_fields = f.get("child_fields")
		if not (isinstance(child_fields, list) and child_fields):
			continue
		opt = (f.get("options") or "").strip()
		# An existing target DocType wins — don't clobber it.
		if opt and frappe.db.exists("DocType", opt):
			continue
		child_name = opt or _child_doctype_name(parent, f)
		if not frappe.db.exists("DocType", child_name):
			_create_custom_doctype(child_name, module, 1, "", child_fields)
			created.append(child_name)
		f["options"] = child_name
	return created


def _create_custom_doctype(name: str, module: str, is_child: int, autoname: str, fields: list, settings: dict = None) -> str:
	doc = frappe.get_doc({
		"doctype": "DocType",
		"name": name,
		"module": module,
		"custom": 1,
		"istable": is_child,
		"editable_grid": 1,
		"autoname": autoname or None,
		"fields": [_docfield_dict(f, i + 1) for i, f in enumerate(_uniquify_fieldnames(fields))],
	})
	_apply_doctype_settings(doc, settings)
	doc.custom = 1          # never let a setting flip the custom flag
	doc.istable = is_child  # child-table state is owned by the caller
	if not doc.istable:
		doc.append("permissions", {
			"role": "System Manager",
			"read": 1, "write": 1, "create": 1, "delete": 1,
			"report": 1, "export": 1, "share": 1, "print": 1, "email": 1,
		})
	doc.insert(ignore_permissions=True)
	return "created"


def _reconcile_custom_doctype(name: str, is_child: int, autoname: str, fields: list, settings: dict = None) -> str:
	"""Bring a custom DocType's fields in line with the IR (add / update / remove).

	The IR (seeded from the live schema and echoed back by the writer) is the
	complete desired field set, so we rebuild the child table from it via
	``doc.set`` — Frappe adds/updates/drops the DB columns on save. Only ever
	called for custom DocTypes; standard types go through ``_add_custom_fields``.
	"""
	doc = frappe.get_doc("DocType", name)
	payloads = []
	idx = 0
	for f in _uniquify_fieldnames(fields):
		is_layout = f.get("fieldtype") in _LAYOUT_FIELDTYPES
		if not is_layout and not (f.get("fieldname") or "").strip():
			continue
		idx += 1
		payloads.append(_docfield_dict(f, idx))
	doc.set("fields", payloads)
	_apply_doctype_settings(doc, settings)
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
