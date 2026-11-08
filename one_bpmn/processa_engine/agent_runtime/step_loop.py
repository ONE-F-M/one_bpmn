# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The step-driven, resumable AI Agent tool loop: one model call per turn, tools run or suspend."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
import time

import frappe

from one_bpmn.ai_agent_security.screening.provenance import wrap_tool_result
from one_bpmn.processa_engine.agent_runtime.tool_bounds import (
	bound_tool_result,
	salvage_leaked_delimiters,
	validate_tool_arguments,
)
from one_bpmn.processa_engine.agent_runtime.llm_types import (
	CompletionResult,
	LLMTruncatedError,
	ToolCallRecord,
	TurnRecord,
)
from one_bpmn.agents.memory.loop_compaction import compact_transcript, has_turns_to_compact
from one_bpmn.agents.observability import SUB_CALL_TURN_FLAG, _tool_call_status, clear_tool_artifacts
from one_bpmn.agents.shape_tools import PAUSE_HELD_FLAG, BudgetExceeded, ToolDeferred
from one_bpmn.processa_engine.agent_runtime.turn_state import TURN_ANSWERED_FLAG
from one_bpmn.security.tool_policy import PolicyViolation


def _now_iso() -> str:
	return frappe.utils.now_datetime().isoformat(sep=" ", timespec="microseconds")


_SECOND_HUMAN_RESULT = (
	"A human task from this turn is already pending; only one human task can "
	"run at a time. Call this tool again after the pending human task completes."
)

_SECOND_PAUSE_RESULT = (
	"Another step from this turn is already waiting for its answer, and only one "
	"can be tracked at a time. Call this tool again once the pending one is back."
)

_FORCED_TOOL_NUDGE = "This step must call a tool. Call one of your tools now instead of answering in text."
_FORCED_TOOL_REFUSED = (
	"tool_choice is {0}, but the model answered in plain text twice instead of calling a tool."
)

_TURN_RECORD_FIELDS = {
	"role",
	"content",
	"tool_calls",
	"prompt_tokens",
	"completion_tokens",
	"cache_read_tokens",
	"cache_write_tokens",
	"latency_ms",
	"model_latency_ms",
	"turn_no",
	"started_at",
	"ended_at",
}

_EDIT_TOOLS = frozenset({"edit_file", "write_file", "apply_edits", "delete_file"})
_BUDGET_WARN_SHARE = 0.75


def _budget_note(turns_used: int, max_turns: int, trace: list) -> str:
	"""The turn count and edits made so far, and from the warn share onward an instruction to wrap up."""
	left = max_turns - turns_used
	names = (
		call["name"] if isinstance(call, dict) else call.name for turn in trace for call in turn.tool_calls
	)
	edits = sum(1 for name in names if name in _EDIT_TOOLS)
	note = f"[Run budget: turn {turns_used} of {max_turns}, {left} left, {edits} edit(s) made.]"
	if left <= 1:
		return (
			note
			+ " This is your last turn: search no more, save your work and report, or hand the item back with what you found."
		)
	if turns_used >= max_turns * _BUDGET_WARN_SHARE:
		return (
			note
			+ " Stop exploring. Use the turns left to test, save your work and report, or hand the item back with what you learned."
		)
	return note


@dataclass
class AgentSuspension:
	"""The loop stopped because the model called a human tool."""

	transcript: list = field(default_factory=list)
	pending_call: dict = field(default_factory=dict)
	deferred_results: list = field(default_factory=list)
	deferred_wait: dict = field(default_factory=dict)
	trace: list = field(default_factory=list)
	turns_used: int = 0
	prompt_tokens: int = 0
	completion_tokens: int = 0
	cache_read_tokens: int = 0
	cache_write_tokens: int = 0


