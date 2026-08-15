# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Whitelisted endpoints backing the Processa Security view.

This module is a WINDOW, not a mechanism. Screening decides nothing here,
nothing is logged here, and nothing is promoted here — those live in
security.injection, security.events, api.security_events and
api.conversation_locks, and every write below delegates to one of them. The
value of keeping that line sharp is that the security behaviour has exactly one
implementation to audit; a second copy behind a UI endpoint is how the console
and the runtime drift into disagreeing about what the rules are.

WHAT IT EXPOSES

* reads over the event stream, the injection pattern pack, and locked
  conversations;
* three writes, each a thin call into the module that owns it — edit a pattern,
  release a lock, promote an event to an eval case;
* the agent's own screening settings, read from and written to whichever
  screening fields the AI Agent Configuration doctype actually has.

RAW CONTENT IS NEVER RETURNED, because it is never stored. An event carries a
hash and a length; the text that produced them was dropped at the boundary. The
event reader is written so that stays true by construction — it names the fields
it returns rather than handing back the document.
"""

import frappe
from frappe import _

# Reads are open to anyone who can read the doctype (Frappe's own permission
# check does the work). WRITES are held to a narrower gate: the pattern pack is
# the rule set every agent is screened against, so editing it is a System
# Manager act even though Process Owner holds write on the doctype for seeding.
PATTERN_EDIT_ROLES = ("System Manager",)

# The per-agent screening controls this screen offers, in the order they are
# shown. Declared as data rather than assumed present: `output_screening_mode`
# is owned by 15.1 and does not exist yet, and a screen that hard-codes it would
# either crash or lie. Each entry renders only when the field is really on the
# doctype, so the section grows by itself as those stories land.
SCREENING_FIELDS = (
	"pii_screening",
	"injection_screening_mode",
	"output_screening_mode",
)

EVENT_FIELDS = (
	"name",
	"boundary",
	"stage",
	"action",
	"severity",
	"detected_at",
	"rule",
	"rule_type",
	"matched_pattern",
	"classifier",
	"agent_configuration",
	"conversation",
	"run",
	"bpmn_id",
	"correlation_id",
	"content_hash",
	"content_length",
	"detail",
	"owner",
	"creation",
)


def _can_edit_patterns() -> bool:
	roles = set(frappe.get_roles())
	return any(r in roles for r in PATTERN_EDIT_ROLES)


def _require_pattern_editor():
	if not _can_edit_patterns():
		frappe.throw(
			_("Editing the injection pattern pack is restricted to {0}.").format(
				", ".join(PATTERN_EDIT_ROLES)
			),
			frappe.PermissionError,
		)


@frappe.whitelist()
def can_manage() -> dict:
	"""What this user may do, so the screen can render the right controls rather
	than offering buttons that will be refused."""
	from one_bpmn.api.conversation_locks import reviewer_roles

	roles = set(frappe.get_roles())
	return {
		"edit_patterns": _can_edit_patterns(),
		"release_locks": bool(roles & set(reviewer_roles() or [])) or "System Manager" in roles,
		"read_events": bool(frappe.has_permission("AI Security Event", "read")),
	}


# ── Event stream ─────────────────────────────────────────────────────────────

@frappe.whitelist()
def list_events(
	agent: str = None,
	boundary: str = None,
	action: str = None,
	severity: str = None,
	search: str = None,
	start: int = 0,
	page_length: int = 50,
) -> dict:
	"""The event stream, most recently updated first, filtered and paged.

	Returns ``total`` alongside the rows so the screen can show how much it is
	looking at — a security console that silently truncates is worse than one
	that says "50 of 4,312".
	"""
	frappe.has_permission("AI Security Event", "read", throw=True)

	filters = {}
	if agent:
		filters["agent_configuration"] = agent
	if boundary:
		filters["boundary"] = boundary
	if action:
		filters["action"] = action
	if severity:
		filters["severity"] = severity

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"detail": ("like", like), "classifier": ("like", like), "rule": ("like", like)}

	page_length = max(1, min(int(page_length or 50), 200))
	start = max(0, int(start or 0))

	rows = frappe.get_list(
		"AI Security Event",
		filters=filters,
		or_filters=or_filters,
		fields=list(EVENT_FIELDS),
		# Last updated, like every other list on this screen. An event is never
		# edited after it is written — deletion is blocked and there is no edit
		# path — so for events this is the same thing as newest-first.
		order_by="modified desc",
		start=start,
		page_length=page_length,
	)
	# Counted through get_list, not db.count, so the same permission scoping that
	# produced the rows produces the total — otherwise the screen reports a
	# number the reader is not allowed to see the contents of.
	#
	# Aggregated in SQL rather than by fetching every row and taking len(): this
	# is the one query that grows without bound as the log fills, and it runs on
	# every page turn. The permission conditions still apply — that is the whole
	# reason for going through get_list — but only one row comes back.
	count_row = frappe.get_list(
		"AI Security Event",
		filters=filters,
		or_filters=or_filters,
		fields=["count(name) as total"],
	)
	total = (count_row[0].get("total") if count_row else 0) or 0
	return {"events": rows, "total": total, "start": start, "page_length": page_length}


@frappe.whitelist()
def get_event(name: str) -> dict:
	"""Everything recorded about one event.

	Fields are named explicitly rather than returning the document, so a field
	added later cannot quietly start leaking something. There is no raw content
	to withhold — the text was hashed and dropped at the boundary — and the
	screen says so rather than leaving a reader wondering where it went.
	"""
	doc = frappe.get_doc("AI Security Event", name)
	doc.check_permission("read")
	out = {f: doc.get(f) for f in EVENT_FIELDS}
	out["content_stored"] = False
	out["promoted_case"] = frappe.db.get_value(
		"AI Eval Case", {"source_security_event": name}, "name"
	)
	return out


@frappe.whitelist()
def event_filter_options() -> dict:
	"""The values actually present in the log, so the filters offer real choices
	instead of every value the schema allows."""
	frappe.has_permission("AI Security Event", "read", throw=True)

	def distinct(field):
		rows = frappe.get_all("AI Security Event", fields=[field], group_by=field, limit_page_length=0)
		return sorted({r[field] for r in rows if r.get(field)})

	return {
		"agents": distinct("agent_configuration"),
		"boundaries": distinct("boundary"),
		"actions": distinct("action"),
		"severities": distinct("severity"),
	}


@frappe.whitelist()
def suites_for_event(event: str) -> list:
	"""Eval suites the event's agent could be promoted into.

	15.2 refuses to choose when an agent has more than one suite — guessing
	would quietly file an attack in the wrong place. That refusal is right, but
	it leaves the reviewer holding an error with no way forward, so the screen
	offers the candidates and asks.
	"""
	frappe.has_permission("AI Security Event", "read", throw=True)
	agent = frappe.db.get_value("AI Security Event", event, "agent_configuration")
	if not agent:
		return []
	return frappe.get_list(
		"AI Eval Suite",
		filters={"agent_configuration": agent},
		fields=["name", "title", "suite_type"],
		order_by="suite_type asc, title asc",
		limit_page_length=0,
	)


@frappe.whitelist()
def promote_event(event: str, suite: str = None) -> dict:
	"""Promote an event to an eval case. Delegates to 15.2's method — the
	promotion logic, including its idempotency, belongs there.

	Reports whether this call created the case or found one already, because
	"nothing happened" and "it was already done" look identical otherwise, and a
	reviewer clicking twice deserves to know which they got.
	"""
	from one_bpmn.api.security_events import promote_to_eval_case

	# 15.2 answers with eval_case/created/suite, and its own idempotency decides
	# `created` — reading that rather than comparing before/after keeps this from
	# having a second opinion about whether the case is new.
	result = promote_to_eval_case(event, suite=suite) if suite else promote_to_eval_case(event)
	return {
		"case": result.get("eval_case"),
		"already_promoted": not result.get("created", True),
		"suite": result.get("suite"),
	}


# ── Injection pattern pack ───────────────────────────────────────────────────

@frappe.whitelist()
def list_patterns(enabled_only: int = 0) -> dict:
	"""The pack, with the caller's edit right, so the screen renders read-only
	for everyone but a System Manager without a second round trip."""
	frappe.has_permission("AI Injection Pattern", "read", throw=True)
	filters = {"enabled": 1} if int(enabled_only or 0) else {}
	return {
		"patterns": frappe.get_list(
			"AI Injection Pattern",
			filters=filters,
			fields=[
				"name", "pattern_name", "enabled", "pattern_type", "severity", "pattern",
				"match_mode", "boundary_scope", "action", "source_taxonomy",
				"source_reference", "source_event", "notes", "modified",
			],
			# Last updated: a reviewer who has just tuned a rule wants to see it,
			# and the pack is small enough to scan. This replaced grouping by
			# enabled-then-severity, which buried a rule you had just edited.
			order_by="modified desc",
			limit_page_length=0,
		),
		"can_edit": _can_edit_patterns(),
	}


@frappe.whitelist()
def pattern_options() -> dict:
	"""The Select options the doctype actually defines.

	Served rather than mirrored in the Vue: hand-copied option lists rot the
	moment a story adds a pattern type, and the copy fails silently — the editor
	offers a value the doctype rejects, or omits one it accepts.
	"""
	frappe.has_permission("AI Injection Pattern", "read", throw=True)
	meta = frappe.get_meta("AI Injection Pattern")
	out = {}
	for fieldname in ("pattern_type", "match_mode", "severity", "action", "boundary_scope", "source_taxonomy"):
		df = meta.get_field(fieldname)
		out[fieldname] = [o for o in ((df.options or "").split("\n") if df else []) if o]
	return out


@frappe.whitelist()
def save_pattern(pattern: str | dict = None, name: str = None) -> dict:
	"""Create or update one pattern. System Manager only.

	Writes through the document so the doctype's own validation runs — the
	pattern is compiled and rejected if it cannot be, which is the check that
	stops a broken rule silently disabling screening for everyone.
	"""
	_require_pattern_editor()
	if isinstance(pattern, str):
		pattern = frappe.parse_json(pattern) or {}
	pattern = pattern or {}
	name = name or pattern.get("name")

	doc = frappe.get_doc("AI Injection Pattern", name) if name else frappe.new_doc("AI Injection Pattern")
	for field in (
		"pattern_name", "enabled", "pattern_type", "severity", "pattern", "match_mode",
		"boundary_scope", "action", "source_taxonomy", "source_reference", "notes",
	):
		if field in pattern:
			doc.set(field, pattern[field])
	doc.save()
	return {"name": doc.name, "enabled": int(doc.enabled or 0)}


@frappe.whitelist()
def set_pattern_enabled(name: str, enabled: int) -> dict:
	"""Enable or disable one rule — the action a reviewer reaches for most, kept
	separate so it does not require sending the whole pattern back."""
	_require_pattern_editor()
	doc = frappe.get_doc("AI Injection Pattern", name)
	doc.enabled = 1 if int(enabled or 0) else 0
	doc.save()
	return {"name": doc.name, "enabled": int(doc.enabled)}


# ── Locked conversations ─────────────────────────────────────────────────────

@frappe.whitelist()
def list_locks(status: str = None) -> dict:
	"""Locked conversations, most recently updated first, with the release audit
	attached so the list answers "who released this and why" without opening each
	one. A release counts as an update, so acting on a lock moves it to the top."""
	frappe.has_permission("AI Conversation Lock", "read", throw=True)
	filters = {"status": status} if status else {}
	return {
		"locks": frappe.get_list(
			"AI Conversation Lock",
			filters=filters,
			fields=[
				"name", "status", "user", "agent_configuration", "conversation", "reason",
				"blocked_count", "locked_at", "trigger_event", "detail",
				"released_by", "released_at", "release_notes",
			],
			# Last updated rather than locked_at, so a release floats its lock to
			# the top — releasing IS the activity a reviewer is tracking, and a
			# lock released this morning matters more than one opened last week.
			order_by="modified desc",
			limit_page_length=0,
		),
		"me": frappe.session.user,
	}


@frappe.whitelist()
def release(lock: str, notes: str = None) -> dict:
	"""Release a frozen conversation. Delegates to 15.3's action, which owns the
	rules that make the release meaningful: a reviewer role, a note for the audit
	trail, and the refusal that stops the locked user releasing themselves."""
	from one_bpmn.api.conversation_locks import release_lock

	return release_lock(lock, notes=notes)


# ── Per-agent screening ──────────────────────────────────────────────────────

@frappe.whitelist()
def agent_screening(agent: str) -> dict:
	"""The screening controls this agent actually has, with their current values.

	Built from the doctype's live fields rather than a hard-coded list: the
	output mode (15.1) and the injection mode (WI-001840) do not exist yet, and
	a screen that assumed them would show a control that writes nowhere. When
	those stories add their fields, they appear here — label, options and
	description included — with no change to this module or the Vue.
	"""
	doc = frappe.get_doc("AI Agent Configuration", agent)
	doc.check_permission("read")
	meta = frappe.get_meta("AI Agent Configuration")

	controls = []
	for fieldname in SCREENING_FIELDS:
		df = meta.get_field(fieldname)
		if not df:
			continue
		controls.append({
			"fieldname": fieldname,
			"label": df.label or fieldname,
			"fieldtype": df.fieldtype,
			"options": [o for o in (df.options or "").split("\n") if o] if df.fieldtype == "Select" else None,
			"description": df.description,
			"value": doc.get(fieldname),
		})
	return {
		"agent": doc.name,
		"agent_name": doc.get("agent_name"),
		"controls": controls,
		"can_edit": bool(doc.has_permission("write")),
	}


@frappe.whitelist()
def save_agent_screening(agent: str, values: str | dict) -> dict:
	"""Write the screening modes back to the agent.

	Only fields in SCREENING_FIELDS that exist on the doctype are accepted, so
	this endpoint can never become a general-purpose writer for the whole
	configuration — the rest of the agent is edited where it always was.
	"""
	if isinstance(values, str):
		values = frappe.parse_json(values) or {}
	values = values or {}

	doc = frappe.get_doc("AI Agent Configuration", agent)
	doc.check_permission("write")
	meta = frappe.get_meta("AI Agent Configuration")

	changed = []
	for fieldname in SCREENING_FIELDS:
		if fieldname not in values or not meta.get_field(fieldname):
			continue
		if doc.get(fieldname) != values[fieldname]:
			doc.set(fieldname, values[fieldname])
			changed.append(fieldname)

	if changed:
		doc.save()
	return {"agent": doc.name, "updated": changed}
