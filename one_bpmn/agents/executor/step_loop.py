# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Step-driven (resumable) AI Agent tool loop — Durable AI Agent HITL, story 1.

one_bpmn drives the reasoning+tool loop turn-by-turn instead of delegating it
to the llm_provider adapter: each turn is ONE adapter.step() model call, the
loop executes the requested automatic tools inline and feeds their results
back, and — the reason this module exists — when the model selects a HUMAN
tool (ToolSpec.human) the loop STOPS and returns an AgentSuspension instead of
executing anything, so the engine can park the task, spawn the human step, and
resume later with the person's output.

Behaviour parity with the adapter-internal loop (complete()) is a hard
requirement for automatic-only runs: same turn cap semantics (aiMaxToolCalls,
counted across suspensions), same TurnRecord trace shape, same token
accounting, same error-string conventions for unknown/failing tools.

Everything in AgentSuspension is JSON-serializable — it IS the checkpoint
payload that gets persisted to the database (story 2).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time

from one_bpmn.agents.llm_provider.base import (
	CompletionResult,
	ToolCallRecord,
	ToolSpec,
	TurnRecord,
)
from one_bpmn.security.tool_policy import REQUIRE_HUMAN, PolicyViolation

# Tool result handed to the model when it requests a second human tool in the
# same turn — v1 supports one human pause at a time.
_SECOND_HUMAN_RESULT = (
	"A human task from this turn is already pending; only one human task can "
	"run at a time. Call this tool again after the pending human task completes."
)


# What counts as "yes" when a person releases a policy approval. Matched
# case-insensitively against the action they chose.
_APPROVAL_WORDS = {"approve", "approved", "yes", "allow", "accept", "ok", "proceed"}


def _resumed_result(pending: dict, human_result, tool_map: dict) -> str:
	"""The tool result to inject when a suspended turn resumes.

	Two different things arrive here and they must not be conflated:

	* a DESIGNER-MARKED human tool — the person IS the tool. Their answer is
	  the result and nothing executes.
	* a POLICY APPROVAL (WI-001645) — the tool was blocked before it ran and
	  the person is deciding whether it may. Approving has to actually CALL it;
	  handing the model the word "Approve" as the tool's output would be a
	  fabricated result, and the work the user authorised would never happen.
	"""
	policy = pending.get("policy")
	if not policy:
		return str(human_result or "")

	answer = human_result if isinstance(human_result, dict) else {}
	action = str(answer.get("action") or human_result or "").strip().lower()
	if action not in _APPROVAL_WORDS:
		note = str(answer.get("comment") or "").strip()
		return (
			f"A person reviewed this call and did not approve it{': ' + note if note else '.'} "
			"The action was not performed. Do not retry it."
		)

	name = pending.get("name") or ""
	tool = tool_map.get(name)
	if tool is None:
		return f"Unknown tool: {name}"
	try:
		# Approved: run the tool for real. Released through the policy module's
		# own one-shot grant rather than by reaching past the guard — the guard
		# is NOT the outermost wrapper (PII restoration sits above it), so
		# calling the inner function directly would hand the tool its redacted
		# arguments. The grant covers this one call and is consumed on use.
		from one_bpmn.security.tool_policy import approved_call

		with approved_call(name):
			return str(tool.fn(**(pending.get("arguments") or {})))
	except Exception as exc:
		return f"Error calling {name}: {exc}"


