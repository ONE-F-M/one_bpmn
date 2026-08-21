# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Running an agent for an A2A task — the one implementation (WI-001933).

Both doors use this: a task that arrived over the network (api/a2a_api)
and a task handed straight from one local agent to another
(agents/a2a/local). Same execution, same state mapping, same screening —
the difference between the two is only how the request got here and who
had to be authorised, never what the agent then does.

Two agent shapes, matching how agents are built in this codebase:

- **Chat** — the standard invocation entry point owns the turn, so the
  whole screening chain, conversation persistence and suspend/resume come
  along unchanged.
- **Background** — no conversation at all: the A2A Task row IS the trigger
  document, and the agent's own A2A-startable map runs against it.
"""

from __future__ import annotations

import frappe

from one_bpmn.agents.a2a import task_store


def run_for_task(task, config, text: str) -> None:
	"""Execute the agent named by ``config`` for this task, writing the
	outcome onto the task row. Never raises: a failure is a failed task,
	not a broken caller."""
	agent_type = config.get("agent_type") if isinstance(config, dict) else config.agent_type
	if agent_type == "Background":
		run_background(task, config, text)
	else:
		run_chat_turn(task, config, text)


def run_chat_turn(task, config, text: str) -> None:
	"""Chat path: the whole existing turn machinery, screening included,
	via the standard invocation entry point."""
	from one_bpmn.api.agent_invocation import invoke_agent
	from one_bpmn.security.rate_limit import RateLimited

	agent_id = config["agent_id"] if isinstance(config, dict) else config.agent_id
	try:
		result = invoke_agent(agent_id, text)
	except RateLimited as refusal:
		task.db_set({"state": "rejected", "error_message": str(refusal)[:500]}, update_modified=True)
		task.reload()
		return
	except Exception:
		frappe.log_error(title="A2A turn failed", message=frappe.get_traceback())
		task.db_set(
			{"state": "failed", "error_message": "the agent's turn failed"}, update_modified=True
		)
		task.reload()
		return

	conversation = result.get("conversation")
	updates = {"conversation": conversation}
	instance = task_store.find_instance(conversation) if conversation else None
	if instance:
		updates["instance"] = instance
	task.db_set(updates, update_modified=False)
	task.reload()

	suspended = None
	if instance:
		from one_bpmn.agents.checkpoint import get_suspended_run

		suspended = get_suspended_run(instance)
	if suspended:
		pending = frappe.db.get_value("AI Agent Run", suspended, "pending_human_task")
		task.db_set(
			{
				"state": "input-required",
				"agent_run": suspended,
				"pending_human_task": pending,
				"status_message": (result.get("response") or "")[:500],
			},
			update_modified=True,
		)
		task.reload()
		from one_bpmn.agents.a2a import delegation

		delegation.sync_from_task(task)
	else:
		task_store.store_result(task, result.get("response") or "")


def run_background(task, config, text: str) -> None:
	"""Background path: the A2A Task row is the trigger document, so an
	A2A-startable map has already started on insert; bind the instance."""
	from one_bpmn.agents.agent_provisioning import is_a2a_startable_map

	process_model = config.get("process_model") if isinstance(config, dict) else config.process_model
	if not is_a2a_startable_map(process_model):
		task.db_set(
			{
				"state": "rejected",
				"error_message": "this agent has no process map that an A2A task can start",
			},
			update_modified=True,
		)
		task.reload()
		return

	instance = task_store.find_instance_for_task(task.name)
	if not instance:
		# The insert may have happened before a map whose start condition needs
		# the agent could match — re-fire the same conditional gate the
		# universal trigger uses.
		try:
			from one_bpmn.one_bpmn.trigger import _maybe_start_instance

			_maybe_start_instance(frappe.get_doc("A2A Task", task.name), process_model)
			instance = task_store.find_instance_for_task(task.name)
		except Exception:
			frappe.log_error(title="A2A background start failed", message=frappe.get_traceback())

	if not instance:
		task.db_set(
			{"state": "failed", "error_message": "no process started for this task"},
			update_modified=True,
		)
		task.reload()
		return
	task.db_set({"instance": instance, "state": "working"}, update_modified=True)
	# WI-002053: the worker's instance records who started it, so the chain can
	# be walked downwards as well as up. Only the A2A path sets this — a Call
	# Activity runs the called process INSIDE its caller's instance, so there is
	# no separate row for it to point back from.
	if task.caller_instance:
		frappe.db.set_value(
			"BPMN Process Instance", instance, "parent_instance", task.caller_instance,
			update_modified=False,
		)
	task.reload()
	# This state change is written straight to the row rather than through
	# task_store._set_state, so the delegation record has to be told here or it
	# sits on "Delegated" for the whole run and In Progress never happens.
	from one_bpmn.agents.a2a import delegation

	delegation.sync_from_task(task)
	# A short map can finish inside the same request. Reading the instance now
	# means such a worker answers inline instead of parking the caller for a
	# reconciler tick it does not need.
	task_store.refresh_state(task)
	task.reload()
