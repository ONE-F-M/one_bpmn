# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Docu API — the whitelisted surface the DocuCanvas Vue panel calls.

- ``docu_chat``           one chat turn → the generic agent path → structured result dict
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

from one_bpmn.security.rate_limit import RateLimited
from frappe import _

from one_bpmn.tools.tool_for_server_scripts import (
	diff_ir,
	DOCFIELD_ATTRS,
	DOCFIELD_FLAGS,
	DOCFIELD_INTS,
	DOCTYPE_SETTING_FLAGS,
	DOCTYPE_SETTING_INTS,
	DOCTYPE_SETTING_STRS,
	read_doctype_definition as _read_doctype_ir,
)
from one_bpmn.security.doctype_validator import RESERVED_FIELDNAMES, validate_doctype_ir

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
	"""Run one Docu chat turn through the generic agent path (WI-001539).

	Docu chat is no longer orchestrated here: this endpoint is a thin alias that
	opens the conversation with ``create_agent_conversation`` and hands the turn to
	``invoke_agent("docu_agent", …)``, exactly like every other configured agent
	(and like ``process_logix_message`` / ``prosally_chat``). Its only remaining job
	is the DocuCanvas panel's request/response contract — the editor state it sends
	and the ``{intent, response, conversation_name, doctype_ir, diff, …}`` reply it
	consumes. Because the ``docu_agent`` configuration links the Docu process map,
	``invoke_agent`` selects the ``bpmn_map`` runner and the map still performs all
	the work (Save User Message → Run Docu Agent → Save Response), so behavior is
	unchanged. The schema helpers below (preview/apply/read) are untouched.

	This synchronous variant is retained for parity; DocuCanvas uses the async
	``docu_chat_async``/``docu_chat_status`` pair because a Docu turn runs 25–50s.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to use Docu."), frappe.PermissionError)
	if not (message or "").strip():
		frappe.throw(_("Message is required"))

	try:
		from one_bpmn.api.agent_invocation import invoke_agent
		from one_bpmn.utils.chat_persistence import create_agent_conversation

		# First turn → open the conversation (stamped with the agent's chat mode
		# label "Docu"), which arms the process map's conditional start trigger and
		# spawns the orchestrating instance. Created here (rather than letting
		# invoke_agent create it) to preserve the "Docu: <label>" title.
		if not conversation_name:
			label = doctype or "DocType"
			conversation_name = create_agent_conversation(
				"docu_agent", title=f"Docu: {label}", user=frappe.session.user
			)

		try:
			result = invoke_agent(
				"docu_agent",
				message,
				conversation=conversation_name,
				context={
					"doctype": doctype or "",
					"target_module": target_module or "",
					"process_context": _parse(process_context, {}),
				},
			)
		except RateLimited as exc:
			# WI-001968: a throttle or a conversation freeze is a real, explainable
			# refusal — not a dead instance. RateLimited subclasses ValidationError,
			# so without this branch the handler below rewrites it as "orchestration
			# isn't running" and the user is told to reopen a chat that is working
			# perfectly. Surface what actually happened, in the chat bubble.
			return {
				"intent": "BLOCKED",
				"response": str(exc),
				"conversation_name": conversation_name,
				"doctype_ir": None, "diff": None, "options": None, "suggested_name": None,
			}
		except frappe.ValidationError:
			# No instance is driving this conversation (map never armed or the
			# instance died) — the generic runner throws; surface the same reopen
			# guidance the panel showed before, over a 200 response.
			return {
				"intent": "ERROR",
				"response": "The Docu process orchestration isn't running for this conversation. Please reopen the chat.",
				"conversation_name": conversation_name,
				"doctype_ir": None, "diff": None, "options": None, "suggested_name": None,
			}

		# The panel keys on ``conversation_name``; invoke_agent returns ``conversation``.
		result["conversation_name"] = result.get("conversation") or conversation_name
		result["session_id"] = session_id
		return result

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
#
# This is a thin async wrapper over the generic ``invoke_agent`` entry point
# (WI-001539): the enqueued worker (``_run_docu_turn``) is the only thing that
# calls it, so the enqueue-and-poll shape wraps cleanly around the same path
# every other agent uses. The conversation is still opened here (fast) via
# ``create_agent_conversation`` so the client gets ``conversation_name`` at once.

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
	immediately) via ``create_agent_conversation``, which stamps the agent's chat
	mode label and arms the Docu process map; the slow turn runs through
	``invoke_agent`` in ``_run_docu_turn`` on a worker. ``chat_history`` is accepted
	for client parity but, as in ``docu_chat``, is not forwarded — the BPMN instance
	carries the conversation's own history.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please sign in to use Docu."), frappe.PermissionError)
	if not (message or "").strip():
		frappe.throw(_("Message is required"))

	from one_bpmn.utils.chat_persistence import create_agent_conversation

	if not conversation_name:
		label = doctype or "DocType"
		conversation_name = create_agent_conversation(
			"docu_agent", title=f"Docu: {label}", user=frappe.session.user
		)

	turn_id = frappe.generate_hash(length=14)
	frappe.cache().set_value(_turn_key(turn_id), {"status": "pending"}, expires_in_sec=_TURN_TTL_SEC)

	# enqueue_after_commit → the worker (separate process) only runs once this
	# request's conversation/instance rows are committed and visible to it.
	# at_front → an interactive Docu turn jumps ahead of batch/background jobs
	# already queued (e.g. memory distillation, engine jobs) so a user waiting on
	# the chat isn't stuck behind them on a shared worker.
	frappe.enqueue(
		"one_bpmn.api.docu_api._run_docu_turn",
		queue="default",
		timeout=600,
		at_front=True,
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
	"""Background worker: run the slow turn through the generic agent path and
	cache the result for polling.

	This is where the async wrapper meets the generic entry point: it calls
	``invoke_agent("docu_agent", …)`` (which, because the config links the Docu
	map, drives the same Save User Message → Run Docu Agent → Save Response
	pipeline) rather than delegating to the BPMN instance directly.
	"""
	key = _turn_key(turn_id)
	try:
		frappe.set_user(user)
		from one_bpmn.api.agent_invocation import invoke_agent

		try:
			result = invoke_agent("docu_agent", message, conversation=conversation_name, context=context)
			result["conversation_name"] = result.get("conversation") or conversation_name
		except RateLimited as exc:
			# WI-001968: a throttle or a conversation freeze is a real, explainable
			# refusal — not a dead instance. RateLimited subclasses ValidationError,
			# so without this branch the handler below rewrites it as "orchestration
			# isn't running" and the user is told to reopen a chat that is working
			# perfectly. Surface what actually happened, in the chat bubble.
			result = {
				"intent": "BLOCKED",
				"response": str(exc),
				"conversation_name": conversation_name,
				"doctype_ir": None, "diff": None, "options": None, "suggested_name": None,
			}
		except frappe.ValidationError:
			result = {
				"intent": "ERROR",
				"response": _("The Docu process orchestration isn't running for this conversation. Please reopen the chat."),
				"conversation_name": conversation_name,
				"doctype_ir": None, "diff": None, "options": None, "suggested_name": None,
			}

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

	# 1) Server-side safety gate — never trust the client IR. When customizing an
	#    existing DocType, its own fields (incl. reserved/standard ones like
	#    amended_from) are passed through untouched, so they are exempted from the
	#    new-field checks; only genuinely new fields are strictly validated.
	_name = (ir_dict.get("doctype_name") or "").strip()
	existing_fieldnames = set()
	if _name and frappe.db.exists("DocType", _name):
		existing_fieldnames = {f.fieldname for f in frappe.get_meta(_name).fields if f.fieldname}
	verdict = validate_doctype_ir(ir_dict, existing_fieldnames=existing_fieldnames)
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
			action = _customize_standard_doctype(name, fields)
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
	called for custom DocTypes; standard types go through ``_customize_standard_doctype``.
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


def _customize_standard_doctype(name: str, fields: list) -> str:
	"""Apply Docu IR field changes to a STANDARD DocType via Customize Form.

	Customize Form is Frappe's supported mechanism for changing a standard
	DocType: brand-new fields are materialised as Custom Fields, and edits to
	existing (standard or custom) fields are emitted as Property Setters. The
	DocType's own source definition is never touched.
	"""
	# Single DocTypes can't go through Customize Form (Frappe raises "Single
	# DocTypes cannot be customized"). They still accept Custom Fields and
	# Property Setters, so route them through a Customize-Form-free path.
	if frappe.db.get_value("DocType", name, "issingle"):
		return _customize_single_doctype(name, fields)

	from frappe.custom.doctype.customize_form.customize_form import docfield_properties

	cf = frappe.get_doc("Customize Form")
	cf.doc_type = name
	cf.fetch_to_customize()

	existing = {row.fieldname: row for row in cf.fields if row.fieldname}
	changed = False
	# Brand-new fields, materialised as Custom Fields after the customize pass.
	new_fields: list = []
	# (fieldname, prop) → desired value, for edits to already-present fields. Used
	# to force through any change Frappe's Customize Form soft-guards refuse.
	desired: dict = {}

	for field in fields:
		# Never customise layout breaks or Frappe's reserved/standard meta fields
		# (name, amended_from, docstatus, …). They round-trip through the IR but
		# must be left untouched — touching them only produces spurious Property
		# Setters (e.g. a "column_break_4" label) or is outright rejected.
		if field.get("fieldtype") in _LAYOUT_FIELDTYPES:
			continue
		fieldname = (field.get("fieldname") or "").strip()
		if not fieldname or fieldname in RESERVED_FIELDNAMES:
			continue
		row = existing.get(fieldname)
		if row is None:
			# Brand-new field → collected now, created as a Custom Field below.
			new_fields.append(_docfield_dict(field, len(new_fields) + 1))
			changed = True
		else:
			# Existing field — apply only the Customize-Form-editable props that
			# Docu supplied and that GENUINELY differ. Values are normalised per
			# property type so the IR's coerced blanks ("" / 0) don't read as
			# changes against the live None values — otherwise every field would
			# spawn a flood of no-op Property Setters on save.
			for prop in docfield_properties:
				if prop == "idx" or prop not in field:
					continue
				want = _norm_prop(prop, field[prop], docfield_properties)
				if want == _norm_prop(prop, row.get(prop), docfield_properties):
					continue
				row.set(prop, want)
				desired[(fieldname, prop)] = want
				changed = True

	if not changed:
		return "unchanged"

	# Edits to already-present fields (standard → Property Setters, custom → the
	# Custom Field itself) go through Customize Form's own save.
	if desired:
		cf.flags.ignore_permissions = True
		cf.hide_success = True
		cf.save_customization()

		# Force any standard-field change Frappe's Customize Form soft-guards
		# refused (e.g. disabling Mandatory on a standard field) by writing the
		# Property Setter directly. Allowed/custom changes already applied above,
		# so they compare equal here and are skipped.
		_force_refused_property_changes(name, desired, docfield_properties)

	# Brand-new fields → materialised as Custom Fields (reliable, avoids the
	# Customize-Form append path).
	if new_fields:
		from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

		create_custom_fields({name: new_fields}, ignore_validate=False)

	frappe.clear_cache(doctype=name)
	return "customized"


def _customize_single_doctype(name: str, fields: list) -> str:
	"""Apply Docu IR field changes to a STANDARD *Single* DocType.

	Frappe's Customize Form refuses Single DocTypes, so this bypasses it: new
	fields become Custom Fields and edits to existing fields become Property
	Setters directly — both fully supported on Single DocTypes. Mirrors the
	new-field / forced-edit logic of ``_customize_standard_doctype`` without the
	Customize Form round-trip.
	"""
	from frappe.custom.doctype.customize_form.customize_form import docfield_properties

	frappe.clear_cache(doctype=name)
	meta = frappe.get_meta(name)
	existing = {df.fieldname: df for df in meta.fields if df.fieldname}

	new_fields: list = []
	# (fieldname, prop) → desired value, for edits to already-present fields.
	desired: dict = {}
	# The most recent already-present field seen while walking the IR in order.
	# A brand-new field is positioned right after it (Custom Field ``insert_after``)
	# so IR order is honoured — e.g. a field inserted "before footer" lands after
	# whatever precedes footer, rather than being appended at the end.
	last_existing: str | None = None

	for field in fields:
		if field.get("fieldtype") in _LAYOUT_FIELDTYPES:
			continue
		fieldname = (field.get("fieldname") or "").strip()
		if not fieldname or fieldname in RESERVED_FIELDNAMES:
			continue
		df = existing.get(fieldname)
		if df is None:
			payload = _docfield_dict(field, len(new_fields) + 1)
			if last_existing:
				payload["insert_after"] = last_existing
			new_fields.append(payload)
		else:
			last_existing = fieldname
			for prop in docfield_properties:
				if prop == "idx" or prop not in field:
					continue
				want = _norm_prop(prop, field[prop], docfield_properties)
				if want == _norm_prop(prop, df.get(prop), docfield_properties):
					continue
				desired[(fieldname, prop)] = want

	if not new_fields and not desired:
		return "unchanged"

	# Brand-new fields → Custom Fields (supported on Single DocTypes).
	if new_fields:
		from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

		create_custom_fields({name: new_fields}, ignore_validate=False)

	# Edits to existing fields → Property Setters written directly.
	for (fieldname, prop), val in desired.items():
		_force_property_setter(name, fieldname, prop, val, docfield_properties.get(prop) or "Data")

	frappe.clear_cache(doctype=name)
	return "customized"


def _force_refused_property_changes(doctype: str, desired: dict, docfield_properties: dict) -> None:
	"""Write Property Setters directly for edits Customize Form refused to persist."""
	if not desired:
		return
	frappe.clear_cache(doctype=doctype)
	meta = frappe.get_meta(doctype)
	for (fieldname, prop), val in desired.items():
		df = meta.get_field(fieldname)
		if not df:
			continue
		if _norm_prop(prop, df.get(prop), docfield_properties) == _norm_prop(prop, val, docfield_properties):
			continue  # already applied (allowed change, or a custom field)
		_force_property_setter(doctype, fieldname, prop, val, docfield_properties.get(prop) or "Data")


def _norm_prop(prop: str, value, prop_types: dict):
	"""Normalise a DocField property value for change detection.

	Coerces per the property's type so the IR's blanks (``""`` / ``0`` / ``None``)
	compare equal to the live meta values and don't register as edits.
	"""
	t = prop_types.get(prop)
	if t == "Check":
		return 1 if value else 0
	if t == "Int":
		try:
			return int(value or 0)
		except (TypeError, ValueError):
			return 0
	return "" if value in (None, "") else value


def _force_property_setter(doctype: str, fieldname: str, prop: str, value, property_type: str) -> None:
	"""Upsert a Property Setter, bypassing Customize Form's soft guards."""
	if property_type == "Check":
		ps_value = "1" if value else "0"
	else:
		ps_value = "" if value is None else str(value)

	ps_name = f"{doctype}-{fieldname}-{prop}"
	if frappe.db.exists("Property Setter", ps_name):
		ps = frappe.get_doc("Property Setter", ps_name)
		ps.value = ps_value
		ps.property_type = property_type
		ps.flags.ignore_permissions = True
		ps.save(ignore_permissions=True)
	else:
		frappe.make_property_setter(
			{
				"doctype": doctype,
				"doctype_or_field": "DocField",
				"fieldname": fieldname,
				"property": prop,
				"value": ps_value,
				"property_type": property_type,
			},
			is_system_generated=False,
		)


