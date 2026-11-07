# Copyright (c) 2026, one-fm and contributors
"""Tasks parked on a remote: an A2A delegation or an Agent Sandbox Run, their results and the remote's questions."""

import frappe
from frappe import _
from frappe.utils import now_datetime

from one_bpmn.processa_engine.assignment import (
	add_frappe_assignment,
	split_users,
)
from one_bpmn.processa_engine.runtime.active_tasks import close_human_row
from one_bpmn.processa_engine.runtime.ai_jobs import enqueue_wait_resume
from one_bpmn.processa_engine.runtime.common import A2A_HUMAN_PREFIX, log_task, task_bpmn_id

A2A_TERMINAL_STATES = ("completed", "failed", "canceled", "rejected", "timed-out")


def bind_a2a_wait(instance, task, marker: dict) -> None:
	"""Link a suspended agent's run and step to the A2A Task it delegated, so the reconciler can wake it."""
	a2a_task = marker.get("a2a_task")
	run_name = marker.get("run") or ""
	if not a2a_task:
		return
	try:
		frappe.db.set_value(
			"A2A Task",
			a2a_task,
			{
				# agent_run is the run doing the work and derives the task's state; the waiting caller goes here.
				"caller_agent_run": run_name or None,
				"caller_instance": instance.name,
				# Not caller_wf_task_id, which resumes a parked Service Task directly; this agent resumes by checkpoint.
				"wf_task_id": str(getattr(task, "id", "") or ""),
				"resume_enqueued": 0,
			},
			update_modified=False,
		)
	except Exception:
		frappe.log_error(
			title=f"A2A: could not bind the delegation to its waiting agent ({a2a_task})",
			message=frappe.get_traceback(),
		)
	# Not waiting_for_human: no person is being asked, and that field drives the human task banner.
	log_task(
		instance,
		task_id=f"a2await::{a2a_task}",
		task_name=marker.get("label") or marker.get("tool") or "",
		action="Started",
		data={
			"source": "ai_agent_a2a_tool",
			"agent_bpmn_id": task_bpmn_id(task),
			"a2a_task": a2a_task,
			"arguments": marker.get("arguments") or {},
		},
	)


def bind_agent_sandbox_wait(instance, task, marker: dict) -> None:
	"""Link a suspended agent's run and step to the Agent Sandbox Run it started, so the callback can wake it.

	agent_callback reads caller_agent_run before caller_wf_task_id, so here the latter holds this task's own id.
	"""
	run_name = marker.get("agent_sandbox_run")
	agent_run_name = marker.get("run") or ""
	if not run_name:
		return
	try:
		frappe.db.set_value(
			"Agent Sandbox Run",
			run_name,
			{
				"caller_agent_run": agent_run_name or None,
				"caller_instance": instance.name,
				"caller_wf_task_id": str(getattr(task, "id", "") or ""),
			},
			update_modified=False,
		)
	except Exception:
		frappe.log_error(
			title=f"Dev Agent Sandbox: could not bind the run to its waiting agent ({run_name})",
			message=frappe.get_traceback(),
		)
	log_task(
		instance,
		task_id=f"devagentwait::{run_name}",
		task_name=marker.get("label") or marker.get("tool") or "",
		action="Started",
		data={
			"source": "ai_agent_agent_sandbox_tool",
			"agent_bpmn_id": task_bpmn_id(task),
			"agent_sandbox_run": run_name,
			"arguments": marker.get("arguments") or {},
		},
	)


def apply_a2a_result(instance, task, marker: dict) -> bool:
	"""Apply a finished delegation to its parked Service Task. False while it still runs; raises on failOnError."""
	from one_bpmn.one_bpmn.connectors.a2a_client_ops import A2A_WAITING_KEY
	from one_bpmn.one_bpmn.integrations.a2a_client import A2ARemoteError

	a2a_task_name = marker.get("a2a_task")
	row = (
		frappe.db.get_value(
			"A2A Task", a2a_task_name, ["state", "result", "error_message", "bpmn_id"], as_dict=True
		)
		if a2a_task_name
		else None
	)
	if not row or row.state not in A2A_TERMINAL_STATES:
		return False

	result_var, fail_on_error = _result_config(instance, task)
	task.data.pop(A2A_WAITING_KEY, None)

	if row.state == "completed":
		if result_var:
			task.data[result_var] = frappe.parse_json(row.result or "{}") or {}
		return True

	if fail_on_error:
		raise A2ARemoteError(row.state, row.error_message or f"delegated task {row.state}")
	if result_var:
		task.data[result_var] = {"a2a_state": row.state, "a2a_error": row.error_message or ""}
	return True


def apply_agent_sandbox_result(instance, task, marker: dict) -> bool:
	"""Apply a finished Agent Sandbox Run to its parked Service Task. False while it still runs; raises on failOnError."""
	from one_bpmn.one_bpmn.connectors.agent_sandbox_ops import AGENT_SANDBOX_WAITING_KEY

	run_name = marker.get("run")
	row = (
		frappe.db.get_value(
			"Agent Sandbox Run", run_name, ["state", "pr_url", "error_message", "bpmn_id"], as_dict=True
		)
		if run_name
		else None
	)
	if not row or row.state not in ("completed", "failed"):
		return False

	result_var, fail_on_error = _result_config(instance, task)
	task.data.pop(AGENT_SANDBOX_WAITING_KEY, None)

	if row.state == "completed":
		if result_var:
			task.data[result_var] = {"pr_url": row.pr_url or ""}
		return True

	if fail_on_error:
		raise frappe.ValidationError(row.error_message or "dev agent sandbox run failed")
	if result_var:
		task.data[result_var] = {"dev_agent_state": row.state, "dev_agent_error": row.error_message or ""}
	return True


