# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Compaction inside one tool loop: older turns become a progress note on the task message.

The step loop calls compact_transcript when a model call's prompt passes the agent's threshold. The note
carries a summary plus the files read and edited. Only the transcript sent to the model changes; the
recorded trace is untouched. The summary call is recorded as a sub-call step of the run.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

from one_bpmn.agents.memory.compaction import _provider_for_model, resolve_compaction_model, summary_call

LOOP_SUMMARY_PROMPT = """You are compacting the earlier turns of an agent's tool loop so they can be
dropped from its context while it keeps working on the same task.

Keep: what was found, decisions made and why, what was changed, errors met and how they were
resolved, and which parts of the task are done and which are still left to do. Drop file contents
and tool output; a list of the files read and edited is kept separately. If an earlier summary is provided, fold it in and return one summary.

Write plain prose, at most a third of the length of the turns."""

# A tool result is rendered for the summariser at this length; the files list carries the rest.
_RESULT_CHARS = 800
_ARGUMENT_CHARS = 300
_TASK_CHARS = 4000
_MAX_INPUT_CHARS = 60000
_SUMMARY_TOKENS = 1500


def has_turns_to_compact(transcript: list, keep_turns: int) -> bool:
	"""True when the transcript holds more tool turns than ``keep_turns``."""
	return len(_tool_turns(transcript)) > keep_turns


def compact_transcript(
	transcript: list, *, keep_turns: int, model: str | None, agent_model: str, provider: str | None
) -> list | None:
	"""The transcript with turns older than the last ``keep_turns`` replaced, or None when nothing was compacted."""
	turns = _tool_turns(transcript)
	if len(turns) <= keep_turns:
		return None
	start, cut = turns[0], turns[-keep_turns]
	prefix = [_without_progress(e) for e in transcript[:start]]
	task_at = max(i for i, e in enumerate(prefix) if e.get("role") == "user")
	previous = transcript[task_at].get("compaction") or {}
	middle = transcript[start:cut]

	model = resolve_compaction_model(model, fallback=agent_model)
	started = time.perf_counter()
	task = prefix[task_at].get("content") or ""
	result = summary_call(
		f"Task: {task[:_TASK_CHARS]}\n\nTurns:\n{_render(middle)}",
		previous.get("summary") or "",
		model=model,
		provider_name=_provider_for_model(model, provider),
		backend="direct_api",
		max_tokens=_SUMMARY_TOKENS,
		system_prompt=LOOP_SUMMARY_PROMPT,
		max_input_chars=_MAX_INPUT_CHARS,
	)
	summary = str(result.output or "").strip() if result else ""
	if not summary:
		return None
	_record(model, result, summary, int((time.perf_counter() - started) * 1000))

	read, edited = _files(middle, previous)
	prefix[task_at] = {
		**prefix[task_at],
		"content": (
			f"{task}\n\nProgress so far (the earlier turns were removed to save context):\n{summary}\n\n"
			f"Files read: {', '.join(read) or 'none'}\nFiles edited: {', '.join(edited) or 'none'}"
		),
		"compaction": {"task": task, "summary": summary, "read": read, "edited": edited},
	}
	return [*prefix, *transcript[cut:]]


def _tool_turns(transcript: list) -> list:
	return [
		i
		for i, entry in enumerate(transcript)
		if entry.get("role") == "assistant" and entry.get("tool_calls")
	]


def _without_progress(entry: dict) -> dict:
	"""A task entry as it was before an earlier compaction added its progress note."""
	if not entry.get("compaction"):
		return entry
	return {key: value for key, value in entry.items() if key != "compaction"} | {
		"content": entry["compaction"]["task"]
	}


def _render(entries: list) -> str:
	lines = []
	for entry in entries:
		role = entry.get("role")
		if role == "assistant":
			if entry.get("content"):
				lines.append(f"Assistant: {entry['content']}")
			for call in entry.get("tool_calls") or []:
				arguments = json.dumps(call.get("arguments") or {}, default=str)[:_ARGUMENT_CHARS]
				lines.append(f"Called {call.get('name')}({arguments})")
		elif role == "tool_results":
			for result in entry.get("results") or []:
				lines.append(
					f"Result of {result.get('name')}: {str(result.get('content') or '')[:_RESULT_CHARS]}"
				)
		elif entry.get("content"):
			lines.append(f"User: {entry['content']}")
	return "\n".join(lines)


def _files(entries: list, previous: dict) -> tuple[list, list]:
	"""Paths passed to reading and to editing tools, added to those an earlier compaction listed."""
	read, edited = list(previous.get("read") or []), list(previous.get("edited") or [])
	for entry in entries:
		for call in entry.get("tool_calls") or []:
			path = (call.get("arguments") or {}).get("path")
			name = call.get("name") or ""
			if not isinstance(path, str) or not path:
				continue
			target = (
				edited
				if any(word in name for word in ("edit", "write", "delete"))
				else read
				if "read" in name
				else None
			)
			if target is not None and path not in target:
				target.append(path)
	return read, edited


def _record(model: str, result, summary: str, latency_ms: int) -> None:
	from one_bpmn.agents import observability

	usage = result.token_usage
	with observability.sub_call_scope(observability.current_run_name(), "compaction"):
		observability.record_sub_call(
			model,
			SimpleNamespace(
				text=summary,
				prompt_tokens=getattr(usage, "prompt_tokens", 0),
				completion_tokens=getattr(usage, "completion_tokens", 0),
				cache_read_tokens=getattr(usage, "cache_read_tokens", 0),
				cache_write_tokens=getattr(usage, "cache_write_tokens", 0),
			),
			latency_ms=latency_ms,
		)
