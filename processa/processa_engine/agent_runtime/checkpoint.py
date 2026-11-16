# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Persist a suspended AI Agent Run and claim it for resume."""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime


def save_checkpoint(
	run,
	instance,
	bpmn_id: str,
	suspension: dict,
	*,
	system_prompt: str,
	wf_task_id: str,
	human_row_id: str,
	steps_recorded: int = 0,
	pending_step: str = "",
):
	"""Persist a suspension on its AI Agent Run (status="Suspended")."""
	if run is None or getattr(run, "stub", False):
		run = frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"instance": instance.name,
				"process_model": instance.process_model or "",
				"bpmn_id": bpmn_id,
				"element_type": "task",
				"status": "Running",
				"started_at": now_datetime(),
			}
		).insert(ignore_permissions=True)  # engine bookkeeping row written during the run, not a user action

	payload = {
		"suspension": suspension,
		"system_prompt": system_prompt,
		"wf_task_id": wf_task_id,
		"human_row_id": human_row_id,
		"pending_result": None,
		"steps_recorded": steps_recorded,
		"pending_step": pending_step,
	}
	run.db_set(
		{
			"status": "Suspended",
			"checkpoint": json.dumps(payload, default=str),
			"pending_human_task": human_row_id,
			"suspended_at": now_datetime(),
		},
		update_modified=True,
	)
	return run


def get_suspended_run(instance_name: str, bpmn_id: str = None, human_row_id: str = None):
	"""The latest Suspended AI Agent Run for an instance, optionally narrowed by bpmn_id or by the human task
	row it is waiting for. Returns a name or None. Uses get_all: engine-internal lookup, runs in
	workers/hooks."""
	filters = {"instance": instance_name, "status": "Suspended"}
	if bpmn_id:
		filters["bpmn_id"] = bpmn_id
	if human_row_id:
		filters["pending_human_task"] = human_row_id
	rows = frappe.get_all("AI Agent Run", filters=filters, order_by="creation desc", limit=1, pluck="name")
	return rows[0] if rows else None


def store_human_result(run_name: str, human_result) -> None:
	"""Record the human task's output on the checkpoint (pending_result) so the resume job - which may run
	later, elsewhere - has everything it needs."""
	run = frappe.get_doc("AI Agent Run", run_name, for_update=True)
	payload = json.loads(run.checkpoint or "{}")
	payload["pending_result"] = human_result
	run.db_set("checkpoint", json.dumps(payload, default=str), update_modified=True)


def claim_for_resume(run_name: str) -> dict | None:
	"""Atomically claim a suspended run for resumption."""
	run = frappe.get_doc("AI Agent Run", run_name, for_update=True)
	if run.status != "Suspended":
		return None
	payload = json.loads(run.checkpoint or "{}")
	# Bank the time this suspension waited; suspended_at is cleared so a later resume never counts it twice.
	update = {"status": "Running", "pending_human_task": ""}
	if run.get("suspended_at"):
		waited_ms = int((now_datetime() - frappe.utils.get_datetime(run.suspended_at)).total_seconds() * 1000)
		update["human_wait_ms"] = int(run.get("human_wait_ms") or 0) + max(0, waited_ms)
		update["suspended_at"] = None
	run.db_set(update, update_modified=True)
	return payload


def build_resume_state(payload: dict) -> dict:
	"""ExecutorConfig.resume_state from a claimed checkpoint payload."""
	suspension = payload.get("suspension") or {}
	return {
		"transcript": suspension.get("transcript") or [],
		"pending_call": suspension.get("pending_call") or {},
		"deferred_results": suspension.get("deferred_results") or [],
		"turns_used": int(suspension.get("turns_used") or 0),
		"trace": suspension.get("trace") or [],
		"human_result": human_result_str(payload.get("pending_result")),
	}


def human_result_str(pending_result) -> str:
	"""The tool-result string the model sees for the completed human task."""
	if pending_result is None:
		return ""
	if isinstance(pending_result, str):
		return pending_result
	try:
		return json.dumps(pending_result, default=str)
	except Exception:
		return str(pending_result)
