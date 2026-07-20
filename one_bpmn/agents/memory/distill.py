"""
Memory distillation: turn one agent interaction into 0..N durable, reusable
facts that are worth remembering — gated by salience.

This is what makes long-term memory *genuine*. Instead of storing the agent's
full user-facing reply verbatim (confirmations, restated requests, clarifying
questions, apologies), a cheap LLM extracts only generalizable rules,
preferences, constraints, or learned patterns — or returns nothing.

The approach mirrors the ingestion-time extraction step used by Mem0, LangMem,
and CrewAI's TaskEvaluator: decide *what* is worth keeping when the memory is
written, not when it is read. Semantic consolidation (update-vs-insert against
similar existing memories) is deferred to a later story; v1 dedups on a
deterministic ``{agent}:{topic}`` key so re-runs overwrite instead of pile up
(the shape of the curated memories already in the store).
"""

from __future__ import annotations

import json
import re

import frappe

_MAX_FACTS = 5
_MAX_CONTENT_LEN = 1000
# Bound the input we hand the curator so a huge reply can't blow up the call.
_MAX_INPUT_LEN = 6000

_DISTILL_SCHEMA = json.dumps(
	{
		"type": "object",
		"properties": {
			"memories": {
				"type": "array",
				"items": {
					"type": "object",
					"properties": {
						"content": {"type": "string"},
						"topic": {"type": "string"},
					},
					"required": ["content", "topic"],
				},
			},
		},
		"required": ["memories"],
	}
)

_SYSTEM_PROMPT = """You are the memory curator for an AI agent named "{agent}".
From the agent's latest output, extract ONLY durable facts worth recalling on
FUTURE, DIFFERENT runs of this agent.

A good memory is a general, reusable rule, preference, constraint, or learned
pattern — something that would still be true and useful next week on an
unrelated request.

Do NOT store (return nothing for) any of the following:
- confirmations or summaries of work just completed ("created successfully", "done")
- restatements of the user's request or the agent's plan
- clarifying questions or requests for more information
- apologies, error messages, or status updates
- details specific to a single one-off document or entity

For each qualifying fact give a short lowercase "topic" (2-4 words) and concise
"content" (one or two generalized sentences — no instance-specific IDs or names).
If nothing qualifies, return {{"memories": []}}. Prefer returning nothing over
storing noise."""

_USER_PROMPT = """The agent just produced this output:
---
{output}
---
Extract durable memories as JSON."""


def _slug(text: str) -> str:
	s = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
	return s or "note"


def _coerce_memories(output) -> list:
	"""The executor returns a parsed dict for response_format='json', but tolerate
	a raw JSON string too. Anything else yields no memories."""
	if isinstance(output, dict):
		data = output
	elif isinstance(output, str):
		try:
			data = json.loads(output)
		except (ValueError, TypeError):
			return []
	else:
		return []
	mems = data.get("memories") if isinstance(data, dict) else None
	return mems if isinstance(mems, list) else []


def distill_memories(
	agent_output,
	*,
	agent: str,
	scope: str,
	scope_key,
	provider_name: str,
	backend: str = "direct_api",
	model: str | None = None,
	conversation=None,
) -> list[dict]:
	"""Extract 0..N durable facts from one interaction.

	Returns a list of ``{content, topic, dedup_key}``; ``[]`` when nothing is
	worth remembering. Never raises — any failure yields ``[]`` so the caller
	(dispatcher / background job) is never blocked.

	``scope``/``scope_key``/``conversation`` are accepted for forward
	compatibility with semantic consolidation; v1 uses only ``agent`` to
	namespace the dedup key.
	"""
	text = agent_output if isinstance(agent_output, str) else str(agent_output or "")
	if not text.strip():
		return []

	# No hardcoded fallback model: distillation runs with the model the caller
	# resolved (the task's aiModel or an explicit aiMemoryDistillModel). Without
	# one there is nothing valid to call, so skip — visibly.
	if not model:
		frappe.log_error(
			title="AI Memory: distillation skipped (no model configured)",
			message=f"agent={agent} scope={scope} — pass the task's aiModel or set aiMemoryDistillModel.",
		)
		return []

	try:
		from one_bpmn.agents.executor import (
			ErrorCode,
			ExecutorConfig,
			ExecutorContext,
			get_executor,
		)
		from one_bpmn.agents.executor.direct_api import DirectApiExecutor  # noqa: F401

		config = ExecutorConfig(
			backend=backend or "direct_api",
			provider_name=provider_name,
			model=model,
			system_prompt=_SYSTEM_PROMPT.format(agent=agent),
			user_prompt=_USER_PROMPT.format(output=text[:_MAX_INPUT_LEN]),
			temperature=0.0,
			max_tokens=800,
			response_format="json",
			response_schema=_DISTILL_SCHEMA,
		)
		result = get_executor(config.backend)().run(config, ExecutorContext())
		if result.error_code != ErrorCode.SUCCESS:
			return []
		raw = _coerce_memories(result.output)
	except Exception:
		frappe.log_error(title="AI Memory: distillation failed", message=frappe.get_traceback())
		return []

	facts: list[dict] = []
	seen: set[str] = set()
	for m in raw[:_MAX_FACTS]:
		if not isinstance(m, dict):
			continue
		content = str(m.get("content") or "").strip()[:_MAX_CONTENT_LEN]
		if not content:
			continue
		topic = _slug(m.get("topic") or content[:40])
		dedup_key = f"{agent}:{topic}"
		if dedup_key in seen:
			continue
		seen.add(dedup_key)
		facts.append({"content": content, "topic": topic, "dedup_key": dedup_key})
	return facts
