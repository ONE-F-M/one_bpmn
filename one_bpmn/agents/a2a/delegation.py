# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Agent Delegation records, and telling a person when one stops at a limit.

Two jobs, and they belong together because the second needs the first.

**Tracking.** An A2A Task says who was asked. It does not say what the work was
about. ``record()`` writes an Agent Delegation row that ties the delegating
instance, the task, the worker's instance and the document being worked on into
one thing a process owner can open, and ``sync_from_task()`` keeps its status
following the task's state.

**Escalation.** WI-002008 already notifies when a delegation is refused at the
door — depth or hand-off limits, checked before anything starts. Nothing covered
a limit reached while the worker was already running, and there are three of
those: the deadline expiring, and the worker ending at its own turn cap. Those
were silent. The deadline set ``state="timed-out"`` and woke the caller; the turn
cap returned whatever partial text the agent had, which at a glance is
indistinguishable from finishing.

``stopped_at_limit()`` is the seam for all of them. It marks the delegation
Needs Review — the work stopped, it did not finish, and a person has to decide
what happens next — notifies the accountable person once, and leaves a comment
on the referenced document so the decision survives the alert being dismissed.

Idempotency matters here more than usual: the reconciler runs on a schedule, so
without a guard it would tell the same person about the same breach on every
tick. ``notified_at`` on the delegation row is that guard.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from one_bpmn.agents.a2a import guardrails

# A2A Task state → Agent Delegation status. "timed-out" is deliberately absent:
# a timeout is a limit breach, which goes through stopped_at_limit() so it lands
# on Needs Review rather than Failed — a person must look at it, and Failed
# reads as "nothing to do here".
_STATUS_FROM_STATE = {
	"submitted": "Delegated",
	"working": "In Progress",
	"input-required": "In Progress",
	"completed": "Completed",
	"failed": "Failed",
	"canceled": "Failed",
	"rejected": "Failed",
}

# Plain words for each limit, for the person reading the alert. The field name
# is precise but it is not what someone wants to read at 9am.
LIMIT_LABELS = {
	"max_recursion_depth": "nesting depth",
	"max_task_handoffs": "hand-offs between agents",
	"delegation_deadline_minutes": "time allowed",
	"turn_cap": "tool-calling turns",
	"max_delegation_retries": "retries",
}

_TERMINAL = ("Completed", "Failed", "Needs Review")


def limit_note(a2a_task: str | None) -> str:
	"""One sentence for the DELEGATING MODEL when its worker stopped at a limit.

	The worker's own answer only reports what it managed to produce — "the
	connector agent produced no answer" — which reads exactly like a transient
	outage. In testing the orchestrator read it that way and told the reporter
	the specialist was "unable to complete or respond right now", when the truth
	was a configured limit that would stop the next attempt the same way. The
	comment on the work item said so; the model was the one party never told.

	Same rule as the refusal path in a2a_client_ops: the reason exists, so it
	reaches the model. Returns "" when nothing stopped the delegation, so the
	normal answer is passed through untouched.
	"""
	if not a2a_task:
		return ""
	row = frappe.db.get_value(
		"Agent Delegation",
		{"a2a_task": a2a_task},
		["stopped_reason", "limit_value", "reached_value"],
		as_dict=True,
	)
	if not row or not row.stopped_reason:
		return ""

	label = LIMIT_LABELS.get(row.stopped_reason, row.stopped_reason)
	numbers = ""
	if cint(row.limit_value):
		numbers = f" — {cint(row.reached_value)} against a limit of {cint(row.limit_value)}"
	return (
		f" It stopped before finishing because it reached the limit on {label}{numbers}, so "
		"whatever it did send back is partial and the work is NOT done. This is a configured "
		"limit rather than a transient failure: handing the same work over again will stop the "
		"same way until someone raises the limit. Report that it stopped at a limit — do not "
		"describe it as unavailable, and do not claim the work was completed."
	)


def _reference_for(instance_name: str | None) -> tuple[str | None, str | None]:
	"""What the delegating instance is about.

	Read from the instance's own context document rather than passed in by the
	caller, because the caller does not reliably know. On the Software
	Development path the orchestrator is a Call Activity, so the delegating
	instance is the CALLER's — and its context is the Work Item, which is
	exactly what we want. In the A2A test harness the same lookup yields an A2A
	Task, which is why this reference is generic.
	"""
	if not instance_name:
		return None, None
	row = frappe.db.get_value(
		"BPMN Process Instance", instance_name, ["context_doctype", "context_docname"], as_dict=True
	)
	if not row or not (row.context_doctype and row.context_docname):
		return None, None

	# reference_name is a Dynamic Link, so it is link-validated on insert. An
	# instance whose context document has since been deleted would therefore
	# take the WHOLE delegation record down with it — losing the tracking row
	# for a delegation that really happened. Losing the reference is the lesser
	# failure by a distance, so a stale one is simply dropped.
	try:
		if not frappe.db.exists(row.context_doctype, row.context_docname):
			return None, None
	except Exception:
		return None, None
	return row.context_doctype, row.context_docname


