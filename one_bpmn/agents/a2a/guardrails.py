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


def may_delegate_to(agent_configuration: str, sub_agent: str) -> bool:
	"""Is this sub-agent on the delegating agent's list? (WI-002010)"""
	if not (agent_configuration and sub_agent):
		return False
	return bool(
		frappe.db.exists(
			"AI Agent Allowed Delegate",
			{
				"parent": agent_configuration,
				"parenttype": "AI Agent Configuration",
				"agent_configuration": sub_agent,
			},
		)
	)


def check_allowed(agent_configuration: str, sub_agent: str) -> None:
	if not may_delegate_to(agent_configuration, sub_agent):
		raise DelegationRefused(
			_("This agent is not allowed to delegate to '{0}'.").format(sub_agent),
			reason_code="sub_agent_not_allowed",
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
