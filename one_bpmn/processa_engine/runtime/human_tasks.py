# Copyright (c) 2026, one-fm and contributors
"""An AI agent suspended for a human tool: spawn the person's task, then hand the answer back to the agent."""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from one_bpmn.processa_engine.agent_runtime.job_limits import AI_AGENT_JOB_TIMEOUT
from one_bpmn.processa_engine.assignment import (
	add_frappe_assignment,
	notify_task_assignee,
	resolve_assignment,
	split_users,
)
from one_bpmn.processa_engine.runtime.active_tasks import close_human_row
from one_bpmn.processa_engine.runtime.ai_jobs import RUN_PARKED_AI_TASK, ai_job_queue
from one_bpmn.processa_engine.runtime.common import (
	AI_HUMAN_PREFIX,
	AI_WAITING_HUMAN_KEY,
	load_json,
	log_task,
	refresh_user_task_extensions_from_model,
	task_bpmn_id,
	waiting_marker,
)
from one_bpmn.processa_engine.runtime.remote_waits import bind_a2a_wait, bind_agent_sandbox_wait


def on_ai_agent_suspended(instance, task):
	"""Open the human tool's task for the suspended agent and bind it to the run's checkpoint.

	The service task stays STARTED with its marker. A pause on another agent or on the sandbox binds that wait instead.
	"""
	marker = waiting_marker(task, AI_WAITING_HUMAN_KEY) or {}
	shape_id = marker.get("tool") or ""
	run_name = marker.get("run") or ""
	arguments = marker.get("arguments") or {}

	if marker.get("waits_on") == "a2a":
		bind_a2a_wait(instance, task, marker)
		return
	if marker.get("waits_on") == "agent_sandbox":
		bind_agent_sandbox_wait(instance, task, marker)
		return

	if not hasattr(instance, "_user_task_extensions"):
		spec_snap = load_json(instance.serialized_spec or "{}") or {}
		instance._user_task_extensions = spec_snap.get("user_task_extensions", {})
	refresh_user_task_extensions_from_model(instance)
	shape_cfg = getattr(instance, "_user_task_extensions", {}).get(shape_id, {}) or {}
	# The shape's drawn name: its id is never shown to a person.
	label = (
		marker.get("label")
		or shape_cfg.get("label")
		or human_tool_label(instance, task, shape_id)
		or shape_id
	)

	row_id = f"{AI_HUMAN_PREFIX}{frappe.generate_hash(length=10)}"
	assigned_user = _assign_human_tool(instance, shape_id, label, arguments)

	instance.append(
		"active_tasks",
		{
			"task_id": row_id,
			"task_name": label,
			"task_type": "AI Human Task",
			"status": "Waiting",
			"started_at": now_datetime(),
			"assigned_user": assigned_user,
			"assigned_role": shape_cfg.get("assigneeRole", "") or "",
			"task_actions": shape_cfg.get("taskActions", "") or "",
			"target_doctype": instance.context_doctype,
			"target_docname": instance.context_docname,
		},
	)

	for u in split_users(assigned_user):
		try:
			add_frappe_assignment(instance, u, label)
		except Exception:
			frappe.log_error(
				title=f"AI HITL: assignment creation failed ({shape_id})",
				message=frappe.get_traceback(),
			)
		# This row is built here, not by sync_active_tasks, so it asks for its own notification.
		notify_task_assignee(instance, u, label, shape_cfg, task_id=row_id, bpmn_id=shape_id)

	log_task(
		instance,
		task_id=row_id,
		task_name=label,
		action="Started",
		data={"source": "ai_agent_human_tool", "agent_bpmn_id": task_bpmn_id(task), "arguments": arguments},
	)

	marker["row_id"] = row_id
	marker["label"] = label
	task.data[AI_WAITING_HUMAN_KEY] = marker
	if run_name:
		_bind_checkpoint(run_name, row_id)
	instance.waiting_for_human = label

	from one_bpmn.ai_agent_conversations import clarification

	# The agent named on the record is the one whose limits apply: read off the AI task that suspended.
	ai_cfg = (getattr(instance, "_service_task_extensions", {}) or {}).get(task_bpmn_id(task)) or {}
	clarification.record_question(
		instance=instance,
		human_task_id=row_id,
		agent_configuration=ai_cfg.get("aiAgentConfig"),
		agent_run=run_name,
		arguments=arguments,
		label=label,
		assigned_user=assigned_user,
	)