async def run_agent_loop(
	adapter,
	*,
	system: str,
	user: str = "",
	tools: list,
	max_tokens: int = 16384,
	max_turns: int = 10,
	resume: dict | None = None,
	timeout_seconds: float | None = None,
	max_retries: int = 0,
	retry_backoff_ms: int = 1000,
	tool_result_max_chars: int | None = None,
	terminal_tools: list | None = None,
	on_tool_event=None,
	history: list | None = None,
	response_schema: dict | None = None,
	check_reply=None,
	tool_choice: str | None = None,
	parallel_tool_calls: bool = True,
	thinking_budget_tokens: int = 0,
	loop_compaction: dict | None = None,
	budget_check=None,
	budget_notes: bool = False,
	temperature: float | None = None,
	top_p: float | None = None,
) -> tuple:
	"""Drive the tool loop. Returns (CompletionResult, None) when the model produces a final answer or hits
	the turn cap, or (None, AgentSuspension) when it selects a human tool."""
	tool_map = {t.name: t for t in (tools or [])}

	turns_used = 0
	trace: list = []
	if resume:
		transcript = list(resume.get("transcript") or [])
		turns_used = int(resume.get("turns_used") or 0)
		# Carry the turns spent before the suspension so the reported total stays right.
		trace = [
			TurnRecord(**{k: v for k, v in t.items() if k in _TURN_RECORD_FIELDS})
			for t in (resume.get("trace") or [])
		]
		pending = resume.get("pending_call") or {}
		results = list(resume.get("deferred_results") or [])
		# A person's answer is outside content, so it is marked like any tool result.
		results.append(
			{
				"id": pending.get("id") or "",
				"name": pending.get("name") or "",
				"content": wrap_tool_result(
					bound_tool_result(resume.get("human_result") or "", tool_result_max_chars),
					pending.get("name") or "human task",
					pending.get("arguments"),
				),
			}
		)
		transcript.append({"role": "tool_results", "results": results})
	else:
		transcript = [*(history or []), {"role": "user", "content": user}]

	clear_tool_artifacts()

	try:
		return await _run_turns(
			adapter,
			system=system,
			tools=tools,
			tool_map=tool_map,
			transcript=transcript,
			trace=trace,
			turns_used=turns_used,
			max_tokens=max_tokens,
			max_turns=max_turns,
			timeout_seconds=timeout_seconds,
			max_retries=max_retries,
			retry_backoff_ms=retry_backoff_ms,
			tool_result_max_chars=tool_result_max_chars,
			terminal_tools=set(terminal_tools) if terminal_tools is not None else {"finalize"},
			on_tool_event=on_tool_event,
			response_schema=response_schema,
			check_reply=check_reply,
			tool_choice=tool_choice,
			controls=_step_controls(parallel_tool_calls, thinking_budget_tokens, temperature, top_p),
			loop_compaction=loop_compaction,
			budget_check=budget_check,
			budget_notes=budget_notes,
		)
	finally:
		# Reset at the top of every turn so neither flag outlives the turn that set it.
		frappe.flags[PAUSE_HELD_FLAG] = False
		frappe.flags[TURN_ANSWERED_FLAG] = False
		frappe.flags[SUB_CALL_TURN_FLAG] = None


async def run_nested_loop(
	adapter,
	*,
	system: str,
	user: str,
	tools: list | None,
	max_tokens: int,
	max_turns: int,
	temperature: float | None = None,
	top_p: float | None = None,
):
	"""complete()'s loop: the same turns, with no terminal tool, leaving the calling turn's state as it was."""
	saved = {
		flag: frappe.flags.get(flag) for flag in (PAUSE_HELD_FLAG, TURN_ANSWERED_FLAG, SUB_CALL_TURN_FLAG)
	}
	try:
		completion, _suspension = await _run_turns(
			adapter,
			system=system,
			tools=tools,
			tool_map={t.name: t for t in tools or []},
			transcript=[{"role": "user", "content": user}],
			trace=[],
			turns_used=0,
			max_tokens=max_tokens,
			max_turns=max_turns,
			terminal_tools=frozenset(),
			controls=_step_controls(True, 0, temperature, top_p),
		)
	finally:
		frappe.flags.update(saved)
	if completion.hit_turn_cap:
		completion.text = ""
	return completion