def for_task(a2a_task: str) -> str | None:
	"""The delegation row for a task, if one was recorded."""
	if not a2a_task:
		return None
	return frappe.db.get_value("Agent Delegation", {"a2a_task": a2a_task}, "name")


def record(task, *, delegating_agent: str | None, instruction: str = "") -> str | None:
	"""Write the Agent Delegation row for a delegation that just started.

	Never raises. A delegation that ran but could not be recorded is worse
	tracked, not broken — the A2A Task is still the source of truth for
	execution, and this row is the view onto it.
	"""
	try:
		existing = for_task(task.name)
		if existing:
			return existing
		ref_doctype, ref_name = _reference_for(task.caller_instance)
		doc = frappe.new_doc("Agent Delegation")
		doc.update({
			"delegating_agent": delegating_agent or None,
			"worker_agent": task.agent_configuration,
			"status": _STATUS_FROM_STATE.get(task.state, "Delegated"),
			"orchestrator_instance": task.caller_instance or None,
			"worker_instance": task.instance or None,
			"a2a_task": task.name,
			"reference_doctype": ref_doctype,
			"reference_name": ref_name,
			"delegation_depth": cint(task.delegation_depth),
			"handoff_count": cint(task.handoff_count),
			"started_at": now_datetime(),
			"instruction": (instruction or "")[:500],
		})
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception:
		frappe.log_error(
			title="Agent Delegation: could not record a delegation",
			message=frappe.get_traceback(),
		)
		return None


def record_refusal(
	refusal,
	*,
	delegating_agent: str | None,
	target: str,
	a2a_task: str | None,
	counters: dict,
	instance: str | None = None,
) -> str | None:
	"""A delegation refused at the door: Failed, with the limit that stopped it.

	This is the WI-002008 path. It already created a failed A2A Task and
	notified; all that was missing was the record saying which limit, and what
	it reached.
	"""
	reason = getattr(refusal, "reason_code", None)
	if reason not in guardrails.LIMIT_REASONS:
		# An off-the-list target never became work, so it leaves no row —
		# same rule record_limit_breach() already applies.
		return None
	try:
		limits = guardrails.guardrails_for(delegating_agent)
		reached = (
			cint(counters.get("delegation_depth"))
			if reason == "max_recursion_depth"
			else cint(counters.get("handoff_count"))
		)
		doc = frappe.new_doc("Agent Delegation")
		doc.update({
			"delegating_agent": delegating_agent or None,
			"worker_agent": target,
			"status": "Failed",
			"stopped_reason": reason,
			"a2a_task": a2a_task or None,
			"delegation_depth": cint(counters.get("delegation_depth")),
			"handoff_count": cint(counters.get("handoff_count")),
			"limit_value": cint(limits.get(reason)),
			"reached_value": reached,
			"started_at": now_datetime(),
			"ended_at": now_datetime(),
			"error_message": str(refusal)[:500],
		})
		ref_doctype, ref_name = _reference_for(instance)
		doc.reference_doctype = ref_doctype
		doc.reference_name = ref_name
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)

		# The same trail the in-flight path leaves. notify_refusal() puts a
		# Notification Log in front of a person, but that is gone once
		# dismissed — and it is not even created when no recipient resolves,
		# which is every Administrator-owned agent on a site whose Processes
		# name no owner. The comment is what is still there afterwards.
		_comment_on_reference(
			ref_doctype,
			ref_name,
			_limit_message(
				worker=target,
				reason=reason,
				limit_value=cint(limits.get(reason)),
				reached_value=reached,
				detail=str(refusal),
				ref_doctype=ref_doctype,
				ref_name=ref_name,
			),
		)
		return doc.name
	except Exception:
		frappe.log_error(
			title="Agent Delegation: could not record a refusal",
			message=frappe.get_traceback(),
		)
		return None