def _assign_human_tool(instance, shape_id: str, label: str, arguments: dict) -> str:
	"""Resolve the human tool's assignee the way a real user task is resolved; '' when that fails."""
	synthetic = frappe._dict(
		data=dict(arguments),
		task_spec=frappe._dict(bpmn_id=shape_id, name=shape_id, description=label),
		workflow=frappe._dict(data={}),
	)
	try:
		return resolve_assignment(instance, synthetic) or ""
	except Exception:
		frappe.log_error(
			title=f"AI HITL: assignment resolution failed ({shape_id})",
			message=frappe.get_traceback(),
		)
		return ""


def _bind_checkpoint(run_name: str, row_id: str) -> None:
	"""Point the suspended AI Agent Run and its checkpoint at the human task row."""
	try:
		frappe.db.set_value("AI Agent Run", run_name, "pending_human_task", row_id, update_modified=False)
		run_doc = frappe.get_doc("AI Agent Run", run_name)
		payload = json.loads(run_doc.checkpoint or "{}")
		payload["human_row_id"] = row_id
		run_doc.db_set("checkpoint", json.dumps(payload, default=str), update_modified=False)
	except Exception:
		frappe.log_error(
			title=f"AI HITL: checkpoint binding failed ({run_name})",
			message=frappe.get_traceback(),
		)


def human_tool_label(instance, task, shape_id: str) -> str:
	"""The name drawn on a human tool shape, from the aiToolShapes compile_process_model recorded on the AI task."""
	try:
		cfg = (getattr(instance, "_service_task_extensions", {}) or {}).get(task_bpmn_id(task)) or {}
		shapes = cfg.get("aiToolShapes") or "[]"
		if isinstance(shapes, str):
			shapes = json.loads(shapes)
		for shape in shapes:
			if isinstance(shape, dict) and shape.get("bpmn_id") == shape_id:
				return (shape.get("label") or "").strip()
	except Exception:
		pass
	return ""


def complete_ai_human_task(instance, task_id: str, data: dict | None = None) -> None:
	"""Complete a pending AI human task and resume the suspended agent in a bpmn_ai_agent job.

	The caller, task_actions.complete_task, has checked assignment, action and document permissions.
	"""
	data = data or {}
	row = next((r for r in instance.active_tasks if r.task_id == task_id), None)
	if row is None or row.status != "Waiting":
		frappe.throw(_("Task '{0}' is not waiting for completion.").format(task_id))

	from one_bpmn.processa_engine.agent_runtime import checkpoint as _checkpoint

	run_name = _checkpoint.get_suspended_run(instance.name, human_row_id=task_id)
	if not run_name:
		frappe.throw(
			_("No suspended AI agent is waiting on task '{0}' - it may have been resumed already.").format(
				row.task_name or task_id
			)
		)

	close_human_row(instance, row, task_id, data)

	from one_bpmn.ai_agent_conversations import clarification

	# The answer is recorded before the agent sees it, whatever the agent then does with it.
	clarification.record_answer(instance=instance, human_task_id=task_id, data=data)
	_checkpoint.store_human_result(run_name, data)

	instance.waiting_for_human = ""
	instance.modified = frappe.utils.now()
	instance.modified_by = frappe.session.user
	instance.db_update()
	instance.update_children()

	payload = json.loads(frappe.db.get_value("AI Agent Run", run_name, "checkpoint") or "{}")
	frappe.enqueue(
		RUN_PARKED_AI_TASK,
		queue=ai_job_queue(instance.process_model),
		timeout=AI_AGENT_JOB_TIMEOUT,
		enqueue_after_commit=True,
		job_id=f"bpmn-ai-{instance.name}-hr-{task_id}",
		deduplicate=True,
		instance_name=instance.name,
		kind="human_resume",
		task_id=payload.get("wf_task_id") or "",
		run_as_user=frappe.session.user,
	)
