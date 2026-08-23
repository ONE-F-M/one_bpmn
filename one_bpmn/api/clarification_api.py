# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Answering an agent's question from the document it is about (WI-002050).

The pending question is a task on a process instance, and the person who can
settle it is the one who wrote the story. Those are not the same screen. Asking
a story owner to open a process instance to unblock their own story is asking
them to learn the machinery to answer a question about their own requirement.

So the question surfaces on the work item, and this is the door: read what is
pending, and answer it. The answer goes through the SAME entry point a user task
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
