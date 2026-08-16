"""
Instrumentation layer for AI Agent observability.

Three core functions that sit between the dispatcher and the executor:

- create_ai_run(instance, bpmn_id, element_type, config) → AI Agent Run
- record_ai_step(run, step_index, role, content, tokens, latency_ms) → AI Agent Step
- finalize_ai_run(run, result) → None (updates run status, duration, costs)
- finalize_ai_run_on_exception(run, exception) → None (error handling)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import frappe
from frappe.utils import flt, now_datetime

from one_bpmn.agents.executor import ErrorCode, ExecutorConfig, ExecutorResult
from one_bpmn.agents.pricing import compute_token_cost

# Max size for final_output stored on the Run (64 KB)
_MAX_OUTPUT_CHARS = 64 * 1024

_STEP_METRIC_KEYS = (
	"prompt_tokens",
	"completion_tokens",
	"cache_read_tokens",
	"cache_write_tokens",
	"cost",
	"input_cost",
	"output_cost",
	"cache_read_cost",
	"cache_write_cost",
	"agent_latency_ms",
)


def _sum_step_metrics(run_name: str) -> Dict[str, Any]:
	"""Sum every per-step metric of *run_name* in one query.

	``agent_latency_ms`` is the sum of the steps' own latencies — the time the
	agent was actually working (provider round-trips plus inline tool calls).
	It deliberately excludes wall-clock gaps between steps, which for a
	human-in-the-loop run can be days of waiting (WI-001643).

	Never raises: a failed rollup returns zeros rather than blocking finalize.
	"""
	zeros = {k: 0 for k in _STEP_METRIC_KEYS}
	try:
		row = frappe.db.sql(
			"""
			select
				coalesce(sum(prompt_tokens), 0),
				coalesce(sum(completion_tokens), 0),
				coalesce(sum(cache_read_tokens), 0),
				coalesce(sum(cache_write_tokens), 0),
				coalesce(sum(cost), 0),
				coalesce(sum(input_cost), 0),
				coalesce(sum(output_cost), 0),
				coalesce(sum(cache_read_cost), 0),
				coalesce(sum(cache_write_cost), 0),
				coalesce(sum(latency_ms), 0)
			from `tabAI Agent Step` where run = %s
			""",
			run_name,
		)[0]
	except Exception:
		frappe.log_error(
			title=f"AI Observability: step metric rollup failed ({run_name})",
			message=frappe.get_traceback(),
		)
		return zeros

	totals = dict(zip(_STEP_METRIC_KEYS, row))
	for key in ("prompt_tokens", "completion_tokens", "cache_read_tokens",
	            "cache_write_tokens", "agent_latency_ms"):
		totals[key] = int(totals[key] or 0)
	for key in ("cost", "input_cost", "output_cost", "cache_read_cost", "cache_write_cost"):
		totals[key] = flt(totals[key])
	return totals


def _turn_correlation_id():
	"""The current turn's correlation id, if a screened turn is in progress.

	Imported lazily and defensively: observability must never fail because the
	security package is unavailable or misbehaving.
	"""
	try:
		from one_bpmn.security.turn import current_correlation_id

		return current_correlation_id()
	except Exception:
		return None


def create_ai_run(
	instance,
	bpmn_id: str,
	element_type: str,
	config: ExecutorConfig,
	bpmn_label: str = "",
	process_model: str = "",
) -> "frappe.Document":
	"""Create an AI Agent Run record with status="Running".

	Args:
	    instance: BPMN Process Instance document
	    bpmn_id: Element ID on the diagram
	    element_type: "task" or "subprocess"
	    config: ExecutorConfig from the dispatcher
	    bpmn_label: Human-readable element name from the BPMN diagram
	    process_model: Name of the BPMN Process Model

	Returns:
	    The created AI Agent Run document.
	"""
	import frappe

	# WI-001636/WI-001608: attribute the run to its AI Agent Configuration.
	# Primary source: the shape's own aiAgentConfig link (every AI shape
	# carries one since WI-001650) — covers task AND selector runs. Fallback:
	# the configuration that owns this process model (chat maps provisioned
	# before the live link). Runs nobody owns carry none.
	agent_configuration = None
	try:
		shape_cfg = (getattr(instance, "_service_task_extensions", {}) or {}).get(bpmn_id, {}).get("aiAgentConfig")
		if shape_cfg and frappe.db.exists("AI Agent Configuration", shape_cfg):
			agent_configuration = shape_cfg
	except Exception:
		agent_configuration = None
	owning_model = process_model or getattr(instance, "process_model", "") or ""
	if not agent_configuration and owning_model:
		try:
			agent_configuration = frappe.db.get_value(
				"AI Agent Configuration",
				{"process_model": owning_model, "enabled": 1},
				"name",
			)
		except Exception:
			agent_configuration = None

	# A non-dict flag (or none) means this is not an eval run; guard rather than
	# trust the flag's shape, since any caller can set it.
	eval_origin = getattr(frappe.flags, "eval_origin", None)
	if not isinstance(eval_origin, dict):
		eval_origin = {} if not eval_origin else {"eval_case": None, "eval_run": None}

	run = frappe.get_doc({
		"doctype": "AI Agent Run",
		"instance": instance.name,
		"bpmn_id": bpmn_id,
		"bpmn_label": bpmn_label or "",
		"process_model": process_model or "",
		"agent_configuration": agent_configuration,
		"element_type": element_type,
		"backend": config.backend,
		"provider": config.provider_name,
		"model": config.model,
		# WI-001751: runs produced while an eval is invoking the agent are
		# tagged so Insights can show them under a separate "Evals" segment.
		# The flag also names WHICH case and run, so reviewing an eval no longer
		# means filtering by origin and matching on a time window.
		"origin": "eval" if eval_origin else "production",
		"eval_case": eval_origin.get("eval_case") or None,
		"eval_run": eval_origin.get("eval_run") or None,
		"status": "Running",
		"started_at": now_datetime(),
		"max_retries": config.max_retries,
		# WI-001967: reuse the turn's correlation id when one was minted upstream,
		# so a security event recorded before this run existed can be joined to it.
		# Falls back to a fresh id for runs that start outside a screened turn.
		"correlation_id": _turn_correlation_id() or frappe.generate_hash(length=16),
	})
	try:
		run.insert(ignore_permissions=True)
	except Exception as e:
		frappe.log_error(
			title=f"AI Observability: create_ai_run failed ({bpmn_id})",
			message=frappe.get_traceback(),
		)
		# Return a lightweight stub so callers don't need to null-check
		run.stub = True
	return run


def record_ai_step(
	run,
	step_index: int,
	role: str,
	content: str,
	*,
	prompt_tokens: int = 0,
	completion_tokens: int = 0,
	cache_read_tokens: int = 0,
	cache_write_tokens: int = 0,
	latency_ms: int = 0,
	tool_calls: list | None = None,
	error_code: str = None,
	error_message: str = None,
) -> Optional["frappe.Document"]:
	"""Record a single AI Agent Step linked to *run*.

	Computes cost if pricing data is available for the run's model, splitting the
	prompt across its three billing rates (WI-001643).

	Args:
	    run: AI Agent Run document
	    step_index: 0-based step index
	    role: "system", "user", "assistant", or "tool"
	    content: The rendered prompt text or response text
	    prompt_tokens: FULL consumed input context for this step — inclusive of
	        the two cache figures below, never exclusive of them
	    completion_tokens: Token count for this step's completion
	    cache_read_tokens: Part of prompt_tokens served from the prompt cache
	    cache_write_tokens: Part of prompt_tokens written into the prompt cache
	    latency_ms: Step latency in milliseconds
	    error_code: Error code if this step is a failed retry attempt
	    error_message: Error details for failed retry attempts

	Returns:
	    The created AI Agent Step document, or None on failure.
	"""
	if getattr(run, "stub", False):
		return None

	# Cost split by billing rate: uncached input / cache read / cache write /
	# output. Charging the whole prompt at the input rate (pre-WI-001643)
	# overstated spend wherever prompt caching was active.
	costs = compute_token_cost(
		getattr(run, "model", None) or "",
		prompt_tokens=prompt_tokens,
		completion_tokens=completion_tokens,
		cache_read_tokens=cache_read_tokens,
		cache_write_tokens=cache_write_tokens,
	)

	step = frappe.get_doc({
		"doctype": "AI Agent Step",
		"run": run.name,
		"step_index": step_index,
		"role": role,
		"content": content,
		"prompt_tokens": prompt_tokens,
		"completion_tokens": completion_tokens,
		"cache_read_tokens": cache_read_tokens,
		"cache_write_tokens": cache_write_tokens,
		"cost": costs["total_cost"],
		"input_cost": costs["input_cost"],
		"output_cost": costs["output_cost"],
		"cache_read_cost": costs["cache_read_cost"],
		"cache_write_cost": costs["cache_write_cost"],
		"latency_ms": latency_ms,
		"error_code": error_code or None,
		"error_message": error_message or None,
	})
	# WI-001358: one child row per tool actually called in this turn. A
	# single LLM turn can contain several calls — they stay grouped under
	# this Step with its one shared token/cost figure. (The legacy flat
	# tool_name/tool_args/tool_result fields were removed 2026-07-04 —
	# the child table is the sole record of tool calls.)
	for call in tool_calls or []:
		step.append(
			"tool_calls",
			{
				"tool_name": call.get("name") or call.get("tool_name") or "",
				"tool_source": call.get("tool_source") or "",
				"tool_args": call.get("arguments") or call.get("tool_args") or None,
				"tool_result": call.get("result") or call.get("tool_result") or "",
				"status": call.get("status") or "Success",
			},
		)
	try:
		step.insert(ignore_permissions=True)
		return step
	except Exception as e:
		frappe.log_error(
			title=f"AI Observability: record_ai_step failed (run={run.name}, idx={step_index})",
			message=frappe.get_traceback(),
		)
		return None


def finalize_ai_run(run, result: ExecutorResult, goal_key: str | None = None) -> None:
	"""Finalize an AI Agent Run after executor completion.

	On SUCCESS: sets status, duration, tokens, cost, output.
	On ERROR:   sets status="Error", error_code, error_message (partial tokens recorded).

	Args:
	    run:  AI Agent Run document (status="Running")
	    result: ExecutorResult from the executor call
	    goal_key: optional reply key the map declares as its definition of done
	        (WI-001823). When absent, completion falls back to error/turn-cap/
	        output signals; either way the run never records a guess.
	"""
	if run is None or getattr(run, "stub", False):
		return

	ended = now_datetime()
	started = run.started_at

	# Compute duration
	if started and isinstance(started, datetime):
		duration = (ended - started).total_seconds() * 1000
	else:
		duration = 0

	# Cost + agent-latency rollups come from the recorded Steps either way — a
	# failed run still consumed tokens and still spent real time.
	step_totals = _sum_step_metrics(run.name)

	update = {
		"ended_at": ended,
		"duration_ms": int(duration),
		"agent_latency_ms": step_totals["agent_latency_ms"],
		"estimated_cost": step_totals["cost"],
		"total_input_cost": step_totals["input_cost"],
		"total_output_cost": step_totals["output_cost"],
		"total_cache_read_cost": step_totals["cache_read_cost"],
		"total_cache_write_cost": step_totals["cache_write_cost"],
		"retry_count": len(result.attempts),
	}

	if result.error_code == ErrorCode.SUCCESS:
		# Final output (truncated)
		output = str(result.output or "")
		if len(output) > _MAX_OUTPUT_CHARS:
			output = output[:_MAX_OUTPUT_CHARS]
		update["status"] = "Success"
		update["final_output"] = output
	else:
		update["status"] = "Error"
		update["error_code"] = result.error_code.value
		update["error_message"] = (result.error_message or "")[:_MAX_OUTPUT_CHARS]

	# WI-001823: what the executor itself knows about the outcome, folded into
	# the same write. The stronger signal — whether the map reached its end
	# event — arrives later, from settle_for_instance.
	from one_bpmn.agents import goal_completion

	state, basis = goal_completion.determine(result, goal_key)
	update["goal_completion"] = state
	update["completion_basis"] = basis

	# Token totals from the result (partial tokens are recorded on error too).
	if result.token_usage:
		update["total_prompt_tokens"] = result.token_usage.prompt_tokens
		update["total_completion_tokens"] = result.token_usage.completion_tokens
		update["total_tokens"] = result.token_usage.total_tokens
		update["total_cache_read_tokens"] = getattr(result.token_usage, "cache_read_tokens", 0) or 0
		update["total_cache_write_tokens"] = getattr(result.token_usage, "cache_write_tokens", 0) or 0

	run.db_set(update)


def finalize_ai_run_on_exception(run, exception: Exception) -> None:
	"""Finalize an AI Agent Run when an unexpected exception occurs.

	Records the error without an ExecutorResult.

	Args:
	    run: AI Agent Run document (status="Running")
	    exception: The unhandled exception
	"""
	if run is None or getattr(run, "stub", False):
		return

	ended = now_datetime()
	started = run.started_at

	if started and isinstance(started, datetime):
		duration = (ended - started).total_seconds() * 1000
	else:
		duration = 0

	try:
		run.db_set({
			"ended_at": ended,
			"goal_completion": "Not Achieved",
			"completion_basis": "The run raised an unhandled exception.",
			"duration_ms": int(duration),
			"agent_latency_ms": _sum_step_metrics(run.name)["agent_latency_ms"],
			"status": "Error",
			"error_code": "UNEXPECTED_ERROR",
			"error_message": str(exception)[:_MAX_OUTPUT_CHARS],
		})
	except Exception:
		frappe.log_error(
			title="AI Observability: finalize_ai_run_on_exception failed",
			message=frappe.get_traceback(),
		)


# ─────────────────────────────────────────────────────────────
# Ad-hoc / AI Task Selector instrumentation (WI-001358)
#
# One ad-hoc subprocess's ENTIRE agent loop is one AI Agent Run
# (element_type="subprocess"), reused across decision points; one AI Agent
# Step per real LLM turn from the executor trace (WI-001356); one AI Agent
# Tool Call child row per tool actually called within a turn. All helpers
# swallow their own failures — instrumentation must never block dispatch
# (same guarantee dispatch_ai_agent's instrumentation documents, AI-009).
# ─────────────────────────────────────────────────────────────


def get_or_create_selector_run(instance, bpmn_id: str, config, bpmn_label: str = "", process_model: str = ""):
	"""Return the open subprocess Run for (instance, bpmn_id), or create one.

	Subsequent decision points of the same ad-hoc subprocess reuse the same
	AI Agent Run, appending Steps — a subprocess run is one Run, not one per
	LLM call.
	"""
	try:
		existing = frappe.get_all(
			"AI Agent Run",
			filters={
				"instance": instance.name,
				"bpmn_id": bpmn_id,
				"element_type": "subprocess",
				"status": "Running",
			},
			pluck="name",
			limit_page_length=1,
		)
		if existing:
			return frappe.get_doc("AI Agent Run", existing[0])
	except Exception:
		frappe.log_error(
			title=f"AI Observability: selector run lookup failed ({bpmn_id})",
			message=frappe.get_traceback(),
		)
	return create_ai_run(
		instance, bpmn_id, "subprocess", config,
		bpmn_label=bpmn_label, process_model=process_model,
	)


def record_selector_turns(run, trace: list, source_map: dict | None = None) -> int:
	"""Append one AI Agent Step per turn of an executor trace to *run*.

	Turns with tool calls become role="tool" Steps carrying one AI Agent
	Tool Call row per call (tool_source resolved via *source_map*,
	{tool_name: "diagram_task"|"registry_tool"}); the final-answer turn
	becomes a role="assistant" Step with no Tool Call rows.

	Returns the number of Steps recorded.
	"""
	if getattr(run, "stub", False):
		return 0
	source_map = source_map or {}
	# step_index is 1-based: with N steps already recorded, the next is N+1.
	try:
		start_index = frappe.db.count("AI Agent Step", {"run": run.name}) + 1
	except Exception:
		start_index = 1

	recorded = 0
	for offset, turn in enumerate(trace or []):
		tool_calls = [
			{
				"name": call.get("name", ""),
				"tool_source": source_map.get(call.get("name", ""), ""),
				"arguments": call.get("arguments") or {},
				"result": call.get("result", ""),
				"status": "Error" if str(call.get("result", "")).startswith(
					("Error calling", "Unknown tool:")
				) else "Success",
			}
			for call in turn.get("tool_calls") or []
		]
		step = record_ai_step(
			run,
			start_index + offset,
			turn.get("role") or ("tool" if tool_calls else "assistant"),
			turn.get("content") or "",
			prompt_tokens=turn.get("prompt_tokens", 0),
			completion_tokens=turn.get("completion_tokens", 0),
			cache_read_tokens=turn.get("cache_read_tokens", 0),
			cache_write_tokens=turn.get("cache_write_tokens", 0),
			latency_ms=turn.get("latency_ms", 0),
			tool_calls=tool_calls,
		)
		if step is not None:
			recorded += 1

	# Selector runs stay "Running" for the whole subprocess — roll the
	# totals up after every decision so the instance page shows live
	# token/cost/duration numbers instead of zeros until finalize.
	if recorded:
		update_selector_run_rollups(run)
	return recorded


def record_activation_outcome(instance_name: str, task_bpmn_id: str, outcome: str) -> bool:
	"""Attach the real-world outcome to the tool call that activated a
	diagram task, once that task has completed in the engine.

	The tool_result stays the honest transcript of what the model was told
	at call time ("will be activated…"); outcome is what actually happened.
	Targets the most recent outcome-less call of *task_bpmn_id* across the
	instance's runs. Returns True when a row was updated.
	"""
	if not (instance_name and task_bpmn_id and (outcome or "").strip()):
		return False
	try:
		rows = frappe.db.sql(
			"""
			select tc.name
			from `tabAI Agent Tool Call` tc
			join `tabAI Agent Step` s on tc.parent = s.name
			join `tabAI Agent Run` r on s.run = r.name
			where r.instance = %s
			  and tc.tool_name = %s
			  and tc.tool_source = 'diagram_task'
			  and ifnull(tc.outcome, '') = ''
			order by tc.creation desc
			limit 1
			""",
			(instance_name, task_bpmn_id),
		)
		if not rows:
			return False
		frappe.db.set_value(
			"AI Agent Tool Call", rows[0][0], "outcome", outcome.strip(), update_modified=False
		)
		return True
	except Exception:
		frappe.log_error(
			title=f"AI Observability: activation outcome failed ({task_bpmn_id})",
			message=frappe.get_traceback(),
		)
		return False


def update_selector_run_rollups(run) -> None:
	"""Refresh a Running selector run's token/cost/duration rollups from its
	recorded Steps. Cheap (one aggregate query) and idempotent; finalize
	still owns status/ended_at/final_output."""
	if getattr(run, "stub", False):
		return
	try:
		totals = _sum_step_metrics(run.name)
		duration_ms = 0
		if getattr(run, "started_at", None):
			duration_ms = int(
				(now_datetime() - frappe.utils.get_datetime(run.started_at)).total_seconds() * 1000
			)
		run.db_set(
			{
				"total_prompt_tokens": totals["prompt_tokens"],
				"total_completion_tokens": totals["completion_tokens"],
				"total_tokens": totals["prompt_tokens"] + totals["completion_tokens"],
				"total_cache_read_tokens": totals["cache_read_tokens"],
				"total_cache_write_tokens": totals["cache_write_tokens"],
				"estimated_cost": totals["cost"],
				"total_input_cost": totals["input_cost"],
				"total_output_cost": totals["output_cost"],
				"total_cache_read_cost": totals["cache_read_cost"],
				"total_cache_write_cost": totals["cache_write_cost"],
				"duration_ms": duration_ms,
				"agent_latency_ms": totals["agent_latency_ms"],
			},
			update_modified=False,
		)
	except Exception:
		frappe.log_error(
			title="AI Observability: selector rollup failed",
			message=frappe.get_traceback(),
		)


def finalize_open_selector_runs(instance_name: str, bpmn_id: str) -> int:
	"""Finalize every still-Running selector run for (instance, subprocess).
	Called when the ad-hoc subprocess completes — the moment a selector run
	is actually over. Returns the number of runs finalized."""
	count = 0
	try:
		for name in frappe.get_all(
			"AI Agent Run",
			filters={
				"instance": instance_name,
				"bpmn_id": bpmn_id,
				"element_type": "subprocess",
				"status": "Running",
			},
			pluck="name",
		):
			finalize_selector_run(frappe.get_doc("AI Agent Run", name))
			count += 1
	except Exception:
		frappe.log_error(
			title=f"AI Observability: finalize_open_selector_runs failed ({bpmn_id})",
			message=frappe.get_traceback(),
		)
	return count


def finalize_selector_run(run) -> None:
	"""Finalize a subprocess Run exactly once, when the ad-hoc subprocess
	completes: status, ended_at, duration, token/cost rollups summed across
	all Steps, and final_output = the last role="assistant" Step's content —
	the turn where the loop ended because the LLM stopped calling tools.
	"""
	if getattr(run, "stub", False) or getattr(run, "status", "") != "Running":
		return
	try:
		steps = frappe.get_all(
			"AI Agent Step",
			filters={"run": run.name},
			fields=["role", "content", "prompt_tokens", "completion_tokens", "cost"],
			order_by="step_index asc",
		)
		final_output = ""
		for step in steps:
			if step.role == "assistant" and (step.content or "").strip():
				final_output = step.content

		# Full rollup (prompt/completion split, costs, duration) shared with
		# the per-decision live update.
		update_selector_run_rollups(run)

		ended = now_datetime()
		duration_ms = 0
		if getattr(run, "started_at", None):
			duration_ms = int(
				(ended - frappe.utils.get_datetime(run.started_at)).total_seconds() * 1000
			)
		run.db_set(
			{
				"status": "Success",
				"ended_at": ended,
				"duration_ms": duration_ms,
				"agent_latency_ms": _sum_step_metrics(run.name)["agent_latency_ms"],
				"final_output": final_output,
			},
			update_modified=True,
		)
	except Exception:
		frappe.log_error(
			title=f"AI Observability: finalize_selector_run failed ({getattr(run, 'name', '?')})",
			message=frappe.get_traceback(),
		)
