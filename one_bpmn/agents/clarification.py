# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Asking the story owner instead of guessing (WI-002050).

The pause itself is not new. A User shape drawn inside an agent's tool
sub-process is already a human tool: the model selecting it suspends the run
against a real waiting task, and the person's answer comes back as that tool's
result when they complete it. That is the same shape Camunda documents (BPMN
activities inside an ad-hoc sub-process are the agent's tools, and a user task
is one of them) and the same shape LangGraph's ``interrupt()`` takes.

What this module adds is the part a suspension alone does not give you:

**A record.** The question and the answer only existed inside the run's
transcript, so "why was it built this way" had no answer a fortnight later. Every
question an agent asks a person is now an AI Clarification row, and the pair is
written onto the work item as a comment as well — an alert is dismissed, a
comment stays.

**Somebody to ask.** The question goes to the person who set the requirement —
the work item's reporter — rather than to whoever the map happened to name.

**A limit on asking.** The measured failure mode is not silence, it is noise:
models default to not asking at all until told to, and told too forcefully they
ask unnecessary questions. So the rounds are capped per agent, and hitting the
cap escalates rather than guesses.

**Somebody chasing it.** Nothing ever looked at a question nobody answered. A
pending clarification is reminded once and then raised with the process owner,
and it still never resolves itself — an unanswered ambiguity is not a licence to
assume.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, now_datetime

# How the question and the interpretations arrive from the model. The tool's
# aiToolParams name them, and a shape that asks for nothing still records the
# label so the row is never blank.
QUESTION_KEYS = ("question", "ambiguity", "text", "prompt")
INTERPRETATION_KEYS = ("interpretations", "options", "choices", "alternatives")

# What the person's answer arrives as. instance_api hands the task's data
# straight through, so anything the form collected is here.
ANSWER_KEYS = ("answer", "response", "clarification", "value", "comment")

_TERMINAL = ("Answered", "Escalated", "Abandoned")


def _first(data: dict, keys) -> str:
	for key in keys:
		value = (data or {}).get(key)
		if value is None:
			continue
		if isinstance(value, (list, tuple)):
			value = ", ".join(str(v) for v in value if v)
		text = str(value).strip()
		if text:
			return text
	return ""


def story_owner(reference_doctype: str | None, reference_name: str | None) -> str | None:
	"""Who set the requirement, and therefore who can settle what it meant.

	The work item's reporter, not its owner: on this site the owner is usually
	Administrator (the record was created by an import or a duplicate) while the
	reporter is the person who actually wrote the story. Asking the owner would
	route half the questions to a service account.

	Falls back to the record's creator only when there is no reporter at all,
	because a question with nobody to answer it is worse than a question to the
	wrong person — the second gets forwarded, the first stalls silently.
	"""
	if not (reference_doctype and reference_name):
		return None
	meta = frappe.get_meta(reference_doctype)
	for fieldname in ("reporter_user", "raised_by", "owner"):
		if not meta.has_field(fieldname) and fieldname != "owner":
			continue
		user = frappe.db.get_value(reference_doctype, reference_name, fieldname)
		if user and user != "Guest":
			return user
	return None


def rounds_allowed(agent_configuration: str | None) -> int:
	"""How many times this agent may ask about one piece of work.

	0 means no limit. A cap is worth having because the documented failure of
	interactive agents is over-asking — a question that adds friction without
	improving the outcome — and because a story that has been queried three
	times is telling you something about the story, not about the agent.
	"""
	if not agent_configuration:
		return 0
	return cint(
		frappe.db.get_value(
			"AI Agent Configuration", agent_configuration, "max_clarification_rounds"
		)
	)


def rounds_used(reference_doctype: str | None, reference_name: str | None) -> int:
	"""Questions already asked about this work, answered or not.

	Counted per document rather than per run: a story handed back or retried is
	the same story, and resetting the count on a new run would make the cap
	meaningless.
	"""
	if not (reference_doctype and reference_name):
		return 0
	return frappe.db.count(
		"AI Clarification",
		{"reference_doctype": reference_doctype, "reference_name": reference_name},
	)


def cap_reached(agent_configuration, reference_doctype, reference_name) -> bool:
	allowed = rounds_allowed(agent_configuration)
	return bool(allowed) and rounds_used(reference_doctype, reference_name) >= allowed


