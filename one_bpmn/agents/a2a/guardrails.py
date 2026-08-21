# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Delegation guardrails (WI-002008) and the sub-agent allow-list (WI-002010).

One enforcement point for every hand-off, whichever direction it goes:

- **Who** may receive work — ``allowed_delegates`` on the delegating
  agent. It governs BOTH A2A delegation and internal composition, so
  there is a single answer to "who may this agent hand work to".
- **How much** hand-off is allowed — nesting depth and total handoffs in
  one execution chain, each capped by the delegating agent's own
  guardrail fields.

Limits are enforced LOCALLY. A remote may claim any depth it likes in
message metadata; we read that only to keep counting a chain that
started elsewhere, never to decide whether the chain may continue.

A bulk request counts as ONE delegation: the counter moves per task
hand-off, not per item inside it, so legitimate high-volume work is
never mistaken for a loop.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

DEFAULTS = {
	"max_recursion_depth": 5,
	"max_task_handoffs": 10,
	"max_delegation_retries": 3,
}


class DelegationRefused(frappe.ValidationError):
	"""A hand-off that must not happen: off the allow-list, or a limit hit.

	Carries a plain-language reason — it reaches a person, either as the
	failed task's message or as an escalation.
	"""

	def __init__(self, message: str, reason_code: str = "delegation_refused"):
		super().__init__(message)
		self.reason_code = reason_code


def guardrails_for(agent_configuration: str) -> dict:
	"""The delegating agent's own limits, with defaults for anything unset
	(0 or blank means "not configured", never "no delegation allowed")."""
	values = (
		frappe.db.get_value(
			"AI Agent Configuration",
			agent_configuration,
			list(DEFAULTS),
			as_dict=True,
		)
		or {}
	)
	return {field: cint(values.get(field)) or default for field, default in DEFAULTS.items()}


def may_delegate_to(agent_configuration: str, target: str) -> bool:
	"""May this agent hand work to that one? (WI-002010)

	**Exposure is the grant, the list only narrows it.** An agent marked
	Exposed over A2A participates in agent-to-agent work and can receive a
	delegated task; the tools drawn on the delegating agent's process map
	already decide who it actually calls, so a second copy of that decision
	on the configuration would be bookkeeping rather than control.

	Ticking Restrict Delegation on the delegating agent narrows the set to
	the agents it names — for the cases where the map is not a tight enough
	boundary on its own.
	"""
	if not target:
		return False
	if not _participates_in_a2a(target):
		return False
	if not agent_configuration:
		return True
	if not frappe.db.get_value("AI Agent Configuration", agent_configuration, "restrict_delegates"):
		return True
	return bool(
		frappe.db.exists(
			"AI Agent Allowed Delegate",
			{
				"parent": agent_configuration,
				"parenttype": "AI Agent Configuration",
				"agent_configuration": target,
			},
		)
	)


def _participates_in_a2a(target: str) -> bool:
	fields = frappe.db.get_value(
		"AI Agent Configuration", target, ["enabled", "lifecycle_status", "a2a_exposed"], as_dict=True
	)
	return bool(
		fields and fields.enabled and fields.lifecycle_status == "Live" and fields.a2a_exposed
	)


def check_allowed(agent_configuration: str, target: str) -> None:
	if may_delegate_to(agent_configuration, target):
		return
	if not _participates_in_a2a(target):
		raise DelegationRefused(
			_(
				"Agent '{0}' is not available for agent-to-agent work. Tick 'Exposed over A2A' "
				"on it (it must also be enabled and Live)."
			).format(target),
			reason_code="target_not_exposed",
		)
	raise DelegationRefused(
		_("This agent restricts delegation and '{0}' is not on its list.").format(target),
		reason_code="target_not_allowed",
	)


def next_counters(parent_task: str | None) -> dict:
	"""The trace one step further down the chain.

	No parent means this is a top-level request: the chain starts at
	depth 1 with one hand-off and a fresh execution id, so counting never
	carries over from an earlier request.
	"""
	if not parent_task:
		return {"task_execution_id": None, "delegation_depth": 1, "handoff_count": 1}

	parent = (
		frappe.db.get_value(
			"A2A Task",
			parent_task,
			["task_execution_id", "delegation_depth", "handoff_count"],
			as_dict=True,
		)
		or {}
	)
	return {
		"task_execution_id": parent.get("task_execution_id"),
		"delegation_depth": cint(parent.get("delegation_depth")) + 1,
		"handoff_count": chain_handoffs(parent.get("task_execution_id")) + 1,
	}


def chain_handoffs(task_execution_id: str | None) -> int:
	"""How many hand-offs this execution chain has already made. Counted
	from the A2A Task rows themselves — the one counter store — so it is
	the same number whoever asks."""
	if not task_execution_id:
		return 0
	return frappe.db.count("A2A Task", {"task_execution_id": task_execution_id})


def enforce(agent_configuration: str, sub_agent: str, counters: dict) -> None:
	"""The gate every delegation passes through. Raises DelegationRefused
	with a plain reason; the caller marks the task failed and notifies."""
	check_allowed(agent_configuration, sub_agent)
	limits = guardrails_for(agent_configuration)

	depth = cint(counters.get("delegation_depth"))
	if depth > limits["max_recursion_depth"]:
		raise DelegationRefused(
			_(
				"Delegation stopped: agents have nested {0} levels deep, and this agent "
				"allows {1}. This usually means agents are handing work back and forth."
			).format(depth, limits["max_recursion_depth"]),
			reason_code="max_recursion_depth",
		)

	handoffs = cint(counters.get("handoff_count"))
	if handoffs > limits["max_task_handoffs"]:
		raise DelegationRefused(
			_(
				"Delegation stopped: this request has already been handed between agents "
				"{0} times, and this agent allows {1}."
			).format(handoffs, limits["max_task_handoffs"]),
			reason_code="max_task_handoffs",
		)