def sync_from_task(task) -> None:
	"""Follow the A2A Task's state onto the delegation row.

	Needs Review is sticky. A worker whose deadline expired can still finish
	its own instance a moment later and drive the task to "completed"; letting
	that overwrite Needs Review would erase the very thing a person was asked
	to look at.
	"""
	try:
		name = for_task(getattr(task, "name", None))
		if not name:
			return
		status = _STATUS_FROM_STATE.get(task.state)
		if not status:
			return
		current = frappe.db.get_value("Agent Delegation", name, "status")
		if current == "Needs Review":
			return
		changed = {"status": status}
		if status in _TERMINAL:
			changed["ended_at"] = now_datetime()
		if task.instance:
			changed["worker_instance"] = task.instance
		if getattr(task, "error_message", None):
			changed["error_message"] = str(task.error_message)[:500]
		frappe.db.set_value("Agent Delegation", name, changed, update_modified=True)
	except Exception:
		frappe.log_error(
			title="Agent Delegation: could not sync a delegation",
			message=frappe.get_traceback(),
		)


# ── Retry: max_delegation_retries, finally wired to something ────────────────
#
# The field has existed with a default of 3 since WI-002008 and nothing read it,
# because nothing retried a delegation. Four decisions make it a control rather
# than a setting, and each is a judgement worth stating:
#
# 1. Only a FAILED worker is retried. A timed-out one is not — its time is up,
#    and that is the deadline escalation's business. A refusal at the door is not
#    either: off the allow-list or past the depth limit is a configuration
#    outcome, and repeating it only delays the escalation.
# 2. The A2A Task row is REUSED, so one delegation stays one row and Agent
#    Delegation keeps its single a2a_task link. The count lives on the delegation
#    record, which is also what WI-002060's dashboard needs.
# 3. A retry does NOT consume a hand-off and does NOT increase nesting depth. It
#    is the same hand-off attempted again; counting it otherwise would trip the
#    loop guards on a delegation that is working correctly.
# 4. The deadline does NOT restart. Someone who allowed 120 minutes meant 120
#    minutes for the work, not 120 per attempt — a restart would let a flapping
#    worker run for retries x deadline in total.


def attempts_allowed(delegating_agent: str | None) -> int:
	"""How many times in total the worker may be run: the first attempt plus the
	configured retries."""
	return 1 + cint(guardrails.guardrails_for(delegating_agent).get("max_delegation_retries"))


def should_retry(a2a_task: str | None) -> bool:
	"""Has this failed delegation got an attempt left?"""
	name = for_task(a2a_task)
	if not name:
		return False
	row = frappe.db.get_value(
		"Agent Delegation", name, ["attempt_count", "delegating_agent", "status"], as_dict=True
	)
	if not row or row.status == "Needs Review":
		return False
	return cint(row.attempt_count) < attempts_allowed(row.delegating_agent)


def note_attempt(a2a_task: str | None) -> int:
	"""Count another run of the worker. Returns the new attempt number."""
	name = for_task(a2a_task)
	if not name:
		return 0
	current = cint(frappe.db.get_value("Agent Delegation", name, "attempt_count")) or 1
	frappe.db.set_value(
		"Agent Delegation",
		name,
		{"attempt_count": current + 1, "status": "In Progress", "error_message": None},
		update_modified=True,
	)
	return current + 1


def retries_exhausted(a2a_task: str | None, *, detail: str = "") -> bool:
	"""The last retry is used and it still has not completed — escalate through
	the same seam every other limit uses."""
	name = for_task(a2a_task)
	if not name:
		return False
	row = frappe.db.get_value(
		"Agent Delegation", name, ["attempt_count", "delegating_agent", "worker_agent"], as_dict=True
	)
	allowed = attempts_allowed(row.delegating_agent if row else None)
	return stopped_at_limit(
		a2a_task=a2a_task,
		reason="max_delegation_retries",
		limit_value=allowed,
		reached_value=cint(row.attempt_count) if row else 0,
		detail=(
			detail
			or f"The worker was run {cint(row.attempt_count) if row else 0} time(s) and failed each time."
		),
		worker_agent=row.worker_agent if row else None,
		delegating_agent=row.delegating_agent if row else None,
	)