def record_question(
	*,
	instance,
	human_task_id: str,
	agent_configuration: str | None,
	agent_run: str | None,
	arguments: dict,
	label: str = "",
	assigned_user: str | None = None,
) -> str | None:
	"""Write down what was asked, the moment the agent suspends.

	Never raises. A question that could not be recorded is worse tracked, not
	unasked — the person still has the task in front of them, and breaking the
	suspension to protect the audit trail would lose the run as well as the row.
	"""
	try:
		reference_doctype = getattr(instance, "context_doctype", None)
		reference_name = getattr(instance, "context_docname", None)
		question = _first(arguments, QUESTION_KEYS) or (label or "").strip()
		previous = frappe.get_all(
			"AI Clarification",
			filters={"reference_doctype": reference_doctype, "reference_name": reference_name},
			fields=["name"],
			order_by="creation desc",
			limit=1,
		)
		doc = frappe.new_doc("AI Clarification")
		doc.update({
			"agent_configuration": agent_configuration,
			"asked_by_agent_run": agent_run,
			"instance": getattr(instance, "name", None),
			"human_task_id": human_task_id,
			"round": rounds_used(reference_doctype, reference_name) + 1,
			# A follow-up is chained so the thread reads in order later. The story
			# requires a follow-up when an answer does not resolve the ambiguity,
			# and a chain is what makes "we asked twice" visible.
			"follow_up_of": previous[0].name if previous else None,
			"status": "Awaiting Answer",
			"question": question[:500],
			"interpretations": _first(arguments, INTERPRETATION_KEYS)[:500],
			"asked_at": now_datetime(),
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"owner_asked": assigned_user or story_owner(reference_doctype, reference_name),
		})
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)

		_comment(
			reference_doctype,
			reference_name,
			_("<b>{0} asked a question and paused</b><br>{1}{2}").format(
				frappe.utils.escape_html(agent_configuration or _("An agent")),
				frappe.utils.escape_html(question),
				_("<br><i>Choosing between:</i> {0}").format(
					frappe.utils.escape_html(doc.interpretations)
				)
				if doc.interpretations
				else "",
			),
			agent_configuration=agent_configuration,
		)
		return doc.name
	except Exception:
		frappe.log_error(
			title="AI Clarification: could not record the question",
			message=frappe.get_traceback(),
		)
		return None


def record_answer(*, instance, human_task_id: str, data: dict) -> str | None:
	"""Close the question with what the person actually said.

	Whether the answer RESOLVES the ambiguity is not decided here — that is the
	agent's judgement, and if it does not, the agent asks again and the next row
	chains onto this one. Deciding it here would mean guessing at the thing the
	whole story exists to avoid guessing at.
	"""
	try:
		name = frappe.db.get_value(
			"AI Clarification",
			{"instance": getattr(instance, "name", None), "human_task_id": human_task_id},
			"name",
		)
		if not name:
			return None
		answer = _first(data, ANSWER_KEYS)
		if not answer and data:
			# The form may have collected fields nobody here knows the names of.
			# Better to keep them verbatim than to record an empty answer.
			answer = ", ".join(f"{k}: {v}" for k, v in data.items() if v)
		doc = frappe.get_doc("AI Clarification", name)
		doc.db_set(
			{
				"status": "Answered",
				"answer": (answer or _("(answered without text)"))[:500],
				"answered_by": frappe.session.user,
				"answered_at": now_datetime(),
			},
			update_modified=True,
		)
		_comment(
			doc.reference_doctype,
			doc.reference_name,
			_("<b>Question answered by {0}</b><br><i>Asked:</i> {1}<br><i>Answered:</i> {2}").format(
				frappe.utils.escape_html(frappe.session.user),
				frappe.utils.escape_html(doc.question or ""),
				frappe.utils.escape_html(answer or ""),
			),
			agent_configuration=doc.agent_configuration,
		)
		return name
	except Exception:
		frappe.log_error(
			title="AI Clarification: could not record the answer",
			message=frappe.get_traceback(),
		)
		return None


