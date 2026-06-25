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
from one_bpmn.agents.pricing import get_model_pricing

# Max size for final_output stored on the Run (64 KB)
_MAX_OUTPUT_CHARS = 64 * 1024


def create_ai_run(
	instance,
	bpmn_id: str,
	element_type: str,
	config: ExecutorConfig,
) -> "frappe.Document":
	"""Create an AI Agent Run record with status="Running".

	Args:
	    instance: BPMN Process Instance document
	    bpmn_id: Element ID on the diagram
	    element_type: "task" or "subprocess"
	    config: ExecutorConfig from the dispatcher

	Returns:
	    The created AI Agent Run document.
	"""
	import frappe

	run = frappe.get_doc({
		"doctype": "AI Agent Run",
		"instance": instance.name,
		"bpmn_id": bpmn_id,
		"element_type": element_type,
		"backend": config.backend,
		"provider": config.provider_name,
		"model": config.model,
		"status": "Running",
		"started_at": now_datetime(),
		"correlation_id": frappe.generate_hash(length=16),
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
	latency_ms: int = 0,
	tool_name: str = None,
	tool_args: dict = None,
	tool_result: str = None,
) -> Optional["frappe.Document"]:
	"""Record a single AI Agent Step linked to *run*.

	Computes cost if pricing data is available for the run's model.

	Args:
	    run: AI Agent Run document
	    step_index: 0-based step index
	    role: "system", "user", "assistant", or "tool"
	    content: The rendered prompt text or response text
	    prompt_tokens: Token count for this step's prompt
	    completion_tokens: Token count for this step's completion
	    latency_ms: Step latency in milliseconds

	Returns:
	    The created AI Agent Step document, or None on failure.
	"""
	if getattr(run, "stub", False):
		return None

	# Compute cost
	cost = 0.0
	if getattr(run, "model", None):
		pricing = get_model_pricing(run.model)
		if pricing:
			input_rate = flt(pricing.get("input_cost_per_1k", 0))
			output_rate = flt(pricing.get("output_cost_per_1k", 0))
			cost = (prompt_tokens / 1000.0) * input_rate + (completion_tokens / 1000.0) * output_rate

	step = frappe.get_doc({
		"doctype": "AI Agent Step",
		"run": run.name,
		"step_index": step_index,
		"role": role,
		"content": content,
		"tool_name": tool_name,
		"tool_args": tool_args if tool_args else None,
		"tool_result": tool_result,
		"prompt_tokens": prompt_tokens,
		"completion_tokens": completion_tokens,
		"cost": cost,
		"latency_ms": latency_ms,
	})
	try:
		step.insert(ignore_permissions=True)
		return step
	except Exception as e:
		frappe.log_error(
			title=f"AI Observability: record_ai_step failed (run={run.name}, idx={step_index})",
			message=frappe.get_traceback(),
		)
		return None


def finalize_ai_run(run, result: ExecutorResult) -> None:
	"""Finalize an AI Agent Run after executor completion.

	On SUCCESS: sets status, duration, tokens, cost, output.
	On ERROR:   sets status="Error", error_code, error_message (partial tokens recorded).

	Args:
	    run:  AI Agent Run document (status="Running")
	    result: ExecutorResult from the executor call
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

	if result.error_code == ErrorCode.SUCCESS:
		# Sum step costs from the database
		step_costs = frappe.db.get_all(
			"AI Agent Step",
			filters={"run": run.name},
			pluck="cost",
		)
		estimated_cost = flt(sum(flt(c) for c in step_costs))

		# Final output (truncated)
		output = str(result.output or "")
		if len(output) > _MAX_OUTPUT_CHARS:
			output = output[:_MAX_OUTPUT_CHARS]

		update = {
			"ended_at": ended,
			"duration_ms": int(duration),
			"status": "Success",
			"estimated_cost": estimated_cost,
			"final_output": output,
		}

		# Token totals from the result
		if result.token_usage:
			update["total_prompt_tokens"] = result.token_usage.prompt_tokens
			update["total_completion_tokens"] = result.token_usage.completion_tokens
			update["total_tokens"] = result.token_usage.total_tokens

		run.db_set(update)
	else:
		update = {
			"ended_at": ended,
			"duration_ms": int(duration),
			"status": "Error",
			"error_code": result.error_code.value,
			"error_message": (result.error_message or "")[:_MAX_OUTPUT_CHARS],
		}

		# Record partial tokens on error too
		if result.token_usage:
			update["total_prompt_tokens"] = result.token_usage.prompt_tokens
			update["total_completion_tokens"] = result.token_usage.completion_tokens
			update["total_tokens"] = result.token_usage.total_tokens

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
			"duration_ms": int(duration),
			"status": "Error",
			"error_code": "UNEXPECTED_ERROR",
			"error_message": str(exception)[:_MAX_OUTPUT_CHARS],
		})
	except Exception:
		frappe.log_error(
			title="AI Observability: finalize_ai_run_on_exception failed",
			message=frappe.get_traceback(),
		)
