# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The a2a connector's delegate-task operation (WI-001933).

One generic ``a2a`` connector serves every remote agent; which one is a
parameter, resolved through the registry. A Service Task using it hires
an external specialist exactly like any other integration.

Waiting is the interesting part. The connector framework is synchronous,
so a remote that answers immediately returns inline and nothing parks.
Anything slower parks the Service Task with its own marker — distinct
from the AI waiting-for-human marker, which means "a person must act"
and is bound to AI Agent Run checkpoints — and the poller resumes it
later.

Every delegation passes the guardrails first: the target must be on the
delegating agent's sub-agent list (WI-002010), and the chain's depth and
handoff count must be within that agent's limits (WI-002008).
"""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, cint, now_datetime

from one_bpmn.agents.shape_tools import PAUSE_HELD_FLAG as _PAUSE_HELD_FLAG
from one_bpmn.agents.a2a import guardrails, local, push
from one_bpmn.one_bpmn.integrations import a2a_client

A2A_WAITING_KEY = "_bpmn_a2a_waiting"


def local_agent_choices() -> list[str]:
	"""Dropdown source for same-site delegation — every live agent, with no
	registry entry and no exposure needed."""
	return local.local_agent_choices()


def delegate_to_local_agent(params: dict, ctx: dict) -> dict | None:
	"""Hand a task to an agent on THIS site (WI-001933, the primary case).

	No registry, no approved client, no HTTP: the target agent runs here.
	The delegating agent's allowed-delegates list and its guardrails still
	apply, because those are about scope and loops rather than
	authentication.

	Returns a result dict when the agent answered inside the call, or None
	after parking the Service Task for the poller to reconcile.
	"""
	instance = ctx.get("instance")
	task = ctx.get("task")
	instruction = (params.get("instruction") or "").strip()
	if not instruction:
		raise a2a_client.A2AClientError("delegate_to_local_agent needs an instruction to send.")

	target = params.get("agent") or params.get("remote_agent")
	if not target:
		raise a2a_client.A2AClientError("delegate_to_local_agent needs an agent to hand work to.")

	# ── Refuse to start work this turn cannot collect ────────────────────────
	# The agent loop tracks ONE pause per turn (step_loop: the first
	# ToolDeferred takes the slot). A model that calls several delegation tools
	# in a single assistant turn used to get one tracked delegation and the rest
	# ABANDONED MID-FLIGHT: local.delegate() creates the A2A Task and starts the
	# agent before anything parks, so the extra rows were live, unwatched, and
	# non-terminal until their deadline expired. The model was then told to call
	# again, so every specialist past the first also ran twice.
	#
	# Observed with four specialists on one brief: three delegations in one turn
	# produced five A2A Tasks — one tracked, two orphaned in "working" forever,
	# two duplicates from the retry.
	#
	# So the check belongs HERE, before the row exists, not in the loop after
	# the fact. Nothing is created, and the model is told plainly to come back
	# to it — which is the sequence that already works.
	if frappe.flags.get(_PAUSE_HELD_FLAG):
		return {
			"state": "not-started",
			"reason": "another-delegation-pending",
			"text": (
				f"Nothing was started for {target}. Another delegation from this turn is "
				"still waiting for its answer, and only one can be tracked at a time. "
				"Call this tool again once that one has come back."
			),
		}

	a2a_task = local.delegate(
		_delegating_agent(instance, params),
		target,
		instruction,
		parent_task=_parent_task(instance, params),
		caller_instance=getattr(instance, "name", None),
		caller_wf_task_id=_caller_task_id(task),
		bpmn_id=_bpmn_id(task),
		deadline_minutes=cint(params.get("timeout_minutes")) or None,
	)

	if a2a_task.state in ("completed", "failed", "canceled", "rejected"):
		# Answered inside the call: nothing parked, so nothing needs waking and
		# the reconciler must not later try.
		a2a_task.db_set("resume_enqueued", 1, update_modified=False)
		if a2a_task.state == "completed":
			payload = frappe.parse_json(a2a_task.result or "{}") or {}
			return {
				"a2a_task": a2a_task.name,
				"state": "completed",
				"text": payload.get("text") or a2a_task.status_message or "",
			}
		return {"a2a_task": a2a_task.name, "state": a2a_task.state, "error": a2a_task.error_message or ""}

	# Still working (or waiting on a person): park exactly as the remote path
	# does, so one resume seam serves both.
	if task is not None:
		task.data[A2A_WAITING_KEY] = {
			"a2a_task": a2a_task.name,
			"remote_task_id": None,
			"remote_agent": None,
			"label": f"Delegated to {a2a_task.agent_configuration}",
		}
	a2a_task.db_set(
		"next_poll_at", add_to_date(now_datetime(), seconds=15), update_modified=False
	)
	return None


def remote_agent_choices() -> list[str]:
	"""Dropdown source: only entries that could actually be delegated to."""
	return frappe.get_all(
		"A2A Remote Agent",
		filters={"enabled": 1, "approval_status": "Approved"},
		order_by="agent_name asc",
		pluck="name",
	)


def delegate_task(params: dict, ctx: dict) -> dict | None:
	"""Delegate one task to an approved remote agent.

	Returns a result dict when the remote answered inside the call, or
	None after parking the Service Task for the poller to resume.
	"""
	instance = ctx.get("instance")
	task = ctx.get("task")
	remote = a2a_client.require_approved(params.get("remote_agent"))
	instruction = (params.get("instruction") or "").strip()
	if not instruction:
		raise a2a_client.A2AClientError("delegate_task needs an instruction to send.")

	agent_configuration = _delegating_agent(instance, params)
	sub_agent = _local_agent_for(remote)
	counters = guardrails.next_counters(_parent_task(instance, params))

	# The gate. A refusal is a plain-language failure, not a crash: it
	# reaches whoever is watching the process.
	if agent_configuration:
		try:
			guardrails.enforce(agent_configuration, sub_agent, counters)
		except guardrails.DelegationRefused as refusal:
			breach = guardrails.record_limit_breach(
				refusal,
				delegating_agent=agent_configuration,
				target=sub_agent,
				instance=getattr(instance, "name", None),
				caller_wf_task_id=str(task.id) if task is not None else None,
				bpmn_id=_bpmn_id(task),
				counters=counters,
			)
			if breach:
				guardrails.notify_refusal(
					refusal,
					delegating_agent=agent_configuration,
					instance=getattr(instance, "name", None),
					a2a_task=breach,
				)
			raise

	a2a_task = _create_outbound_task(
		remote, instance, task, agent_configuration, instruction, counters, params
	)

	result = a2a_client.message_send(
		remote,
		instruction,
		context_id=a2a_task.context_id,
		metadata=guardrails.trace_metadata(counters),
	)
	state = a2a_client.remote_state(result) or "working"
	remote_task_id = result.get("id") if result.get("kind") != "message" else None
	if remote_task_id:
		a2a_task.db_set("remote_task_id", remote_task_id, update_modified=False)

	# Fast path: the remote finished inside the call. Nothing parks.
	if state == "completed":
		text = a2a_client.remote_text(result)
		a2a_task.db_set(
			{
				"state": "completed",
				"result": frappe.as_json({"text": text}),
				"status_message": text[:500],
				"completed_at": now_datetime(),
			},
			update_modified=True,
		)
		return {"a2a_task": a2a_task.name, "state": "completed", "text": text}

	if state in ("failed", "canceled", "rejected"):
		a2a_task.db_set(
			{"state": state, "error_message": a2a_client.remote_text(result)[:500]},
			update_modified=True,
		)
		return {"a2a_task": a2a_task.name, "state": state}

	# Slow path: park this Service Task. The poller owns it from here — and if
	# the remote can call us back instead, register that and let the poller
	# drop to a slow reconciliation (push complements polling, never replaces
	# it: a dropped callback must cost latency, not a hung process).
	a2a_task.db_set({"state": state}, update_modified=True)
	if push.register_with_remote(a2a_task, remote):
		a2a_task.db_set(
			"next_poll_at",
			add_to_date(now_datetime(), seconds=push.PUSH_RECONCILE_SECONDS),
			update_modified=False,
		)
	if task is not None:
		task.data[A2A_WAITING_KEY] = {
			"a2a_task": a2a_task.name,
			"remote_task_id": remote_task_id,
			"remote_agent": remote.name,
			"label": f"Delegated to {remote.card_name or remote.name}",
		}
	return None


def _create_outbound_task(remote, instance, task, agent_configuration, instruction, counters, params):
	deadline_minutes = cint(params.get("timeout_minutes")) or cint(
		remote.default_task_timeout_minutes
	) or 240
	doc = frappe.get_doc(
		{
			"doctype": "A2A Task",
			"direction": "Outbound",
			"state": "submitted",
			"remote_agent": remote.name,
			"agent_configuration": agent_configuration,
			"instance": getattr(instance, "name", None),
			"wf_task_id": str(task.id) if task is not None else None,
			"caller_instance": getattr(instance, "name", None),
			"caller_wf_task_id": str(task.id) if task is not None else None,
			"bpmn_id": _bpmn_id(task),
			"request_payload": frappe.as_json({"instruction": instruction}),
			"task_execution_id": counters.get("task_execution_id"),
			"delegation_depth": counters.get("delegation_depth"),
			"handoff_count": counters.get("handoff_count"),
			"input_assignee": params.get("input_assignee")
			or getattr(instance, "initiated_by", None),
			"input_role": params.get("input_role"),
			"deadline": add_to_date(now_datetime(), minutes=deadline_minutes),
			"next_poll_at": add_to_date(
				now_datetime(), seconds=cint(remote.poll_base_interval) or 60
			),
		}
	)
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)
	return doc


def _caller_task_id(task) -> str | None:
	"""The SpiffWorkflow id of the step to wake, or None when there is no step.

	A shape called as an agent's TOOL runs against a synthetic task that exists
	only for that call and has no id. Stringifying it wrote the literal "None"
	into the row, so the reconciler would later try to resume a step by that
	name. Such a delegation is woken through the agent's checkpoint instead —
	see ``_bind_a2a_wait``.
	"""
	task_id = getattr(task, "id", None) if task is not None else None
	return str(task_id) if task_id else None


def _parent_task(instance, params: dict) -> str | None:
	"""Which delegation this one continues. Derived, not typed: an instance
	already doing delegated work is linked from the task that handed it that
	work. A blank field here would restart the depth count on every nested
	step and quietly defeat the loop guards."""
	return params.get("parent_task") or local.parent_task_for(instance)


def _delegating_agent(instance, params: dict) -> str | None:
	"""Which local agent is doing the delegating — its configuration owns
	the allow-list and the limits."""
	if params.get("delegating_agent"):
		return params["delegating_agent"]
	agent_id = getattr(instance, "_a2a_delegating_agent", None)
	if agent_id:
		return agent_id
	# A chat/background instance running an agent's own map: the agent whose
	# process model this is.
	model = getattr(instance, "process_model", None)
	if model:
		return frappe.db.get_value("AI Agent Configuration", {"process_model": model}, "name")
	return None


def _local_agent_for(remote) -> str:
	"""The local AI Agent Configuration a remote entry corresponds to, when
	the remote is one of our own agents (the loopback case). Falls back to
	the registry name so the allow-list check still has something to match."""
	card = frappe.parse_json(remote.agent_card or "{}") or {}
	skills = card.get("skills") or []
	agent_id = skills[0].get("id") if skills else None
	if agent_id:
		local = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name")
		if local:
			return local
	return remote.name


def _bpmn_id(task) -> str | None:
	if task is None:
		return None
	spec = getattr(task, "task_spec", None)
	return getattr(spec, "bpmn_id", None) or getattr(spec, "name", None)