def stopped_at_limit(
	*,
	a2a_task: str | None,
	reason: str,
	limit_value: int = 0,
	reached_value: int = 0,
	detail: str = "",
	instance: str | None = None,
	worker_agent: str | None = None,
	delegating_agent: str | None = None,
) -> bool:
	"""A delegation stopped mid-flight because a limit was reached.

	Marks it Needs Review, tells the accountable person once, and leaves the
	trail on the referenced document. Returns True when a person was told, so
	callers can log it; never raises — an escalation that fails must not also
	break the reconciler that noticed.
	"""
	try:
		name = for_task(a2a_task)
		row = (
			frappe.db.get_value(
				"Agent Delegation",
				name,
				[
					"notified_at",
					"worker_agent",
					"delegating_agent",
					"orchestrator_instance",
					"reference_doctype",
					"reference_name",
				],
				as_dict=True,
			)
			if name
			else None
		)

		# Idempotent per breach: the reconciler sees the same stopped delegation
		# on every tick, and a person needs telling once.
		if row and row.notified_at:
			return False

		if name:
			frappe.db.set_value(
				"Agent Delegation",
				name,
				{
					"status": "Needs Review",
					"stopped_reason": reason,
					"limit_value": cint(limit_value),
					"reached_value": cint(reached_value),
					"ended_at": now_datetime(),
					"error_message": (detail or "")[:500],
				},
				update_modified=True,
			)

		worker = (row.worker_agent if row else None) or worker_agent
		delegator = (row.delegating_agent if row else None) or delegating_agent
		caller_instance = (row.orchestrator_instance if row else None) or instance
		ref_doctype = row.reference_doctype if row else None
		ref_name = row.reference_name if row else None
		if not ref_name:
			ref_doctype, ref_name = _reference_for(caller_instance)

		recipient = guardrails.refusal_recipient(delegator, caller_instance)
		message = _limit_message(
			worker=worker,
			reason=reason,
			limit_value=limit_value,
			reached_value=reached_value,
			detail=detail,
			ref_doctype=ref_doctype,
			ref_name=ref_name,
		)

		# The trail goes on first: it must survive whether or not the alert
		# lands, and whether or not anyone opens it.
		_comment_on_reference(ref_doctype, ref_name, message)

		told = _notify(recipient, message, a2a_task=a2a_task, delegation=name)
		if name and told:
			frappe.db.set_value(
				"Agent Delegation",
				name,
				{"notified_user": recipient, "notified_at": now_datetime()},
				update_modified=False,
			)
		return bool(told)
	except Exception:
		frappe.log_error(
			title="Agent Delegation: could not escalate a stopped delegation",
			message=frappe.get_traceback(),
		)
		return False


def _limit_message(
	*, worker, reason, limit_value, reached_value, detail, ref_doctype, ref_name
) -> str:
	"""What the person reads. Names the agent, the item, the limit and the
	number it reached, because "a limit was hit" is not actionable."""
	label = LIMIT_LABELS.get(reason, reason)
	about = f" while working on {ref_doctype} {ref_name}" if ref_name else ""
	lines = [
		f"<b>{frappe.utils.escape_html(str(worker or 'An agent'))}</b> stopped before "
		f"finishing{frappe.utils.escape_html(about)}."
	]
	if cint(limit_value):
		lines.append(
			f"It reached the limit on {label}: {cint(reached_value)} against a limit of "
			f"{cint(limit_value)}."
		)
	else:
		lines.append(f"It reached the limit on {label}.")
	if detail:
		lines.append(frappe.utils.escape_html(str(detail)))
	lines.append(
		"The work is <b>not</b> finished. Nothing has been re-delegated automatically — "
		"raise the limit and hand it over again, or take it on yourself."
	)
	return "<br>".join(lines)


def _comment_on_reference(ref_doctype: str | None, ref_name: str | None, message: str) -> None:
	"""The auditable record, on the document the work was about.

	A Notification Log entry is gone once dismissed. A comment on the Work Item
	is what is still there when someone asks in a fortnight why this stalled.
	"""
	if not (ref_doctype and ref_name):
		return
	try:
		if not frappe.db.exists(ref_doctype, ref_name):
			return
		frappe.get_doc(ref_doctype, ref_name).add_comment(
			"Comment", f"<b>Delegation stopped at a limit</b><br>{message}"
		)
	except Exception:
		frappe.log_error(
			title="Agent Delegation: could not comment on the reference document",
			message=frappe.get_traceback(),
		)


def _notify(recipient: str | None, message: str, *, a2a_task=None, delegation=None) -> str | None:
	"""In-app alert plus an email, and return who was told.

	Both, deliberately. A stopped delegation expects someone to act, and an
	in-app alert nobody opens is not a notification. It is a rare event, so
	there is no inbox to flood.
	"""
	if not recipient:
		return None
	subject = _("A delegated agent stopped before finishing")
	try:
		note = frappe.new_doc("Notification Log")
		note.for_user = recipient
		note.type = "Alert"
		note.subject = subject
		note.email_content = message
		if delegation:
			note.document_type = "Agent Delegation"
			note.document_name = delegation
		elif a2a_task:
			note.document_type = "A2A Task"
			note.document_name = a2a_task
		note.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="Agent Delegation: in-app alert failed", message=frappe.get_traceback()
		)

	try:
		from one_fm.processor import sendemail

		sendemail(
			recipients=[recipient],
			subject=subject,
			message=message,
			is_external_mail=True,
		)
	except Exception:
		# The in-app alert above still stands, so a mail failure is logged and
		# swallowed rather than losing the escalation entirely.
		frappe.log_error(
			title="Agent Delegation: escalation email failed", message=frappe.get_traceback()
		)
	return recipient