def chase_unanswered(reminder_minutes: int = 60, escalate_minutes: int = 1440) -> dict:
	"""Nudge, then raise it with the process owner. Never answer it.

	Every source on human-in-the-loop work says the same thing: do not block
	indefinitely and do not proceed on a timeout. So a pending question is
	reminded once, then escalated once, and stays Awaiting Answer either way —
	the agent remains blocked, which is the point. Auto-resolving an ambiguity
	after a wait would be guessing with extra steps.
	"""
	now = now_datetime()
	reminded = escalated = 0
	for row in frappe.get_all(
		"AI Clarification",
		filters={"status": "Awaiting Answer"},
		fields=[
			"name", "asked_at", "reminded_at", "escalated_at", "owner_asked",
			"question", "reference_doctype", "reference_name", "instance",
			"agent_configuration",
		],
	):
		waited = (now - frappe.utils.get_datetime(row.asked_at)).total_seconds() / 60 if row.asked_at else 0

		if not row.escalated_at and waited >= escalate_minutes:
			owner = _process_owner(row)
			if owner:
				_notify(
					owner,
					_("A question to the story owner has gone unanswered"),
					_(
						"{0} asked about {1} {2} and has been waiting {3} hour(s). It is still "
						"blocked and will not proceed on an assumption.<br><br>{4}"
					).format(
						row.agent_configuration or _("An agent"),
						row.reference_doctype or "",
						row.reference_name or "",
						int(waited // 60),
						frappe.utils.escape_html(row.question or ""),
					),
					row.name,
				)
			frappe.db.set_value(
				"AI Clarification", row.name,
				{"escalated_at": now, "escalated_to": owner}, update_modified=False,
			)
			escalated += 1
			continue

		if not row.reminded_at and waited >= reminder_minutes:
			if row.owner_asked:
				_notify(
					row.owner_asked,
					_("An agent is waiting on your answer"),
					_(
						"{0} paused on {1} {2} and needs your answer before it goes any "
						"further.<br><br>{3}"
					).format(
						row.agent_configuration or _("An agent"),
						row.reference_doctype or "",
						row.reference_name or "",
						frappe.utils.escape_html(row.question or ""),
					),
					row.name,
				)
			frappe.db.set_value(
				"AI Clarification", row.name, "reminded_at", now, update_modified=False
			)
			reminded += 1

	return {"reminded": reminded, "escalated": escalated}


def _process_owner(row) -> str | None:
	"""Who hears about a question nobody answered — the process owner of the
	running process, falling back to the person who was asked's manager-less
	last resort, the run's initiator."""
	from one_bpmn.agents.a2a import guardrails

	return guardrails.refusal_recipient(row.get("agent_configuration"), row.get("instance"))


def _notify(recipient: str, subject: str, message: str, clarification: str) -> None:
	try:
		note = frappe.new_doc("Notification Log")
		note.for_user = recipient
		note.type = "Alert"
		note.subject = subject
		note.email_content = message
		note.document_type = "AI Clarification"
		note.document_name = clarification
		note.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="AI Clarification: could not notify", message=frappe.get_traceback()
		)


def _comment(reference_doctype, reference_name, html, agent_configuration=None) -> None:
	"""The auditable half. A notification is gone once dismissed; the question
	and the answer belong on the work item, where the next person to ask "why is
	it built this way" is already looking.

	Signed by the AGENT, not by whoever happened to be logged in. Both of these
	comments narrate what the agent did — it asked, and it received an answer —
	and add_comment owns a comment as the session user, which on a chat turn or a
	form action is a person. So the thread read "You commented: Orchestrator Agent
	asked a question", with the same person credited on both sides of a
	conversation they only took one side of. The answer comment already names who
	answered, in its text, which is where that belongs.
	"""
	if not (reference_doctype and reference_name):
		return
	try:
		if not frappe.db.exists(reference_doctype, reference_name):
			return
		from one_bpmn.agents import identity

		if identity.comment_as(agent_configuration, reference_doctype, reference_name, html):
			return
		# No agent, or no identity provisioned for it: better an attributed-to-a-
		# person comment than no record at all.
		frappe.get_doc(reference_doctype, reference_name).add_comment("Comment", html)
	except Exception:
		frappe.log_error(
			title="AI Clarification: could not comment on the document",
			message=frappe.get_traceback(),
		)