# ── Shared-endpoint integration (WI-001676 follow-up, after 54e9ead/73e7d89) ──
def _compact_ir(ir: dict) -> dict:
	"""Strip empty/zero attributes from a round-tripped IR before it rides in
	dialog_context — the reader emits every DocField attribute (a plain ToDo
	is ~35KB verbatim), but absent keys mean defaults on the apply path, so
	the model only needs the truthy ones."""
	compact = {k: v for k, v in ir.items() if k != "fields" and v not in ("", 0, None, [])}
	compact["fields"] = [
		{k: v for k, v in f.items() if k in ("fieldname", "fieldtype") or v not in ("", 0, None)}
		for f in ir.get("fields") or []
		if isinstance(f, dict)
	]
	return compact


def build_docu_turn_context(context: dict) -> dict:
	"""Load the target DocType's current IR for a Docu turn (context builder
	for the AG-UI endpoint) and fold it, with the Docu reply contract, into
	dialog_context — the same dual-generation strategy as Logix/ProsAlly:
	the purpose-built map's Classify tool loads current_ir itself and renders
	its own variables, while a generic chat-template clone renders only
	{{ dialog_context }} and would otherwise never see the schema or the
	contract."""
	out = dict(context or {})
	doctype = out.get("doctype") or ""

	schema_block = ""
	if doctype and frappe.db.exists("DocType", doctype):
		if frappe.has_permission("DocType", "read"):
			ir = _read_doctype_ir(doctype)
			if ir:
				schema_block = (
					"CURRENT DOCTYPE ('%s') AS IR:\n```json\n%s\n```\n"
					"This form exists — treat the request as a MODIFY of this IR "
					"unless the user clearly asks for a new form.\n\n"
				) % (doctype, json.dumps(_compact_ir(ir), indent=1, default=str))
		else:
			frappe.log_error(
				title="Docu: DocType read denied for turn context",
				message=f"user={frappe.session.user} doctype={doctype}",
			)
	elif doctype:
		schema_block = (
			"Named form: '%s' — it does not exist yet, so this is likely a CREATE.\n\n" % doctype
		)

	contract = (
		schema_block
		+ "DOCU REPLY CONTRACT: respond ONLY with a JSON object: "
		'{"intent": "CREATE"|"MODIFY"|"DISAMBIGUATE", '
		'"response": "<short human explanation>", '
		'"doctype_ir": <the FULL DocType definition when proposing a schema: '
		'{"doctype_name": "Title Case Name", "fields": [{"fieldname": "snake_case", '
		'"label": "Title Case", "fieldtype": "<a real Frappe fieldtype>", '
		'"options": "<Link/Select target when applicable>", "reqd": 0|1}, ...]}>, '
		'"suggested_name": "<the doctype_name>", '
		'"options": ["..."] <only when intent is DISAMBIGUATE> }. '
		"For MODIFY return the complete updated IR, not just the changed fields. "
		"Never claim you created or changed anything — the designer reviews your "
		"proposal on a schema card and applies it from there."
	)
	existing = out.get("dialog_context") or ""
	out["dialog_context"] = (existing + "\n\n" + contract).strip()
	return out


def shape_docu_reply(result: dict) -> dict:
	"""Lift the Docu JSON contract out of a text reply (reply shaper); a
	no-op when the purpose-built map already returned structured keys."""
	if result.get("doctype_ir") or result.get("intent"):
		return result
	from one_bpmn.api.ai_assistant import _extract_json

	raw = result.get("response") or ""
	parsed = _extract_json(raw if isinstance(raw, str) else "")
	if not isinstance(parsed, dict) or not (parsed.get("intent") or parsed.get("doctype_ir")):
		return result
	shaped = dict(result)
	shaped["response"] = str(parsed.get("response") or "").strip() or raw
	for key in ("intent", "doctype_ir", "diff", "suggested_name", "options"):
		if parsed.get(key):
			shaped[key] = parsed[key]
	return shaped


def _register_agui_hooks():
	from one_bpmn.agents.agui_stream import (
		register_context_builder,
		register_reply_shaper,
	)

	register_context_builder("docu_agent", build_docu_turn_context)
	register_reply_shaper("docu_agent", shape_docu_reply)


_register_agui_hooks()