def trace_metadata(counters: dict) -> dict:
	"""The trace to put in an outgoing message's metadata so a remote can
	keep counting the same chain (WI-002008)."""
	from one_bpmn.agents import a2a_contract

	metadata = {
		a2a_contract.trace_key("delegationDepth"): cint(counters.get("delegation_depth")),
		a2a_contract.trace_key("handoffCount"): cint(counters.get("handoff_count")),
	}
	if counters.get("task_execution_id"):
		metadata[a2a_contract.trace_key("taskExecutionId")] = counters["task_execution_id"]
	return metadata


# ── When a limit stops a chain, tell someone (WI-002008) ─────────────────────


def refusal_recipient(delegating_agent: str | None = None, instance: str | None = None) -> str | None:
	"""Who hears about a stopped delegation chain.

	Preference order, most accountable first:

	1. the **process owner** of the process this instance is running — the
	   person who owns the thing that misbehaved;
	2. the delegating **agent's** process owner, when the running process has
	   none (a map with no Process record behind it);
	3. whoever **set the agent up**, as the last person who touched its
	   configuration;
	4. whoever **started the run**, so the alert always lands somewhere.
	"""
	if instance:
		model = frappe.db.get_value("BPMN Process Instance", instance, "process_model")
		process = (
			frappe.db.get_value("BPMN Process Model", model, "process_name") if model else None
		)
		owner = frappe.db.get_value("Process", process, "process_owner") if process else None
		if owner:
			return owner

	if delegating_agent:
		fields = (
			frappe.db.get_value(
				"AI Agent Configuration", delegating_agent, ["process_owner", "owner"], as_dict=True
			)
			or {}
		)
		if fields.get("process_owner"):
			return fields["process_owner"]
		if fields.get("owner") and fields["owner"] != "Administrator":
			return fields["owner"]

	if instance:
		started_by = frappe.db.get_value("BPMN Process Instance", instance, "initiated_by")
		if started_by:
			return started_by
	return None


def notify_refusal(
	refusal: DelegationRefused,
	*,
	delegating_agent: str | None = None,
	instance: str | None = None,
	a2a_task: str | None = None,
) -> str | None:
	"""Put the plain-language reason in front of a person, and return who got
	it. Never raises: a failed alert must not also break the process."""
	recipient = refusal_recipient(delegating_agent, instance)
	if not recipient:
		return None
	try:
		note = frappe.new_doc("Notification Log")
		note.for_user = recipient
		note.type = "Alert"
		note.subject = _("An agent delegation was stopped")
		note.email_content = str(refusal)
		if a2a_task:
			note.document_type = "A2A Task"
			note.document_name = a2a_task
		elif instance:
			note.document_type = "BPMN Process Instance"
			note.document_name = instance
		note.insert(ignore_permissions=True)
		return recipient
	except Exception:
		frappe.log_error(
			title="A2A delegation refusal: notification failed", message=frappe.get_traceback()
		)
		return None


# A limit breach is worth a record; an off-the-list target is a configuration
# mistake that never became work, so it leaves nothing behind.
#
# These are the DOOR-TIME limits: checked by enforce() before anything starts,
# so a breach means no task row exists yet and record_limit_breach() has to
# create one. Deliberately NOT widened to cover the in-flight limits below —
# those already have a task row and a running worker, so putting them through
# record_limit_breach() would mint a second, duplicate row for work that had
# already begun.
LIMIT_REASONS = ("max_recursion_depth", "max_task_handoffs")

# The limits reached while the worker is already running. They share the
# escalation seam (agents/a2a/delegation.stopped_at_limit) but not the
# record-creating one, because there is nothing left to create.
#
# max_delegation_retries is absent on purpose: it is a configured field with a
# default in DEFAULTS above, and nothing in the codebase retries a delegation,
# so there is no moment at which it could fire. Implementing retry is its own
# story; a branch here would be unreachable code pretending to be a control.
IN_FLIGHT_LIMIT_REASONS = ("delegation_deadline_minutes", "turn_cap")


def record_limit_breach(
	refusal: DelegationRefused,
	*,
	delegating_agent: str | None = None,
	target: str | None = None,
	instance: str | None = None,
	caller_wf_task_id: str | None = None,
	bpmn_id: str | None = None,
	counters: dict | None = None,
) -> str | None:
	"""Leave a failed task behind when a LIMIT stopped the chain, so the
	monitor shows what happened and the alert has something to point at."""
	if refusal.reason_code not in LIMIT_REASONS:
		return None
	counters = counters or {}
	try:
		doc = frappe.get_doc(
			{
				"doctype": "A2A Task",
				"direction": "Internal",
				"state": "failed",
				"agent_configuration": target,
				"delegated_by": delegating_agent,
				"caller_instance": instance,
				"caller_wf_task_id": caller_wf_task_id,
				"bpmn_id": bpmn_id,
				"error_code": refusal.reason_code,
				"error_message": str(refusal)[:500],
				"task_execution_id": counters.get("task_execution_id"),
				"delegation_depth": counters.get("delegation_depth"),
				"handoff_count": counters.get("handoff_count"),
				# Nothing parked, so nothing is waiting to be woken.
				"resume_enqueued": 1,
				"completed_at": frappe.utils.now_datetime(),
			}
		)
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception:
		frappe.log_error(
			title="A2A delegation refusal: could not record the breach",
			message=frappe.get_traceback(),
		)
		return None
