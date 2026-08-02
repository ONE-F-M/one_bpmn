# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Durable AI Agent HITL, story 2 — checkpoint persistence + resume entry point.

A suspended agent's full in-flight state lives on its AI Agent Run row
(status="Suspended"): the provider-agnostic conversation transcript, the
pending human tool call, the deferred sibling results, cumulative turn/token
counters, and the linkage back to the engine (workflow task id + the
active-task row id of the spawned human task). Database-persisted by design —
human steps are long-lived and must survive worker restarts and migrations.

Idempotency: resume happens exactly once per suspension. claim_for_resume()
flips status Suspended→Running under a row lock; a redelivered job or a
double-submitted human task finds status != "Suspended" and no-ops.
"""
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
	prior_prompt_tokens: int = 0,
	prior_completion_tokens: int = 0,
	prior_cache_read_tokens: int = 0,
	prior_cache_write_tokens: int = 0,
):
	"""Persist a suspension on its AI Agent Run (status="Suspended").

	Returns the run document the checkpoint was written to. When observability
	could not create a run (it never blocks the executor), a minimal run is
	created here instead — the checkpoint is load-bearing, not telemetry.
	"""
	if run is None or getattr(run, "stub", False):
		run = frappe.get_doc({
			"doctype": "AI Agent Run",
			"instance": instance.name,
			"process_model": instance.process_model or "",
			"bpmn_id": bpmn_id,
			"element_type": "task",
			"status": "Running",
			"started_at": now_datetime(),
		}).insert(ignore_permissions=True)

	payload = {
		"suspension": suspension,
		"system_prompt": system_prompt,
		"wf_task_id": wf_task_id,
		"human_row_id": human_row_id,
		"pending_result": None,
		"steps_recorded": steps_recorded,
		# Token totals of ALL segments before the next resume — the final
		# segment's usage is added on top so run totals stay cumulative.
		"prompt_tokens_so_far": prior_prompt_tokens + int(suspension.get("prompt_tokens") or 0),
		"completion_tokens_so_far": prior_completion_tokens + int(suspension.get("completion_tokens") or 0),
		# The cache breakdown of prompt_tokens_so_far, carried the same way so
		# cost stays accurate across a multi-suspension run (WI-001643).
		"cache_read_tokens_so_far": prior_cache_read_tokens + int(suspension.get("cache_read_tokens") or 0),
		"cache_write_tokens_so_far": prior_cache_write_tokens + int(suspension.get("cache_write_tokens") or 0),
	}
	run.db_set(
		{
			"status": "Suspended",
			"checkpoint": json.dumps(payload, default=str),
			"pending_human_task": human_row_id,
			# WI-001643: stamp when the wait began so claim_for_resume can add
			# the elapsed time to human_wait_ms. Without this the run's
			# duration_ms silently absorbs the human wait (potentially days) and
			# stops being usable as an agent-latency metric.
			"suspended_at": now_datetime(),
		},
		update_modified=True,
	)
	return run


def get_suspended_run(instance_name: str, bpmn_id: str = None, human_row_id: str = None):
	"""The latest Suspended AI Agent Run for an instance, optionally narrowed
	by bpmn_id or by the human task row it is waiting for. Returns a name or
	None. Uses get_all: engine-internal lookup, runs in workers/hooks."""
	filters = {"instance": instance_name, "status": "Suspended"}
	if bpmn_id:
		filters["bpmn_id"] = bpmn_id
	if human_row_id:
		filters["pending_human_task"] = human_row_id
	rows = frappe.get_all(
		"AI Agent Run", filters=filters, order_by="creation desc", limit=1, pluck="name"
	)
	return rows[0] if rows else None


def store_human_result(run_name: str, human_result) -> None:
	"""Record the human task's output on the checkpoint (pending_result) so the
	resume job — which may run later, elsewhere — has everything it needs."""
	run = frappe.get_doc("AI Agent Run", run_name, for_update=True)
	payload = json.loads(run.checkpoint or "{}")
	payload["pending_result"] = human_result
	run.db_set("checkpoint", json.dumps(payload, default=str), update_modified=True)


def claim_for_resume(run_name: str) -> dict | None:
	"""Atomically claim a suspended run for resumption.

	Returns the checkpoint payload and flips status to "Running", or None if
	the run is not Suspended (already claimed / finished) — the caller must
	treat None as an idempotent no-op.
	"""
	run = frappe.get_doc("AI Agent Run", run_name, for_update=True)
	if run.status != "Suspended":
		return None
	payload = json.loads(run.checkpoint or "{}")
	# WI-001643: bank the time this suspension waited on a person before
	# reopening the run. Accumulates across repeated suspensions; suspended_at is
	# cleared so a later resume can never double-count the same wait.
	update = {"status": "Running", "pending_human_task": ""}
	if run.get("suspended_at"):
		waited_ms = int(
			(now_datetime() - frappe.utils.get_datetime(run.suspended_at)).total_seconds() * 1000
		)
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
		"human_result": _human_result_str(payload.get("pending_result")),
	}


def _human_result_str(pending_result) -> str:
	"""The tool-result string the model sees for the completed human task."""
	if pending_result is None:
		return ""
	if isinstance(pending_result, str):
		return pending_result
	try:
		return json.dumps(pending_result, default=str)
	except Exception:
		return str(pending_result)