@dataclass
class AgentSuspension:
	"""The loop stopped because the model called a human tool.

	Every field is JSON-serializable so the whole object can be checkpointed
	to the database and reloaded after a restart (human steps are long-lived).

	transcript        — the provider-agnostic conversation so far, INCLUDING
	                    the assistant entry whose pending human call suspended
	                    us (see BaseLLMAdapter.step() for the entry shapes).
	pending_call      — {"id", "name", "arguments"} of the human tool call
	                    awaiting a person. Its result slot is unfilled.
	deferred_results  — results for the OTHER calls of the same turn (executed
	                    automatic tools, unknown-tool errors, extra human calls
	                    rejected with _SECOND_HUMAN_RESULT). On resume these
	                    plus the human result complete the turn's tool_results
	                    entry — wire formats require a result for EVERY call.
	trace             — list[dict] (TurnRecord shape) for THIS loop segment
	                    only; the dispatcher records it before suspending.
	turns_used        — model calls consumed so far, cumulative across
	                    suspensions. The turn cap is a total, not per-segment.
	prompt_tokens / completion_tokens — token totals for this segment.
	cache_read_tokens / cache_write_tokens — the part of prompt_tokens billed at
	                    the cache rates rather than the full input rate
	                    (WI-001643). Inclusive of prompt_tokens, not extra.
	"""
	transcript: list = field(default_factory=list)
	pending_call: dict = field(default_factory=dict)
	deferred_results: list = field(default_factory=list)
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
) -> tuple:
	"""Drive the tool loop. Returns (CompletionResult, None) when the model
	produces a final answer or hits the turn cap, or (None, AgentSuspension)
	when it selects a human tool.

	Fresh run: pass ``user`` (the rendered user prompt); the transcript starts
	as a single user entry.

	Resume: pass ``resume`` = {"transcript", "pending_call", "deferred_results",
	"turns_used", "human_result"} — the persisted AgentSuspension fields plus
	the human's output. The loop injects the human result as the pending
	call's tool result, completes the suspended turn, and continues.
	"""
	tool_map = {t.name: t for t in (tools or [])}

	turns_used = 0
	if resume:
		transcript = list(resume.get("transcript") or [])
		turns_used = int(resume.get("turns_used") or 0)
		pending = resume.get("pending_call") or {}
		results = list(resume.get("deferred_results") or [])
		results.append({
			"id": pending.get("id") or "",
			"name": pending.get("name") or "",
			"content": _resumed_result(pending, resume.get("human_result"), tool_map),
		})
		transcript.append({"role": "tool_results", "results": results})
	else:
		transcript = [{"role": "user", "content": user}]

	trace: list = []

	while turns_used < max_turns:
		_turn_t0 = time.perf_counter()
		step = await adapter.step(
			system, transcript, tools=tools or None, max_tokens=max_tokens
		)
		turns_used += 1

		# ── Final answer: no tool calls requested ─────────────────────────
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
				)
			)
			return CompletionResult(text=step.content, trace=trace), None

		# ── Record the assistant turn on the transcript ───────────────────
		transcript.append({
			"role": "assistant",
			"content": step.content,
			"tool_calls": [
				{"id": c.id, "name": c.name, "arguments": c.arguments}
				for c in step.tool_calls
			],
		})

		# ── Execute automatic calls; a human call suspends ────────────────
		turn_record = TurnRecord(
			role="tool",
			content=step.content,
			prompt_tokens=step.prompt_tokens,
			completion_tokens=step.completion_tokens,
			cache_read_tokens=getattr(step, "cache_read_tokens", 0) or 0,
			cache_write_tokens=getattr(step, "cache_write_tokens", 0) or 0,
		)
		results = []
		pending_call = None
		for call in step.tool_calls:
			tool = tool_map.get(call.name)
			if tool is not None and tool.human:
				if pending_call is None:
					# First human call of the turn: no result yet — the
					# person supplies it. Recorded on resume, not here.
					pending_call = {
						"id": call.id, "name": call.name, "arguments": call.arguments
					}
					continue
				result = _SECOND_HUMAN_RESULT
			elif tool is None:
				result = f"Unknown tool: {call.name}"
			else:
				try:
					result = str(tool.fn(**call.arguments))
				except PolicyViolation as violation:
					# WI-001645: the interceptor refused the call BEFORE the
					# tool ran. A rule asking for human approval reuses the
					# existing suspension path rather than a second mechanism:
					# the call becomes the turn's pending human decision.
					if violation.decision.outcome == REQUIRE_HUMAN and pending_call is None:
						# The ``policy`` block is what tells the engine this is an
						# APPROVAL, not a designer-marked human tool. The two are
						# not interchangeable: a human tool has a diagram shape
						# carrying its label, assignee and actions, and a policy
						# rule has none of that — without this the engine spawned
						# a task with no assignee and no actions that nobody could
						# ever complete. It also changes what resuming MEANS: a
						# human tool's answer replaces the call, an approval lets
						# the call proceed.
						pending_call = {
							"id": call.id, "name": call.name, "arguments": call.arguments,
							"policy": {
								"rule": violation.decision.rule,
								"reason": violation.decision.reason,
								"approver_user": violation.decision.approver_user,
								"approver_role": violation.decision.approver_role,
							},
						}
						continue
					result = violation.decision.as_tool_result()
				except Exception as exc:
					result = f"Error calling {call.name}: {exc}"

			turn_record.tool_calls.append(
				ToolCallRecord(name=call.name, arguments=call.arguments, result=result)
			)
			results.append({"id": call.id, "name": call.name, "content": result})

		turn_record.latency_ms = int((time.perf_counter() - _turn_t0) * 1000)
		trace.append(turn_record)

		if pending_call is not None:
			from dataclasses import asdict

			return None, AgentSuspension(
				transcript=transcript,
				pending_call=pending_call,
				deferred_results=results,
				trace=[asdict(t) for t in trace],
				turns_used=turns_used,
				prompt_tokens=sum(t.prompt_tokens for t in trace),
				completion_tokens=sum(t.completion_tokens for t in trace),
				cache_read_tokens=sum(t.cache_read_tokens for t in trace),
				cache_write_tokens=sum(t.cache_write_tokens for t in trace),
			)

		transcript.append({"role": "tool_results", "results": results})

	# Turn cap reached. Carry the model's last narration out as the text rather
	# than "": an empty string reaches a response_format="json" agent as
	# "invalid JSON at char 0", which reads as a model fault and says nothing
	# about the loop having run out of turns.
	last_said = next(
		(t.content for t in reversed(trace) if (t.content or "").strip()), ""
	)
	return CompletionResult(text=last_said, trace=trace, hit_turn_cap=True), None
