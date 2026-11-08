# Copyright (c) 2026, one-fm and contributors
"""The instance's active_tasks table, its completion check and the save every engine pass ends with."""

import json

import frappe
from frappe.utils import now_datetime

from one_bpmn.processa_engine import engine as bpmn_engine
from one_bpmn.processa_engine.assignment import (
	add_frappe_assignment,
	notify_task_assignee,
	remove_frappe_assignment,
	resolve_assignment,
	split_users,
)
from one_bpmn.processa_engine.engine import TaskState
from one_bpmn.processa_engine.instances.cancellation import settle_cancellation
from one_bpmn.processa_engine.runtime.common import AI_HUMAN_PREFIX, log_task, settle_goal_completion


def persist_workflow(instance, wf, prev_assigned) -> None:
	"""Store the workflow state, rebuild active_tasks, check completion and save the instance."""
	bpmn_engine.clean_doc_from_wf_data(wf)
	instance.workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))
	sync_call_activity_rows(instance, wf)
	sync_active_tasks(instance, wf, prev_assigned=prev_assigned)
	check_completion(instance, wf)
	save_without_version_check(instance)


def save_without_version_check(instance) -> None:
	"""Save the instance and its children without save()'s modified-timestamp check.

	A ToDo email sent mid-pass, or the realtime update this pass publishes, can bump modified first and
	save() would then raise TimestampMismatchError, which Frappe never writes to the Error Log.
	"""
	instance.modified = frappe.utils.now()
	instance.modified_by = frappe.session.user
	instance.db_update()
	instance.update_children()
	instance.run_method("on_update")


def get_active_tasks_summary(instance) -> list:
	"""The instance's waiting User Tasks as dicts, for API responses and the Processa frontend."""
	return [
		{
			"task_id": row.task_id,
			"task_name": row.task_name,
			"task_type": row.task_type,
			"status": row.status,
			"assigned_user": row.assigned_user,
			"assigned_role": row.assigned_role,
			"started_at": str(row.started_at) if row.started_at else None,
			"task_actions": resolve_task_actions(row),
			"task_actions_detail": resolve_task_actions_detail(row),
		}
		for row in instance.active_tasks
		if row.status == "Waiting"
	]


def resolve_task_actions(row) -> str:
	"""Comma-separated action labels of an active task row, for older frontends."""
	actions = parse_task_actions_json(getattr(row, "task_actions", "") or "")
	return ",".join(a.get("action", "") for a in actions if a.get("action"))


def resolve_task_actions_detail(row) -> list:
	"""The row's actions with their per-action flags such as confirmTransition and requireDigitalSignature."""
	return parse_task_actions_json(getattr(row, "task_actions", "") or "")


def parse_task_actions_json(raw: str) -> list:
	"""Parse task_actions from a JSON array or a legacy comma-separated list into dicts with an action key."""
	if not raw:
		return []
	trimmed = raw.strip()
	if trimmed.startswith("["):
		try:
			parsed = json.loads(trimmed)
			return parsed if isinstance(parsed, list) else []
		except (TypeError, ValueError):
			return []
	return [{"action": a.strip()} for a in trimmed.split(",") if a.strip()]


def close_human_row(instance, row, task_id: str, data: dict) -> None:
	"""Mark a Waiting human-task row Completed, log it and close the ToDos of users left with no Waiting row."""
	completed_at = now_datetime()
	prev_assigned = {
		u
		for r in instance.active_tasks
		if r.status == "Waiting" and r.assigned_user
		for u in split_users(r.assigned_user)
	}
	row.status = "Completed"
	row.end_time = completed_at
	if row.started_at:
		row.timer_duration = int(frappe.utils.time_diff_in_seconds(completed_at, row.started_at))
	log_task(instance, task_id=task_id, task_name=row.task_name, action="Completed", data=data)

	still_assigned = {
		u
		for r in instance.active_tasks
		if r.status == "Waiting" and r.assigned_user
		for u in split_users(r.assigned_user)
	}
	for user in prev_assigned - still_assigned:
		remove_frappe_assignment(instance, user, status="Closed")


def sync_call_activity_rows(instance, wf) -> None:
	"""Keep a visible Process Instance row for each Call Activity this run makes. Call after workflow_state is set."""
	from one_bpmn.processa_engine.call_activities import (
		sync_call_activity_instances,
	)

	sync_call_activity_instances(instance, wf)


