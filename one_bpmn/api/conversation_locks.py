# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Releasing a frozen conversation (WI-001968).

Deliberately the only way out of a lock. The doctype grants write to nobody, so
a reviewer cannot quietly flip the status on the form — they come through here,
the check runs, and the release is recorded with their name against it.

The rule that carries the weight is the last one: **the locked user can never
release their own lock**, no matter which roles they hold. A System Manager who
gets themselves frozen still needs a second pair of eyes. Without that, a
containment control contains nobody who matters.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime


@frappe.whitelist()
def release_lock(lock: str, notes: str | None = None) -> dict:
	"""Release a frozen conversation. Reviewer only, never the locked user.

	Args:
		lock: name of the AI Conversation Lock.
		notes: why it is being released. Required — a release with no reason is
			the thing an auditor will ask about first.

	Returns ``{"lock": name, "status": "Released", "released_by": user}``.
	"""
	if not lock:
		frappe.throw(_("A lock is required."))
	if not frappe.db.exists("AI Conversation Lock", lock):
		frappe.throw(_("Conversation lock {0} does not exist.").format(lock))

	doc = frappe.get_doc("AI Conversation Lock", lock)
	user = frappe.session.user

	if doc.status != "Locked":
		return {"lock": doc.name, "status": doc.status, "released_by": doc.released_by, "already": True}

	if user == doc.user:
		frappe.throw(
			_(
				"You cannot release your own conversation lock. Another reviewer has to do it — "
				"that is the whole point of the freeze."
			),
			frappe.PermissionError,
			title=_("Reviewer Required"),
		)

	if not _is_reviewer(user):
		frappe.throw(
			_("Releasing a conversation lock requires one of these roles: {0}.").format(
				", ".join(reviewer_roles())
			),
			frappe.PermissionError,
			title=_("Reviewer Required"),
		)

	if not (notes or "").strip():
		frappe.throw(_("Say why you are releasing this lock — the note is part of the audit trail."))

	doc.db_set(
		{
			"status": "Released",
			"released_by": user,
			"released_at": now_datetime(),
			"release_notes": (notes or "").strip()[:1000],
		},
		update_modified=True,
	)

	# Let them straight back in. A release that leaves the throttle window full
	# is barely a release: the user's next message is refused and they are told
	# to wait, sometimes for the whole window, after a reviewer has just decided
	# they may carry on. Clearing the window is what makes "released" mean it.
	#
	# Their earlier blocked attempts stop counting toward the next freeze too —
	# that is handled where the strikes are counted, so the events stay in the
	# log for audit rather than being deleted.
	from one_bpmn.security.rate_limit import clear_window

	clear_window(doc.user, doc.agent_configuration)

	# The release belongs in the same log as the lockout it undoes.
	from one_bpmn.security.events import record_event

	record_event(
		boundary="input",
		stage="conversation-lock",
		action="Log",
		agent_configuration=doc.agent_configuration,
		conversation=doc.conversation,
		severity="Medium",
		classifier="lock-released",
		detail=f"lock {doc.name} released by {user} for {doc.user}",
	)

	return {"lock": doc.name, "status": "Released", "released_by": user}


def reviewer_roles() -> list[str]:
	"""Roles allowed to release, from settings. System Manager is always in."""
	from one_bpmn.security.rate_limit import settings

	configured = (settings().get("lock_release_roles") or "").split(",")
	roles = [r.strip() for r in configured if r.strip()]
	if "System Manager" not in roles:
		roles.append("System Manager")
	return roles


def _is_reviewer(user: str) -> bool:
	try:
		return bool(set(frappe.get_roles(user)) & set(reviewer_roles()))
	except Exception:
		return False


@frappe.whitelist()
def my_lock_status(agent_id: str | None = None) -> dict:
	"""Whether the calling user is currently frozen. For a UI to show why.

	Read-only and safe to call from anywhere; a user is allowed to know they are
	locked, and being told beats a message that silently fails.
	"""
	from one_bpmn.one_bpmn.doctype.ai_conversation_lock.ai_conversation_lock import active_lock

	agent = None
	if agent_id:
		agent = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name")

	lock = active_lock(frappe.session.user, agent, None)
	if not lock:
		return {"locked": False}

	doc = frappe.db.get_value(
		"AI Conversation Lock", lock, ["name", "reason", "locked_at", "blocked_count"], as_dict=True
	)
	return {"locked": True, **doc}
