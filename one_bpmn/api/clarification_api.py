# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Answering an agent's question from the document it is about (WI-002050).

The pending question is a task on a process instance, and the person who can
settle it is the one who owns the document. Those are not the same screen. Asking
them to open a process instance to unblock their own work is asking them to learn
the machinery to answer a question about their own requirement.

So the question surfaces on the document — whichever doctype it is, because the
record names a doctype and a document and was never Work-Item-specific — and this
is the door: read what is pending, and answer it. The answer goes through the SAME entry point a user task
uses, so the permission checks, the resume-exactly-once guarantee and the audit
record all behave identically to answering it anywhere else. Nothing here decides
whether the answer was good enough — that is the agent's judgement, and if it was
not, it asks again.
"""

from __future__ import annotations

import frappe
from frappe import _

FIELDS = (
	"name",
	"question",
	"interpretations",
	"agent_configuration",
	"asked_at",
	"round",
	"owner_asked",
	"instance",
	"human_task_id",
	"status",
	"answer",
	"answered_by",
	"answered_at",
	"reminded_at",
	"escalated_at",
)


# What the monitor lists. Wider than the form needs, because the point of the
# screen is scanning: who asked, who was asked, what it was about, and whether
# anyone has replied — without opening anything.
LIST_FIELDS = (
	"name",
	"agent_configuration",
	"owner_asked",
	"reference_doctype",
	"reference_name",
	"status",
	"question",
	"answer",
	"answered_by",
	"answered_at",
	"asked_at",
	"round",
	"follow_up_of",
	"reminded_at",
	"escalated_at",
	"escalated_to",
	"modified",
)

MAX_PAGE_LENGTH = 200


def _require_admin() -> None:
	"""Same gate as the rest of the A2A screen: this lists questions asked about
	documents across the whole site, which is more than any one person's view."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only System Managers may review clarifications."), frappe.PermissionError)


@frappe.whitelist()
def list_clarifications(
	agent_configuration: str = None,
	owner_asked: str = None,
	reference_doctype: str = None,
	status: str = None,
	asked_from: str = None,
	asked_to: str = None,
	start: int = 0,
	page_length: int = 20,
) -> dict:
	"""Questions agents have asked, newest activity first.

	Ordered by last updated rather than by when it was asked: a question that has
	just been answered, reminded or escalated is the one worth seeing, and
	ordering by asked_at buries it under everything raised since.
	"""
	_require_admin()
	filters: dict = {}
	if agent_configuration:
		filters["agent_configuration"] = agent_configuration
	if owner_asked:
		filters["owner_asked"] = owner_asked
	if reference_doctype:
		filters["reference_doctype"] = reference_doctype
	if status:
		filters["status"] = status
	# A date range on when it was ASKED, not when it was last touched — "what did
	# we ask last week" is the question people actually have, and the answer must
	# not move when somebody replies today.
	if asked_from and asked_to:
		filters["asked_at"] = ["between", [asked_from, f"{asked_to} 23:59:59"]]
	elif asked_from:
		filters["asked_at"] = [">=", asked_from]
	elif asked_to:
		filters["asked_at"] = ["<=", f"{asked_to} 23:59:59"]

	page_length = min(int(page_length or 20), MAX_PAGE_LENGTH)
	rows = frappe.get_all(
		"AI Clarification",
		filters=filters,
		fields=list(LIST_FIELDS),
		order_by="modified desc",
		start=int(start or 0),
		limit=page_length,
	)
	return {
		"clarifications": rows,
		"total": frappe.db.count("AI Clarification", filters),
		"start": int(start or 0),
		"page_length": page_length,
	}


@frappe.whitelist()
def clarification_detail(name: str) -> dict:
	"""One question in full, with the thread it belongs to.

	The thread is the point. A follow-up reads as pedantic on its own; beside the
	answer that failed to settle the matter it reads as the agent doing exactly
	what it was asked to do.
	"""
	_require_admin()
	row = frappe.db.get_value("AI Clarification", name, list(LIST_FIELDS) + ["instance", "human_task_id", "interpretations", "asked_by_agent_run"], as_dict=True)
	if not row:
		frappe.throw(_("Clarification {0} not found.").format(name), frappe.DoesNotExistError)

	thread = []
	if row.get("reference_doctype") and row.get("reference_name"):
		thread = frappe.get_all(
			"AI Clarification",
			filters={
				"reference_doctype": row["reference_doctype"],
				"reference_name": row["reference_name"],
			},
			fields=["name", "round", "status", "question", "answer", "answered_by", "answered_at", "asked_at"],
			order_by="round asc, creation asc",
		)

	title = None
	if row.get("reference_doctype") and row.get("reference_name"):
		try:
			field = frappe.get_meta(row["reference_doctype"]).get_title_field()
			if field and field != "name":
				title = frappe.db.get_value(row["reference_doctype"], row["reference_name"], field)
		except Exception:
			# A reference to a doctype that no longer exists must not take the
			# modal down with it.
			title = None

	return {"clarification": row, "thread": thread, "reference_title": title}


