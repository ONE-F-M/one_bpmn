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

from one_bpmn.agents.a2a import execute, guardrails

TARGET_FIELDS = ("name", "agent_id", "agent_name", "enabled", "lifecycle_status", "agent_type", "process_model")


def local_agent_choices() -> list[str]:
	"""Dropdown source: agents that can actually be handed work today.

	Deliberately NOT filtered by a2a_exposed — exposure is about who may
	call us from outside, and a local hand-off is not from outside.
	"""
	return frappe.get_all(
		"AI Agent Configuration",
		filters={"enabled": 1, "lifecycle_status": "Live"},
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
	return target


def delegate(
	delegating_agent: str,
	target: str,
	instruction: str,
	*,
	parent_task: str | None = None,
	instance: str | None = None,
	wf_task_id: str | None = None,
	bpmn_id: str | None = None,
	input_assignee: str | None = None,
	input_role: str | None = None,
	deadline=None,
):
	"""Hand a task to a local agent. Returns the A2A Task row.

	The guardrails run BEFORE anything is created, so a refused delegation
	leaves no trace of work that never started.
	"""
	config = resolve_target(target)
	counters = guardrails.next_counters(parent_task)
	if delegating_agent:
		guardrails.enforce(delegating_agent, config.name, counters)

	task = frappe.get_doc(
		{
			"doctype": "A2A Task",
			"direction": "Internal",
			"state": "submitted",
			"agent_configuration": config.name,
			"delegated_by": delegating_agent or None,
			"instance": instance,
			"wf_task_id": wf_task_id,
			"bpmn_id": bpmn_id,
			"request_payload": frappe.as_json({"instruction": instruction}),
			"task_execution_id": counters.get("task_execution_id"),
			"delegation_depth": counters.get("delegation_depth"),
			"handoff_count": counters.get("handoff_count"),
			"input_assignee": input_assignee,
			"input_role": input_role,
			"deadline": deadline,
		}
	)
	task.flags.ignore_links = True
	task.insert(ignore_permissions=True)

	execute.run_for_task(task, config, instruction)
	task.reload()
	return task


def refresh(task) -> None:
	"""Bring an Internal task up to date from the run or instance doing the
	work. This is what the poller calls instead of a network round trip."""
	from one_bpmn.agents.a2a import task_store

	task_store.refresh_state(task)