def _result_config(instance, task) -> tuple:
	"""The task's resultVariable and whether its failOnError is set."""
	task_cfg = getattr(instance, "_service_task_extensions", {}).get(task_bpmn_id(task)) or {}
	fail_on_error = str(task_cfg.get("failOnError") or "").lower() in ("1", "true", "yes")
	return task_cfg.get("resultVariable"), fail_on_error


def on_a2a_input_required(instance, a2a_task_name: str, prompt: str) -> None:
	"""The remote agent asked a question: open a human task on this instance to answer it."""
	row_data = frappe.db.get_value(
		"A2A Task",
		a2a_task_name,
		["input_assignee", "input_role", "remote_agent", "instance"],
		as_dict=True,
	)
	if not row_data:
		return
	label = f"Answer {row_data.remote_agent}: {(prompt or '').strip()[:80]}"
	row_id = f"{A2A_HUMAN_PREFIX}{frappe.generate_hash(length=10)}"
	assigned_user = row_data.input_assignee or instance.initiated_by or ""

	instance.append(
		"active_tasks",
		{
			"task_id": row_id,
			"task_name": label,
			"task_type": "A2A Human Task",
			"status": "Waiting",
			"started_at": now_datetime(),
			"assigned_user": assigned_user,
			"assigned_role": row_data.input_role or "",
			"target_doctype": instance.context_doctype,
			"target_docname": instance.context_docname,
		},
	)
	for user in split_users(assigned_user):
		try:
			add_frappe_assignment(instance, user, label)
		except Exception:
			frappe.log_error(
				title=f"A2A HITL: assignment creation failed ({a2a_task_name})",
				message=frappe.get_traceback(),
			)
	log_task(
		instance,
		task_id=row_id,
		task_name=label,
		action="Started",
		data={"source": "a2a_input_required", "a2a_task": a2a_task_name},
	)
	frappe.db.set_value("A2A Task", a2a_task_name, "pending_human_task", row_id, update_modified=False)
	instance.waiting_for_human = label
	instance.modified = frappe.utils.now()
	instance.db_update()
	instance.update_children()


def complete_a2a_human_task(instance, task_id: str, data: dict | None = None) -> None:
	"""Send a person's answer back to the remote agent that asked. The caller has checked assignment and permissions."""
	from one_bpmn.one_bpmn.integrations import a2a_client

	data = data or {}
	row = next((r for r in instance.active_tasks if r.task_id == task_id), None)
	if row is None or row.status != "Waiting":
		frappe.throw(_("Task '{0}' is not waiting for completion.").format(task_id))

	a2a_task_name = frappe.db.get_value(
		"A2A Task", {"pending_human_task": task_id, "state": "input-required"}, "name"
	)
	if not a2a_task_name:
		frappe.throw(_("No delegated task is waiting on '{0}'.").format(task_id))
	a2a_task = frappe.get_doc("A2A Task", a2a_task_name)

	answer = data.get("response") or data.get("answer") or ""
	close_human_row(instance, row, task_id, data)

	instance.waiting_for_human = ""
	instance.modified = frappe.utils.now()
	instance.modified_by = frappe.session.user
	instance.db_update()
	instance.update_children()

	try:
		result = a2a_client.message_send(
			a2a_task.remote_agent,
			answer,
			task_id=a2a_task.remote_task_id,
			context_id=a2a_task.context_id,
		)
	except Exception as exc:  # a dead remote fails the task
		a2a_task.db_set(
			{"state": "failed", "error_message": str(exc)[:500], "pending_human_task": ""},
			update_modified=True,
		)
		enqueue_wait_resume(instance.name, a2a_task.wf_task_id, a2a_task.name, "A2A Task")
		return

	state = a2a_client.remote_state(result) or "working"
	updates = {"pending_human_task": "", "state": state}
	if state == "completed":
		text = a2a_client.remote_text(result)
		updates.update(
			{
				"result": frappe.as_json({"text": text}),
				"status_message": text[:500],
				"completed_at": now_datetime(),
			}
		)
	a2a_task.db_set(updates, update_modified=True)

	if state in A2A_TERMINAL_STATES:
		enqueue_wait_resume(instance.name, a2a_task.wf_task_id, a2a_task.name, "A2A Task")
	else:
		# Back to waiting: reset the backoff so the next poll is prompt.
		remote = frappe.get_doc("A2A Remote Agent", a2a_task.remote_agent)
		a2a_task.db_set(
			{
				"poll_attempts": 0,
				"next_poll_at": frappe.utils.add_to_date(
					now_datetime(), seconds=frappe.utils.cint(remote.poll_base_interval) or 60
				),
			},
			update_modified=False,
		)
