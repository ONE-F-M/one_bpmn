# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A2A Task store — create, resolve, and derive state (WI-001932).

State mapping onto the existing machinery, never a parallel runtime:

- ``submitted``      row exists, nothing has answered yet
- ``working``        the agent's run / instance is busy
- ``input-required`` the run is Suspended waiting on the caller
- ``completed``      the turn (chat path) or instance (background path)
  finished; the reply is the result
- ``failed``         run or instance errored
- ``canceled``       tasks/cancel before work started

Terminal states are sticky — refresh never rewrites history.
"""

from __future__ import annotations

import json

import frappe

from one_bpmn.agents import a2a_contract
from one_bpmn.agents.a2a.protocol import A2AError
from one_bpmn.agents.checkpoint import get_suspended_run


def create_inbound_task(config, client_name: str, message: dict, text: str, trace: dict) -> "frappe.model.document.Document":
	task = frappe.get_doc(
		{
			"doctype": "A2A Task",
			"direction": "Inbound",
			"state": "submitted",
			"client": client_name,
			"agent_configuration": config.name,
			"context_id": message.get("contextId"),
			"request_payload": frappe.as_json({"text": text, "metadata": message.get("metadata") or {}}),
			"task_execution_id": trace.get("task_execution_id"),
			"delegation_depth": trace.get("delegation_depth") or 0,
			"handoff_count": trace.get("handoff_count") or 0,
		}
	)
	task.insert(ignore_permissions=True)
	return task


def get_task_for_principal(task_id: str):
	"""Resolve a wire task id for the CURRENT caller. A missing task and a
	foreign client's task are the same error — no existence leak. System
	Managers see everything (the admin surface)."""
	if not task_id:
		raise A2AError("INVALID_PARAMS", "task id is required")
	filters: dict = {"task_id": task_id}
	if "System Manager" not in frappe.get_roles():
		filters["principal"] = frappe.session.user
	name = frappe.db.get_value("A2A Task", filters, "name")
	if not name:
		raise A2AError("TASK_NOT_FOUND", f"no task '{task_id}' for this caller")
	return frappe.get_doc("A2A Task", name)


def refresh_state(task) -> None:
	"""Derive the current state from the linked run/instance. Terminal
	states are sticky; a worker map that wrote the row directly wins."""
	if task.state in a2a_contract.terminal_states():
		return

	if task.agent_run:
		_refresh_from_run(task)
	elif task.instance:
		_refresh_from_instance(task)


def _refresh_from_run(task) -> None:
	run = frappe.db.get_value(
		"AI Agent Run", task.agent_run, ["status", "pending_human_task"], as_dict=True
	)
	if not run:
		return
	if run.status == "Suspended":
		_set_state(task, "input-required", pending_human_task=run.pending_human_task)
	elif run.status == "Running":
		_set_state(task, "working")
	elif run.status == "Success":
		_set_state(task, "completed", status_message=_latest_bot_reply(task) or task.status_message)
	elif run.status == "Error":
		_set_state(task, "failed")


def _refresh_from_instance(task) -> None:
	"""Background path: the instance IS the task's execution."""
	status = frappe.db.get_value("BPMN Process Instance", task.instance, "status")
	if not status:
		return
	if status in ("Queued", "Active"):
		suspended = get_suspended_run(task.instance)
		if suspended:
			pending = frappe.db.get_value("AI Agent Run", suspended, "pending_human_task")
			_set_state(task, "input-required", agent_run=suspended, pending_human_task=pending)
		else:
			_set_state(task, "working")
	elif status == "Completed":
		_set_state(task, "completed")
	elif status in ("Errored", "Failed"):
		_set_state(task, "failed")
	elif status == "Cancelled":
		_set_state(task, "canceled")


def _set_state(task, state: str, **extra) -> None:
	changed = {"state": state}
	for field, value in extra.items():
		if value and task.get(field) != value:
			changed[field] = value
	if task.state == state:
		changed.pop("state")
	if not changed:
		return
	task.db_set(changed, update_modified=True)
	for field, value in changed.items():
		task.set(field, value)
	_notify(task)


def find_instance(conversation: str) -> str | None:
	"""The live instance answering a conversation — context correlation,
	same as the chat surface uses."""
	rows = frappe.get_all(
		"BPMN Process Instance",
		filters={
			"context_doctype": "Chat Conversation",
			"context_docname": conversation,
			"status": ("in", ("Queued", "Active")),
		},
		order_by="creation desc",
		limit=1,
		pluck="name",
	)
	return rows[0] if rows else None


def find_instance_for_task(task_name: str) -> str | None:
	"""Background path: the instance whose context doc IS the A2A Task."""
	rows = frappe.get_all(
		"BPMN Process Instance",
		filters={"context_doctype": "A2A Task", "context_docname": task_name},
		order_by="creation desc",
		limit=1,
		pluck="name",
	)
	return rows[0] if rows else None


def build_history(task, history_length: int | None) -> list | None:
	"""The last N turns as wire messages, chat path only."""
	if not history_length or not task.conversation:
		return None
	rows = frappe.get_all(
		"Chat Message",
		filters={"conversation": task.conversation, "message_type": ("in", ("User", "Bot"))},
		fields=["text", "message_type"],
		order_by="creation desc",
		limit=int(history_length),
	)
	history = []
	for row in reversed(rows):
		history.append(
			{
				"role": "user" if row.message_type == "User" else "agent",
				"parts": [{"kind": "text", "text": row.text or ""}],
				"kind": "message",
				"taskId": task.task_id,
			}
		)
	return history


def _latest_bot_reply(task) -> str | None:
	if not task.conversation:
		return None
	return frappe.db.get_value(
		"Chat Message",
		{"conversation": task.conversation, "message_type": "Bot"},
		"text",
		order_by="creation desc",
	)


def store_result(task, text: str) -> None:
	task.db_set(
		{
			"state": "completed",
			"status_message": (text or "")[:500],
			"result": frappe.as_json({"text": text or ""}),
			"artifacts": json.dumps(
				[
					{
						"artifactId": f"{task.task_id}-reply",
						"parts": [{"kind": "text", "text": text or ""}],
					}
				]
			),
			"completed_at": frappe.utils.now_datetime(),
		},
		update_modified=True,
	)
	task.reload()
	_notify(task)


def _notify(task) -> None:
	"""Tell an inbound caller their task moved, if they asked to be told.
	Best-effort: they can always poll, so this must never raise into the
	agent's work."""
	if task.direction != "Inbound":
		return
	try:
		from one_bpmn.agents.a2a.push import notify_caller

		notify_caller(task)
	except Exception:
		frappe.log_error(title="A2A push notify skipped", message=frappe.get_traceback())