@frappe.whitelist()
def clarification_filter_options() -> dict:
	"""What is worth filtering by on this site, built from the rows themselves.

	An agent that has never asked anything, or a person nobody has ever asked, is
	a dead entry in a dropdown.
	"""
	_require_admin()

	def distinct(fieldname):
		rows = frappe.get_all(
			"AI Clarification",
			filters={fieldname: ["is", "set"]},
			fields=[fieldname],
			group_by=fieldname,
			order_by=f"{fieldname} asc",
			limit=MAX_PAGE_LENGTH,
		)
		return [r[fieldname] for r in rows if r.get(fieldname)]

	return {
		"agents": distinct("agent_configuration"),
		"people": distinct("owner_asked"),
		"doctypes": distinct("reference_doctype"),
		"statuses": distinct("status"),
	}


@frappe.whitelist()
def doctypes_with_questions() -> dict:
	"""Which doctypes have ever had a question asked about them.

	The form script runs on every form a person opens, and asking the server
	about every one of them would be a round trip per navigation for a feature
	that applies to a handful of doctypes. This is asked once per page and
	consulted first, so a form of a doctype nobody has ever asked about costs
	nothing.

	Deliberately built from the rows rather than from a configured list: an agent
	pointed at something new starts appearing here the first time it asks, with
	nothing to remember to update.
	"""
	rows = frappe.get_all(
		"AI Clarification",
		filters={"reference_doctype": ["is", "set"]},
		fields=["reference_doctype"],
		group_by="reference_doctype",
		limit=200,
	)
	return {"doctypes": sorted({r["reference_doctype"] for r in rows if r.get("reference_doctype")})}


@frappe.whitelist()
def pending_for_document(reference_doctype: str, reference_name: str) -> dict:
	"""What an agent is currently waiting to be told about this document.

	Also returns what has already been asked and answered, because the thread
	matters: a follow-up reads as pedantic without the answer that failed to
	resolve the first question.
	"""
	if not (reference_doctype and reference_name):
		return {"pending": None, "history": []}

	frappe.has_permission(reference_doctype, doc=reference_name, throw=True)

	rows = frappe.get_all(
		"AI Clarification",
		filters={"reference_doctype": reference_doctype, "reference_name": reference_name},
		fields=list(FIELDS),
		order_by="creation asc",
	)
	pending = next((r for r in rows if r.get("status") == "Awaiting Answer"), None)
	if pending:
		# Only the person who was asked may answer, unless you administer the
		# platform — the value of asking the story owner is lost if anyone can
		# answer on their behalf.
		pending["can_answer"] = bool(
			pending.get("owner_asked") == frappe.session.user
			or "System Manager" in frappe.get_roles()
		)
	return {"pending": pending, "history": [r for r in rows if r.get("status") != "Awaiting Answer"]}


@frappe.whitelist()
def answer(name: str, text: str) -> dict:
	"""Answer the agent's question, and let it carry on.

	Routed through instance_api.complete_task rather than writing the answer
	anywhere directly: that is what validates the person, resumes the suspended
	run exactly once, and hands the answer over as the pending tool's result. A
	shortcut here would be a second way to complete a task, and the two would
	disagree the first time either changed.
	"""
	text = (text or "").strip()
	if not text:
		frappe.throw(_("An answer is needed — the agent is waiting on the actual decision."))

	row = frappe.db.get_value(
		"AI Clarification",
		name,
		["name", "status", "instance", "human_task_id", "owner_asked", "reference_doctype", "reference_name"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Clarification {0} not found.").format(name), frappe.DoesNotExistError)
	if row.status != "Awaiting Answer":
		frappe.throw(_("This question was already {0}.").format(row.status.lower()))
	if not (row.instance and row.human_task_id):
		frappe.throw(_("This question has no pending task to answer — it may have been abandoned."))

	if row.owner_asked != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("This question was asked of {0}. Answering on someone else's behalf would "
			  "defeat the point of asking them.").format(row.owner_asked or _("someone else")),
			frappe.PermissionError,
		)

	from one_bpmn.api.instance_api import complete_task

	complete_task(row.instance, row.human_task_id, frappe.as_json({"answer": text}))
	return {
		"clarification": name,
		"status": frappe.db.get_value("AI Clarification", name, "status"),
		"answered": True,
	}