def sync_active_tasks(instance, wf, prev_assigned=None):
	"""Rebuild active_tasks from the READY User Tasks and move ToDos by a before and after diff of assigned users.

	prev_assigned is the set of users with an Open assignment before this pass; None reads it from the Waiting rows.
	"""
	ready_user_tasks = bpmn_engine.get_ready_user_tasks(wf)
	new_ready_ids = {str(t.id) for t in ready_user_tasks}

	if prev_assigned is None:
		prev_assigned = set()
		for row in instance.active_tasks:
			if row.status == "Waiting" and row.assigned_user:
				prev_assigned.update(split_users(row.assigned_user))

	# A Waiting AI human-task row belongs to a suspended agent and has no engine task, so it survives the rebuild.
	instance.active_tasks = [
		row
		for row in instance.active_tasks
		if row.status == "Completed"
		or row.task_id in new_ready_ids
		or (row.status == "Waiting" and str(row.task_id).startswith(AI_HUMAN_PREFIX))
	]

	existing_waiting_ids = {row.task_id for row in instance.active_tasks if row.status == "Waiting"}
	newly_opened = []
	for task in ready_user_tasks:
		tid = str(task.id)
		if tid in existing_waiting_ids:
			continue
		newly_opened.extend(_append_user_task_row(instance, task, tid))

	curr_assigned = {}
	for row in instance.active_tasks:
		if row.status == "Waiting" and row.assigned_user:
			for u in split_users(row.assigned_user):
				curr_assigned[u] = {
					"task_name": row.task_name,
					"bpmn_id": getattr(row, "_bpmn_id", ""),
					"task_id": row.task_id,
				}

	todo_close_status = _todo_close_status(wf, ready_user_tasks)
	for user in prev_assigned - set(curr_assigned.keys()):
		remove_frappe_assignment(instance, user, status=todo_close_status)

	for user, info in curr_assigned.items():
		if user not in prev_assigned:
			add_frappe_assignment(instance, user, info["task_name"])

	# Every task that opened notifies its users, including those who already held a ToDo from the previous task.
	for user, task_name, task_cfg, task_id, bpmn_id in newly_opened:
		notify_task_assignee(instance, user, task_name, task_cfg, task_id=task_id, bpmn_id=bpmn_id)


def _append_user_task_row(instance, task, tid: str) -> list:
	"""Add a Waiting row for a newly READY user task; returns its (user, name, config, id, bpmn_id) notifications."""
	task_name = bpmn_engine.get_task_display_name(task)
	task_type = bpmn_engine.get_task_type_label(task)

	assigned_user = task.data.get("assigned_user") or ""
	assigned_role = task.data.get("assigned_role") or ""

	async_user = resolve_assignment(instance, task)
	relief_pairs = getattr(instance, "_relief_pairs", []) if async_user else []
	if async_user:
		assigned_user = async_user

	bpmn_id_key = getattr(task.task_spec, "bpmn_id", None) or ""
	task_cfg = getattr(instance, "_user_task_extensions", {}).get(bpmn_id_key, {})

	instance.append(
		"active_tasks",
		{
			"task_id": tid,
			"task_name": task_name,
			"task_type": task_type,
			"status": "Waiting",
			"started_at": now_datetime(),
			"assigned_user": assigned_user,
			"relieved_user": ",".join(p[0] for p in relief_pairs),
			"reliever_user": ",".join(p[1] for p in relief_pairs),
			"assigned_role": assigned_role,
			"task_actions": task_cfg.get("taskActions", ""),
			"target_doctype": instance.context_doctype,
			"target_docname": instance.context_docname,
		},
	)
	# Transient, not persisted: add_frappe_assignment reads the user task config through it.
	instance.active_tasks[-1]._bpmn_id = bpmn_id_key

	log_task(instance, task_id=tid, task_name=task_name, action="Started")
	return [(u, task_name, task_cfg, tid, bpmn_id_key) for u in split_users(assigned_user)]


def _todo_close_status(wf, ready_user_tasks) -> str:
	"""The status closed ToDos get: a todo_close_status hint a script task left on the data, else Closed.

	The workflow root's data never sees script task writes, so the hint is read off the next ready task or the last task.
	"""
	for t in ready_user_tasks:
		hint = t.data.get("todo_close_status")
		if hint:
			return hint
	last_task = getattr(wf, "last_task", None)
	if last_task is not None:
		return last_task.data.get("todo_close_status") or "Closed"
	return "Closed"


def check_completion(instance, wf):
	"""Mark the instance Completed when nothing is READY, WAITING or STARTED any more."""
	if wf.is_completed() or (
		not wf.get_tasks(state=TaskState.READY)
		and not wf.get_tasks(state=TaskState.WAITING)
		and not wf.get_tasks(state=TaskState.STARTED)
	):
		instance.status = "Completed"
		instance.completed_at = now_datetime()
		settle_goal_completion(instance, "Completed")
		settle_cancellation(instance, wf)
