# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Agent-to-agent delegation on the SAME site (WI-001933).

This is the primary case: an orchestrator handing a task to a specialist
that lives in the same bench. Nothing crosses a trust boundary, so none
of the machinery that exists to make an untrusted caller safe applies —
no registry entry, no approved client, no service-user key, no HTTP hop,
and no exposure flag on the target. Requiring any of that for two agents
on one site would be ceremony that buys nothing: you already trust
yourself.

What DOES still apply, because it is about scope and loops rather than
authentication:

- the delegating agent's ``allowed_delegates`` list — who it may hand
  work to at all;
- its guardrails — nesting depth and total handoffs in the chain.

The task row is created exactly as the network path creates one (so the
monitor, the counters and the audit trail are identical) with direction
``Internal``, and the agent runs through the same ``execute`` module the
inbound door uses. A fast agent answers inline; a slow one leaves the row
non-terminal and the caller parks, which the poller then reconciles
locally — no network call involved.
"""

from __future__ import annotations

import frappe
from frappe import _

from one_bpmn.agents.a2a import delegation, execute, guardrails

TARGET_FIELDS = (
	"name",
	"agent_id",
	"agent_name",
	"enabled",
	"lifecycle_status",
	"agent_type",
	"process_model",
)

DEFAULT_DEADLINE_MINUTES = 240


def local_agent_choices() -> list[str]:
	"""Dropdown source: agents that can actually be handed work today.

	Filtered by a2a_exposed: that flag is what marks an agent as taking part
	in agent-to-agent work at all, local or remote.
	"""
	return frappe.get_all(
		"AI Agent Configuration",
		filters={"enabled": 1, "lifecycle_status": "Live", "a2a_exposed": 1},
		order_by="agent_name asc",
		pluck="name",
	)


def resolve_target(agent: str):
	"""Accept a configuration name or an agent_id; require it to be usable."""
	target = None
	if frappe.db.exists("AI Agent Configuration", agent):
		target = frappe.db.get_value("AI Agent Configuration", agent, TARGET_FIELDS, as_dict=True)
	if not target:
		target = frappe.db.get_value(
			"AI Agent Configuration", {"agent_id": agent}, TARGET_FIELDS, as_dict=True
		)
	if not target:
		raise guardrails.DelegationRefused(
			_("There is no agent '{0}' on this site.").format(agent),
			reason_code="unknown_agent",
		)
	if not (target.enabled and target.lifecycle_status == "Live"):
		raise guardrails.DelegationRefused(
			_("Agent '{0}' is not live, so work cannot be handed to it.").format(target.agent_name),
			reason_code="target_not_live",
		)
	# Whether it may RECEIVE work is guardrails' call (exposure, plus any
	# restriction the delegating agent sets) — checked in delegate().
	return target


def delegate(
	delegating_agent: str,
	target: str,
	instruction: str,
	*,
	parent_task: str | None = None,
	caller_instance: str | None = None,
	caller_wf_task_id: str | None = None,
	bpmn_id: str | None = None,
	input_assignee: str | None = None,
	input_role: str | None = None,
	deadline_minutes: int | None = None,
	required_capability: str | None = None,
):
	"""Hand a task to a local agent. Returns the A2A Task row.

	The guardrails run BEFORE anything is created, so a refused delegation
	leaves no trace of work that never started.
	"""
	config = resolve_target(target)
	counters = guardrails.next_counters(parent_task)
	# The DELEGATING agent's limit, never the worker's. delegation_deadline_minutes
	# sits beside max_recursion_depth, max_task_handoffs and max_delegation_retries
	# on the orchestrator's configuration, and it is enforced the same way: locally,
	# by the party that has to notice the work is not coming back. Reading it off
	# the target instead let a worker grant itself more time than the orchestrator
	# allowed — 1 minute configured on the orchestrator, 60 on the worker, and the
	# delegation ran to 60.
	#
	# A step may still override for a single delegation (the shape's
	# timeout_minutes), and 240 minutes is the backstop when nobody says.
	minutes = (
		frappe.utils.cint(deadline_minutes)
		or guardrails.deadline_minutes_for(delegating_agent)
		or DEFAULT_DEADLINE_MINUTES
	)
	# Always enforced, even with no delegating agent to attribute it to: the
	# target still has to be one that accepts agent-to-agent work.
	try:
		guardrails.enforce(
			delegating_agent, config.name, counters, required_capability=required_capability
		)
	except guardrails.DelegationRefused as refusal:
		# A limit breach leaves a failed task and tells a person (WI-002008);
		# an off-the-list target is a configuration mistake that never became
		# work, so it just refuses.
		breach = guardrails.record_limit_breach(
			refusal,
			delegating_agent=delegating_agent,
			target=config.name,
			instance=caller_instance,
			caller_wf_task_id=caller_wf_task_id,
			bpmn_id=bpmn_id,
			counters=counters,
		)
		if breach:
			guardrails.notify_refusal(
				refusal,
				delegating_agent=delegating_agent,
				instance=caller_instance,
				a2a_task=breach,
			)
		# WI-002053: and say which limit, and what it reached. The notify above
		# tells a person; this is what is still there afterwards.
		delegation.record_refusal(
			refusal,
			delegating_agent=delegating_agent,
			target=config.name,
			a2a_task=breach,
			counters=counters,
			instance=caller_instance,
		)
		raise

	task = frappe.get_doc(
		{
			"doctype": "A2A Task",
			"direction": "Internal",
			"state": "submitted",
			"agent_configuration": config.name,
			"delegated_by": delegating_agent or None,
			# The caller is recorded separately: running the agent sets
			# `instance` to the instance DOING the work, and a resume has to
			# target the step that is WAITING, which is a different process.
			"caller_instance": caller_instance,
			"caller_wf_task_id": caller_wf_task_id,
			"bpmn_id": bpmn_id,
			"request_payload": frappe.as_json({"instruction": instruction}),
			"task_execution_id": counters.get("task_execution_id"),
			"delegation_depth": counters.get("delegation_depth"),
			"handoff_count": counters.get("handoff_count"),
			"input_assignee": input_assignee,
			"input_role": input_role,
			"deadline": frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=minutes),
		}
	)
	task.flags.ignore_links = True
	task.insert(ignore_permissions=True)

	# Recorded before the worker runs, not after: a delegation whose worker
	# fails or hangs is exactly the one someone needs to be able to find.
	delegation.record(task, delegating_agent=delegating_agent, instruction=instruction)

	execute.run_for_task(task, config, instruction)
	task.reload()
	return task


def refresh(task) -> None:
	"""Bring an Internal task up to date from the run or instance doing the
	work. This is what the poller calls instead of a network round trip."""
	from one_bpmn.agents.a2a import task_store

	task_store.refresh_state(task)


def parent_task_for(instance) -> str | None:
	"""The delegation this instance is already part of, if any.

	Nobody should have to type this in the modeler: an instance that is doing
	delegated work is linked from the A2A Task that handed it that work, so
	the chain can be followed from where we already are. Getting it wrong the
	other way — a blank field on a nested step — would silently restart the
	depth count and defeat the loop guards.
	"""
	name = getattr(instance, "name", None)
	if not name:
		return None
	rows = frappe.get_all(
		"A2A Task", filters={"instance": name}, order_by="creation desc", limit=1, pluck="name"
	)
	if rows:
		return rows[0]
	# Background agents run with the task row itself as their context document.
	if getattr(instance, "context_doctype", None) == "A2A Task":
		return getattr(instance, "context_docname", None)
	return None