def _step_controls(
	parallel_tool_calls: bool,
	thinking_budget_tokens: int,
	temperature: float | None = None,
	top_p: float | None = None,
) -> dict:
	"""The per-call controls that differ from the provider default, so adapters without them still work."""
	controls = {}
	if not parallel_tool_calls:
		controls["parallel_tool_calls"] = False
	if thinking_budget_tokens:
		controls["thinking_budget_tokens"] = thinking_budget_tokens
	if temperature is not None:
		controls["temperature"] = temperature
	if top_p is not None:
		controls["top_p"] = top_p
	return controls


_PERMANENT_STATUSES = frozenset({400, 401, 403, 404, 413, 422})
MAX_BACKOFF_SECONDS = 30.0


def _status_of(exc) -> int | None:
	return getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)


def _retry_after_seconds(exc) -> float | None:
	"""The wait the provider asked for in its Retry-After header, capped, or None."""
	headers = getattr(getattr(exc, "response", None), "headers", None) or {}
	try:
		return min(float(headers.get("retry-after")), MAX_BACKOFF_SECONDS)
	except (TypeError, ValueError):
		return None


async def _step_with_retries(
	adapter,
	system,
	transcript,
	tools,
	max_tokens,
	*,
	timeout_seconds=None,
	max_retries=0,
	retry_backoff_ms=1000,
	response_schema=None,
	controls=None,
):
	"""One turn's model call, bounded by timeout_seconds and retried up to max_retries times."""
	attempt = 0
	while True:
		try:
			extra = dict(controls or {})
			if response_schema:
				extra["response_schema"] = response_schema
			call = adapter.step(system, transcript, tools=tools or None, max_tokens=max_tokens, **extra)
			if timeout_seconds:
				return await asyncio.wait_for(call, timeout=timeout_seconds)
			return await call
		except LLMTruncatedError:
			raise
		except Exception as exc:
			if _status_of(exc) in _PERMANENT_STATUSES or attempt >= max_retries:
				raise
			wait = _retry_after_seconds(exc)
			if wait is None:
				wait = min((retry_backoff_ms / 1000.0) * (2**attempt), MAX_BACKOFF_SECONDS)
			await asyncio.sleep(wait + random.uniform(0, 0.1))
			attempt += 1


def _fire_tool_event(on_tool_event, phase, tool_name):
	"""Invoke the caller's tool-event callback, never letting it break the turn."""
	if on_tool_event is None:
		return
	try:
		on_tool_event(phase, tool_name)
	except Exception:
		frappe.log_error(
			title="step_loop on_tool_event callback failed",
			message=f"phase={phase} tool={tool_name}\n\n{frappe.get_traceback()}",
		)


