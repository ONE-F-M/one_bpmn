# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Dev Agent Sandbox's push callback (mirrors api/a2a_api.push_callback's
security shape, WI-001933's push endpoint).

Reachable without a Frappe session — the sandbox has no user here — so an
HMAC signature over the exact request body IS the gate, verified against
Processa Settings.agent_callback_secret (the same secret the sandbox
was deployed with — see agent-sandbox/deploy.py). Every failure returns
the same opaque answer: a caller must not be able to use this endpoint to
learn which correlation ids exist or why a signature was rejected.

The sandbox opens the pull request itself, directly against GitHub — as one
of its own tool calls now (open_pull_request), not automatic post-loop logic
— before it ever calls back. This endpoint only records what already
happened (pr_url on a pass, or why one wasn't opened, including "the agent
never called open_pull_request") and resumes whoever is waiting. It never
talks to GitHub on the sandbox's behalf.

payload["agent_trace"] (one entry per coding-loop turn, replacing the old
flat agent_tool_calls list of bare names) is turned into real AI Agent Step
+ AI Agent Tool Call rows here (_record_sandbox_trace) — the same
observability every other AI Agent Task in the system gets via
record_ai_step(), for a loop that runs entirely outside Frappe and can only
ever be recorded from this one callback.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime

import frappe

from one_bpmn.agents.observability import record_ai_step


@frappe.whitelist(allow_guest=True, methods=["POST"])
def report_result() -> dict:
	opaque = {"accepted": False}

	raw_body = frappe.request.get_data()
	presented_signature = (frappe.get_request_header("X-Signature") or "").strip()
	if not presented_signature:
		return opaque

	# .strip() is deliberate — a secret created via `openssl rand -hex 32 |
	# gcloud secrets create ...` carries a trailing newline that a person
	# copy-pasting the same value into this field will not reproduce.
	# Confirmed the hard way: every callback was rejected as a signature
	# mismatch even though both sides held what looked like the identical
	# secret. Symmetric with the .strip() on CALLBACK_HMAC_SECRET in
	# dev_agent_server.py.
	secret = (frappe.get_cached_doc("Processa Settings").get_password("agent_callback_secret") or "").strip()
	if not secret:
		frappe.log_error(
			title="Dev Agent Sandbox: callback rejected — no callback secret configured",
			message="Processa Settings.agent_callback_secret is blank.",
		)
		return opaque

	expected_signature = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
	if not hmac.compare_digest(presented_signature, expected_signature):
		frappe.log_error(
			title="Dev Agent Sandbox: callback rejected — signature mismatch",
			message="Presented X-Signature did not match the expected HMAC.",
		)
		return opaque

	try:
		payload = json.loads(raw_body or b"{}")
	except Exception:
		return opaque
	if not isinstance(payload, dict):
		return opaque

	correlation_id = payload.get("correlation_id")
	if not correlation_id or not frappe.db.exists("Agent Sandbox Run", correlation_id):
		# Deliberately indistinguishable from a signature failure.
		return opaque

	run = frappe.get_doc("Agent Sandbox Run", correlation_id)
	if run.state in ("completed", "failed"):
		return {"accepted": True}  # already settled — a replayed callback is a no-op

	status = payload.get("status")
	run.db_set("result", frappe.as_json(payload), update_modified=False)

	agent_run_name = _create_sandbox_ai_agent_run(run, payload)
	if agent_run_name:
		run.db_set("ai_agent_run", agent_run_name, update_modified=False)

	# The sandbox now opens a PR whenever there are changed files, whether or
	# not tests passed (dev_agent_server.py's _open_pr marks a failing one
	# clearly rather than discarding a possibly-good change over a failure
	# that may be unrelated to it) — so pr_url/files can arrive on either
	# status, and both are recorded here regardless of what follows.
	files = payload.get("files") or {}
	pr_url = payload.get("pr_url") or ""
	if files:
		run.db_set("files", frappe.as_json(files), update_modified=False)

	if status == "tests_passed":
		if pr_url:
			run.db_set({"state": "completed", "pr_url": pr_url}, update_modified=False)
		else:
			error = payload.get("pr_error") or "Sandbox reported tests_passed but did not open a pull request."
			run.db_set({"state": "failed", "error_message": error[:500]}, update_modified=False)
	elif status == "tests_passed_no_changes":
		run.db_set(
			{"state": "failed", "error_message": "Tests passed but the agent made no changes to submit."},
			update_modified=False,
		)
	else:
		# A PR opened despite the failure doesn't make this a success — the
		# run's own state still reflects that tests didn't pass. pr_url is
		# still recorded above so the diff stays reachable for review.
		fields = {"error_message": (payload.get("error") or status or "sandbox run failed")[:500]}
		if pr_url:
			fields["pr_url"] = pr_url
		run.db_set({"state": "failed", **fields}, update_modified=False)

	_enqueue_resume(run)
	return {"accepted": True}


def _create_sandbox_ai_agent_run(run, payload: dict) -> str | None:
	"""Track the sandbox's own coding-loop turn as a real AI Agent Run, so
	its cost/tokens/tool calls show up the same way any other agent turn
	does — reusing that doctype's existing fields rather than duplicating
	them on Agent Sandbox Run. That loop runs entirely outside Frappe (on
	Cloud Run), so this callback is the only place it can ever be recorded;
	nothing else in Processa ever sees it.

	Returns the new run's name, or None when the payload carries no usage
	(the coding loop never started — e.g. it crashed before its first model
	call, which run_job() reports as a bare error with no agent_usage key).
	"""
	usage = payload.get("agent_usage")
	if not isinstance(usage, dict):
		return None

	from frappe.utils import flt

	from one_bpmn.agents.pricing import get_model_pricing

	model = payload.get("agent_model") or ""
	input_tokens = usage.get("input_tokens", 0) or 0
	output_tokens = usage.get("output_tokens", 0) or 0
	cache_read_tokens = usage.get("cache_read_input_tokens", 0) or 0
	cache_write_tokens = usage.get("cache_creation_input_tokens", 0) or 0

	pricing = get_model_pricing(model) or {}
	input_cost = (input_tokens / 1000.0) * flt(pricing.get("input_cost_per_1k", 0))
	output_cost = (output_tokens / 1000.0) * flt(pricing.get("output_cost_per_1k", 0))
	cache_read_cost = (cache_read_tokens / 1000.0) * flt(pricing.get("cache_read_cost_per_1k", 0))
	cache_write_cost = (cache_write_tokens / 1000.0) * flt(pricing.get("cache_write_cost_per_1k", 0))

	# Unix epoch seconds (time.time() on the sandbox side) — get_datetime()
	# parses date strings/objects, not raw epoch floats, so these need
	# datetime.fromtimestamp() first or they'd fail AI Agent Run's own
	# mandatory-field check on started_at with a silently-wrong value.
	started_at_raw = payload.get("agent_started_at")
	ended_at_raw = payload.get("agent_ended_at")
	started_at = datetime.fromtimestamp(started_at_raw) if started_at_raw else None
	ended_at = datetime.fromtimestamp(ended_at_raw) if ended_at_raw else None
	duration_ms = int((ended_at_raw - started_at_raw) * 1000) if started_at_raw and ended_at_raw else 0

	status = payload.get("status") or ""
	if status == "tests_passed":
		goal_completion, completion_basis = "Achieved", "The sandbox's real test suite passed."
	elif status in ("tests_failed", "tests_passed_no_changes"):
		goal_completion, completion_basis = "Not Achieved", f"Sandbox reported {status}."
	else:
		goal_completion, completion_basis = "Unknown", "Sandbox run did not reach a test result."

	agent_run = frappe.get_doc({
		"doctype": "AI Agent Run",
		"instance": run.caller_instance,
		"agent_configuration": "Dev Agent",
		"bpmn_id": "dispatch_to_sandbox",
		"bpmn_label": "Dispatch to sandbox",
		"element_type": "task",
		"backend": "direct_api",
		"provider": "Anthropic",
		"model": model,
		"status": "Success",  # the loop itself completed; goal_completion carries the outcome
		"started_at": started_at or frappe.utils.now_datetime(),
		"ended_at": ended_at,
		"duration_ms": duration_ms,
		"total_prompt_tokens": input_tokens,
		"total_completion_tokens": output_tokens,
		"total_tokens": input_tokens + output_tokens + cache_read_tokens + cache_write_tokens,
		"total_cache_read_tokens": cache_read_tokens,
		"total_cache_write_tokens": cache_write_tokens,
		"estimated_cost": input_cost + output_cost + cache_read_cost + cache_write_cost,
		"total_input_cost": input_cost,
		"total_output_cost": output_cost,
		"total_cache_read_cost": cache_read_cost,
		"total_cache_write_cost": cache_write_cost,
		"goal_completion": goal_completion,
		"completion_basis": completion_basis,
		"final_output": (payload.get("agent_report") or "")[:65536],
		"correlation_id": run.name,
	})
	try:
		agent_run.insert(ignore_permissions=True)
		trace = payload.get("agent_trace") or []
		_record_sandbox_trace(agent_run, trace)
		# Set separately, not in the initial dict above — confirmed the hard
		# way that a field set only in the initial insert() dict can be
		# silently dropped somewhere in insert()'s own pipeline (other fields
		# in the same dict, some also read_only, save correctly; this one
		# alone came back None on reload every time). db_set() writes
		# directly and always sticks. tool_calls itself is now a cheap
		# derived summary (just the names, in call order) — the real detail
		# lives in the AI Agent Step/AI Agent Tool Call rows just recorded.
		agent_run.db_set(
			"tool_calls",
			frappe.as_json([call["name"] for turn in trace for call in turn.get("tool_calls") or []]),
			update_modified=False,
		)
	except Exception:
		frappe.log_error(
			title=f"Dev Agent Sandbox: could not record the coding loop's AI Agent Run ({run.name})",
			message=frappe.get_traceback(),
		)
		return None
	return agent_run.name


def _record_sandbox_trace(agent_run, trace: list) -> None:
	"""One AI Agent Step per turn of the sandbox's own coding loop, each
	carrying one AI Agent Tool Call row per call made in that turn — the
	same observability every other AI Agent Task in the system already gets
	via record_ai_step(), now extended to a loop that runs entirely outside
	Frappe (on Cloud Run) and can only ever be recorded from here.

	Deliberately NOT agents/observability.py's own record_selector_turns,
	despite the trace shape (dev_agent_server.py's _run_coding_loop was built
	to match it exactly): that helper re-derives each call's status via
	_tool_call_status(), which classifies Processa's OWN tool-loop error
	string conventions ("Blocked by policy:", "Error calling ...") — the
	sandbox's tool results are {"error": ...} dicts, not those strings, so
	every sandbox failure would silently re-classify as "Success" if run
	through that helper instead of trusting the status the loop already
	computed correctly.

	result is JSON-stringified before it reaches record_ai_step — confirmed
	the hard way that its tool_result field (Long Text, unlike tool_args'
	JSON fieldtype which Frappe auto-serializes) has no such handling: a raw
	dict fails at the SQL parameter-binding layer with "dict can not be used
	as parameter", silently, since record_ai_step's own insert() call is
	wrapped in a try/except that logs and swallows it. Processa's own tool
	loop never hits this because its own results are already strings by the
	time they reach record_selector_turns — the sandbox's are not."""
	for step_index, turn in enumerate(trace):
		tool_calls = []
		for call in turn.get("tool_calls") or []:
			call = dict(call)
			if not isinstance(call.get("result"), str):
				call["result"] = frappe.as_json(call.get("result"))
			tool_calls.append(call)
		record_ai_step(
			agent_run,
			step_index,
			turn.get("role") or "assistant",
			turn.get("content") or "",
			prompt_tokens=turn.get("prompt_tokens", 0),
			completion_tokens=turn.get("completion_tokens", 0),
			cache_read_tokens=turn.get("cache_read_tokens", 0),
			cache_write_tokens=turn.get("cache_write_tokens", 0),
			latency_ms=turn.get("latency_ms", 0),
			tool_calls=tool_calls,
		)


def _enqueue_resume(run) -> None:
	"""Two shapes of caller, one entry point — mirrors tasks.py's
	_wake_a2a_caller exactly, for the same reason:

	- a plain, top-level parked Service Task on a diagram (the standalone
	  Dev Agent map's own dispatch_to_sandbox step) → resume that step
	  directly via kind="agent_sandbox_result".
	- an agent suspended mid-turn because it called dispatch_to_sandbox as
	  an ai_agent tool (e.g. from Dev Agent's own instruction-parsing step)
	  → hand the answer to its checkpoint and resume the agent, exactly as
	  completing a human task does.

	caller_agent_run is only ever set by the second case (see
	bpmn_process_instance._bind_agent_sandbox_wait), so checking it
	first is the whole routing decision.
	"""
	if run.caller_agent_run:
		_resume_waiting_agent(run)
		return

	from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import (
		_enqueue_agent_sandbox_resume,
	)

	_enqueue_agent_sandbox_resume(run.caller_instance, run.caller_wf_task_id, run.name)


def _resume_waiting_agent(run) -> None:
	"""Give the sandbox's outcome to the agent suspended waiting for it.

	Mirrors tasks.py._resume_waiting_agent (the A2A case) exactly: store the
	result on the checkpoint, then resume in the AI worker via
	kind="human_resume" — to the agent this is the same event as a human
	answering the tool call it paused on.
	"""
	import json as _json

	from one_bpmn.agents import checkpoint as _checkpoint

	agent_run = run.caller_agent_run
	if not (agent_run and run.caller_instance):
		return
	if frappe.db.get_value("AI Agent Run", agent_run, "status") != "Suspended":
		return  # already resumed or failed — nothing is waiting

	_checkpoint.store_human_result(agent_run, _sandbox_run_answer(run))

	payload = _json.loads(frappe.db.get_value("AI Agent Run", agent_run, "checkpoint") or "{}")
	frappe.enqueue(
		"one_bpmn.one_bpmn.doctype.bpmn_process_instance"
		".bpmn_process_instance.run_parked_ai_task",
		queue="bpmn_ai_agent",
		timeout=600,
		enqueue_after_commit=True,
		job_id=f"bpmn-ai-{run.caller_instance}-devagentres-{run.name}",
		deduplicate=True,
		instance_name=run.caller_instance,
		kind="human_resume",
		task_id=payload.get("wf_task_id") or run.caller_wf_task_id or "",
		run_as_user="Administrator",
	)


def _sandbox_run_answer(run) -> str:
	"""What the model is told the sandbox tool call returned — same shape
	as _delegation_answer's reasoning in tasks.py: a failure is reported in
	words, not hidden, since the agent asked for this work and deserves to
	know what actually happened.

	A failing run can still carry a pr_url now (the sandbox opens one
	regardless of test outcome) — that has to be mentioned even on the
	failure branch, or the caller would never learn a PR exists just
	because the state isn't "completed"."""
	if run.state == "completed":
		return f"Pull request opened: {run.pr_url}" if run.pr_url else "Sandbox run completed with no changes to submit."
	reason = f"The sandbox run did not complete ({run.state}): {run.error_message or 'no reason given'}"
	if run.pr_url:
		reason += f" A pull request was still opened for review, despite the failure: {run.pr_url}"
	return reason