async def _run_turns(
	adapter,
	*,
	system,
	tools,
	tool_map,
	transcript,
	trace,
	turns_used,
	max_tokens,
	max_turns,
	timeout_seconds=None,
	max_retries=0,
	retry_backoff_ms=1000,
	tool_result_max_chars=None,
	terminal_tools=frozenset({"finalize"}),
	on_tool_event=None,
	response_schema=None,
	check_reply=None,
	tool_choice=None,
	controls=None,
	loop_compaction=None,
	budget_check=None,
	budget_notes=False,
):
	"""The turn loop itself. Split out only so run_agent_loop can guarantee the pause flag is cleared however
	this returns."""
	reply_checked = False
	force_pending = bool(tool_choice) and tool_choice != "auto" and turns_used == 0
	nudged = False
	last_prompt_tokens = trace[-1].prompt_tokens if trace else 0
	compacted_at = None
	last_error = None
	while turns_used < max_turns:
		spent = budget_check(trace) if budget_check else ""
		if spent:
			return _stopped_at_budget(trace, spent), None
		# Reset at the top of every turn so neither flag outlives the turn that set it.
		frappe.flags[PAUSE_HELD_FLAG] = False
		frappe.flags[TURN_ANSWERED_FLAG] = False
		if (
			loop_compaction
			and last_prompt_tokens > loop_compaction["threshold"]
			and (compacted_at is None or turns_used - compacted_at >= loop_compaction["keep_turns"])
			and has_turns_to_compact(transcript, loop_compaction["keep_turns"])
		):
			compacted = compact_transcript(
				transcript,
				keep_turns=loop_compaction["keep_turns"],
				model=loop_compaction.get("model"),
				agent_model=loop_compaction["agent_model"],
				provider=loop_compaction.get("provider"),
			)
			compacted_at = turns_used
			if compacted is not None:
				transcript[:] = compacted
		_turn_t0 = time.perf_counter()
		_turn_started_at = _now_iso()
		step = await _step_with_retries(
			adapter,
			system,
			transcript,
			tools,
			max_tokens,
			timeout_seconds=timeout_seconds,
			max_retries=max_retries,
			retry_backoff_ms=retry_backoff_ms,
			response_schema=response_schema,
			controls={**(controls or {}), **({"tool_choice": tool_choice} if force_pending else {})},
		)
		_model_ms = int((time.perf_counter() - _turn_t0) * 1000)
		turns_used += 1
		last_prompt_tokens = step.prompt_tokens

		if not step.tool_calls:
			trace.append(
				TurnRecord(
					role="assistant",
					content=step.content,
					prompt_tokens=step.prompt_tokens,
					completion_tokens=step.completion_tokens,
					cache_read_tokens=getattr(step, "cache_read_tokens", 0) or 0,
					cache_write_tokens=getattr(step, "cache_write_tokens", 0) or 0,
					latency_ms=int((time.perf_counter() - _turn_t0) * 1000),
					model_latency_ms=_model_ms,
					turn_no=turns_used,
					started_at=_turn_started_at,
					ended_at=_now_iso(),
				)
			)
			if force_pending:
				if nudged:
					raise RuntimeError(_FORCED_TOOL_REFUSED.format(tool_choice))
				nudged = True
				if (step.content or "").strip():
					transcript.append({"role": "assistant", "content": step.content})
				transcript.append({"role": "user", "content": _FORCED_TOOL_NUDGE})
				continue
			reply_error = None if reply_checked or check_reply is None else check_reply(step.content)
			if reply_error:
				reply_checked = True
				transcript.append({"role": "assistant", "content": step.content})
				transcript.append({"role": "user", "content": reply_error})
				continue
			return CompletionResult(text=step.content, trace=trace, no_terminal_tool=True), None

		force_pending = False

		assistant_entry = {
			"role": "assistant",
			"content": step.content,
			"tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in step.tool_calls],
		}
		if getattr(step, "thinking", None):
			assistant_entry["thinking"] = step.thinking
		transcript.append(assistant_entry)

		turn_record = TurnRecord(
			role="tool",
			content=step.content,
			prompt_tokens=step.prompt_tokens,
			completion_tokens=step.completion_tokens,
			cache_read_tokens=getattr(step, "cache_read_tokens", 0) or 0,
			cache_write_tokens=getattr(step, "cache_write_tokens", 0) or 0,
			model_latency_ms=_model_ms,
			turn_no=turns_used,
			started_at=_turn_started_at,
		)
		frappe.flags[SUB_CALL_TURN_FLAG] = turns_used
		results = []
		pending_call = None
		deferred_wait: dict = {}
		terminal_reply = None
		budget_reason = ""
		repeated = ""
		for call in step.tool_calls:
			if budget_reason or repeated:
				break
			tool = tool_map.get(call.name)
			if tool is not None and tool.human:
				if pending_call is None:
					pending_call = {"id": call.id, "name": call.name, "arguments": call.arguments}
					frappe.flags[PAUSE_HELD_FLAG] = True
					continue
				result = _SECOND_HUMAN_RESULT
			elif tool is None:
				result = f"Unknown tool: {call.name}"
			else:
				call.arguments = salvage_leaked_delimiters(
					call.name, getattr(tool, "parameters", None), call.arguments
				)
				# Check the declared schema before the script runs, so the model repairs the call.
				_invalid = validate_tool_arguments(
					call.name,
					getattr(tool, "parameters", None),
					getattr(tool, "required", None),
					call.arguments,
				)
				if _invalid:
					turn_record.tool_calls.append(
						ToolCallRecord(name=call.name, arguments=call.arguments, result=_invalid)
					)
					repeated, last_error = _repeated_error(last_error, call.name, _invalid)
					results.append(
						{
							"id": call.id,
							"name": call.name,
							"content": wrap_tool_result(_invalid, call.name, call.arguments),
						}
					)
					continue
				_fire_tool_event(on_tool_event, "start", call.name)
				try:
					try:
						result = str(tool.fn(**call.arguments))
						if call.name in terminal_tools:
							_args = call.arguments if isinstance(call.arguments, dict) else {}
							# A terminal tool's response argument is the reply; without one, its raw arguments are.
							terminal_reply = _args.get("response", _args) if _args else result
					except ToolDeferred as deferred:
						if pending_call is None:
							pending_call = {"id": call.id, "name": call.name, "arguments": call.arguments}
							deferred_wait = deferred.marker or {}
							frappe.flags[PAUSE_HELD_FLAG] = True
							continue
						result = _SECOND_PAUSE_RESULT
					except BudgetExceeded as exceeded:
						result = f"Run stopped: {exceeded}"
						budget_reason = f"{exceeded} (in {call.name})"
					except PolicyViolation as violation:
						result = violation.decision.as_tool_result()
					except Exception as exc:
						result = f"Error calling {call.name}: {exc}"
				finally:
					_fire_tool_event(on_tool_event, "end", call.name)

			turn_record.tool_calls.append(
				ToolCallRecord(name=call.name, arguments=call.arguments, result=result)
			)
			repeated, last_error = _repeated_error(last_error, call.name, result)
			# Only the model's copy is marked and capped; the ToolCallRecord keeps the raw result.
			results.append(
				{
					"id": call.id,
					"name": call.name,
					"content": wrap_tool_result(
						bound_tool_result(result, tool_result_max_chars), call.name, call.arguments
					),
				}
			)

		turn_record.latency_ms = int((time.perf_counter() - _turn_t0) * 1000)
		turn_record.ended_at = _now_iso()
		trace.append(turn_record)

		if budget_reason:
			return _stopped_at_budget(trace, budget_reason), None
		if repeated:
			last_said = next((t.content for t in reversed(trace) if (t.content or "").strip()), "")
			return CompletionResult(
				text=last_said, trace=trace, no_terminal_tool=True, repeated_tool_error=repeated
			), None

		if pending_call is not None:
			from dataclasses import asdict

			return None, AgentSuspension(
				transcript=transcript,
				pending_call=pending_call,
				deferred_results=results,
				deferred_wait=deferred_wait,
				trace=[asdict(t) for t in trace],
				turns_used=turns_used,
				prompt_tokens=sum(t.prompt_tokens for t in trace),
				completion_tokens=sum(t.completion_tokens for t in trace),
				cache_read_tokens=sum(t.cache_read_tokens for t in trace),
				cache_write_tokens=sum(t.cache_write_tokens for t in trace),
			)

		# A terminal tool answered, so the turn ends on its words without another model call.
		if terminal_reply is not None:
			return CompletionResult(text=str(terminal_reply), trace=trace, no_terminal_tool=False), None

		if frappe.flags.get(TURN_ANSWERED_FLAG):
			frappe.flags[TURN_ANSWERED_FLAG] = False
			_said = next((t.content for t in reversed(trace) if (t.content or "").strip()), "")
			return CompletionResult(text=_said, trace=trace, no_terminal_tool=False), None

		if budget_notes and results:
			results[-1]["content"] += "\n\n" + _budget_note(turns_used, max_turns, trace)
		transcript.append({"role": "tool_results", "results": results})

	last_said = next((t.content for t in reversed(trace) if (t.content or "").strip()), "")
	return CompletionResult(text=last_said, trace=trace, hit_turn_cap=True, no_terminal_tool=True), None


def _stopped_at_budget(trace: list, reason: str) -> CompletionResult:
	last_said = next((t.content for t in reversed(trace) if (t.content or "").strip()), "")
	return CompletionResult(text=last_said, trace=trace, no_terminal_tool=True, budget_exceeded=reason)


def _repeated_error(last_error, name: str, result) -> tuple[str, tuple | None]:
	"""(why the run stops or "", the error to compare the next call against)."""
	error = (name, str(result)) if _tool_call_status(result) == "Error" else None
	if error and error == last_error:
		return f"{name} failed twice in a row with the same error: {str(result)[:300]}", error
	return "", error
