"""
Memory distillation: turn one agent interaction into 0..N durable, reusable
facts that are worth remembering — gated by salience.

This is what makes long-term memory *genuine*. Instead of storing the agent's
full user-facing reply verbatim (confirmations, restated requests, clarifying
questions, apologies), a cheap LLM extracts only generalizable rules,
preferences, constraints, or learned patterns — or returns nothing.

The approach mirrors the ingestion-time extraction step used by Mem0, LangMem,
and CrewAI's TaskEvaluator: decide *what* is worth keeping when the memory is
written, not when it is read. Every fact gets a deterministic ``{agent}:{topic}``
``dedup_key`` (below); ``memory_write`` uses it as a pre-filter ahead of semantic
reconciliation (update-vs-insert against similar existing memories) so an exact
restatement is caught even if the reconciler's model call fails.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

import frappe

_MAX_FACTS = 5
_DEFAULT_IMPORTANCE = 3


class DistillationFailed(Exception):
	"""The call did not work, as opposed to producing nothing worth keeping.

	Only raised when the caller asks for it (``raise_on_failure``). Without this
	the two outcomes were the same empty list, so a broken model looked exactly
	like a quiet conversation and nothing was ever retried.
	"""
_MAX_CONTENT_LEN = 1000
# Bound the input we hand the curator so a huge reply can't blow up the call.
_MAX_INPUT_LEN = 6000
# Bound the exclusion context (system prompt + injected memory block) handed to
# the curator — same rationale as _MAX_INPUT_LEN, applied to the other side of
# the prompt.
_MAX_EXCLUDE_LEN = 3000

# A fact is rejected as an echo once some sentence of it matches some sentence
# of the exclusion context at or above this ratio (SequenceMatcher, 0-1).
# Deliberately conservative — a backstop for the clear cases, not a substitute
# for the curator prompt's own judgment. Tuned against the confirmed echo rows
# in cleanup_ai_memory_store.py: jrrd68247k (a loose paraphrase of
# harden_logix_pipeline_driver.NEW_USER_PROMPT) scores ~0.91; a genuine
# domain-relevant fact that merely shares vocabulary with an unrelated prompt
# section (e.g. "Use exclusive gateways for yes/no decisions." against
# ProsAlly's gateway rules) scores ~0.49-0.54 — comfortably below this. A
# lower threshold would catch more paraphrases (some confirmed echoes score in
# the 0.5s) at the cost of flagging genuine facts; the prompt instruction is
# the first line of defense for those, this is only the backstop.
_ECHO_SIMILARITY_THRESHOLD = 0.65
# Chunks of the exclusion context shorter than this carry too little signal
# to compare against (a lone heading or bullet marker) and would either never
# match or match everything.
_ECHO_CHUNK_MIN_CHARS = 20

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
						"importance": {"type": "integer", "minimum": 1, "maximum": 5},
						"source_type": {"type": "string", "enum": ["User Statement", "Agent Inference", "Tool Output"]},
					},
					"required": ["content", "topic", "importance", "source_type"],
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
- anything already present, even paraphrased, in the agent's own instructions
  or recalled memory context shown below — that is the agent being told
  something, not the agent learning something

For each qualifying fact give a short lowercase "topic" (2-4 words), concise
"content" (one or two generalized sentences — no instance-specific IDs or names),
and an "importance" from 1 to 5: 5 for a rule that changes what the agent must
do on most future runs (a hard constraint, a standing instruction from the
user), 3 for a useful preference or pattern, 1 for a minor detail that rarely
matters. Most facts are 2 or 3.
Give each fact a "source_type": "User Statement" when the fact is something the
user said, asked for or decided; "Tool Output" when it is read off data a tool
or system returned; otherwise "Agent Inference" (the agent's own conclusion).
If nothing qualifies, return {{"memories": []}}. Prefer returning nothing over
storing noise."""

_USER_PROMPT = """The agent just produced this output:
---
{output}
---
Extract durable memories as JSON."""

_EXCLUDE_SUFFIX = """

The agent's own instructions and recalled memory context for this run were:
---
{exclude_context}
---
Do not extract anything above that merely restates this — only extract what
the agent said or did beyond it."""


def _slug(text: str) -> str:
	s = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
	return s or "note"


def _normalise(text: str) -> str:
	"""Whitespace- and case-insensitive form, so re-indentation or a capital
	letter doesn't hide a paraphrase."""
	return " ".join((text or "").split()).lower()


def _sentences(text: str) -> list[str]:
	"""Split into normalised, comparably-sized chunks for pairwise matching.

	Sentence-level on both sides of the comparison, not whole-content-against-
	chunk: comparing a multi-sentence fact against one short prompt line dilutes
	SequenceMatcher's ratio through sheer length mismatch and misses real
	echoes. Chunks shorter than ``_ECHO_CHUNK_MIN_CHARS`` (a heading, a bullet
	marker) are dropped — too little signal to compare meaningfully.
	"""
	out = []
	for chunk in re.split(r"(?<=[.!?])\s+|[\n;]+", text or ""):
		candidate = _normalise(chunk)
		if len(candidate) >= _ECHO_CHUNK_MIN_CHARS:
			out.append(candidate)
	return out


def _is_echo(content: str, exclude_context: str) -> bool:
	"""True when *content* is substantially the same text as some sentence of
	*exclude_context* (the agent's own system prompt / injected memory block) —
	an instruction or recalled fact echoed back, not something the agent learned.

	Verbatim containment first (cheap, catches an exact or near-exact copy);
	otherwise the best sentence-vs-sentence similarity ratio, since the curator
	LLM paraphrases rather than quotes (WI-002165 — jrrd68247k's "Always call
	classify_intent first..." is a loose rewrite of the driving prompt, not a
	substring of it).
	"""
	if not content or not exclude_context:
		return False
	needle = _normalise(content)
	haystack = _normalise(exclude_context)
	if len(needle) >= _ECHO_CHUNK_MIN_CHARS and needle in haystack:
		return True
	content_sentences = _sentences(content) or [needle]
	context_sentences = _sentences(exclude_context)
	for cs in content_sentences:
		for hs in context_sentences:
			if SequenceMatcher(None, cs, hs).ratio() >= _ECHO_SIMILARITY_THRESHOLD:
				return True
	return False


def _source_type(value) -> str:
	"""One of the three source types; anything else is an agent inference."""
	return value if value in ("User Statement", "Agent Inference", "Tool Output") else "Agent Inference"


def _importance(value) -> int:
	"""Clamp the curator's importance to 1..5; anything unusable is the default."""
	try:
		return min(5, max(1, int(value)))
	except (TypeError, ValueError):
		return _DEFAULT_IMPORTANCE


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
	exclude_context: str | None = None,
	raise_on_failure: bool = False,
) -> list[dict]:
	"""Extract 0..N durable facts from one interaction.

	Returns a list of ``{content, topic, dedup_key, importance, source_type}``; ``[]`` when nothing is
	worth remembering. Never raises — any failure yields ``[]`` so the caller
	(dispatcher / background job) is never blocked.

	``scope``/``scope_key``/``conversation`` are accepted for forward
	compatibility with semantic consolidation; v1 uses only ``agent`` to
	namespace the dedup key.

	``exclude_context`` (WI-002165) is the agent's own system prompt plus its
	injected memory block for this run. The curator is told not to extract
	anything already present there, and every returned fact is additionally
	checked against it with ``_is_echo`` — a deterministic backstop, since the
	prompt instruction alone left confirmed echo rows in the store (see
	cleanup_ai_memory_store.py). Passing nothing here (the previous behaviour)
	just skips both checks.

	``raise_on_failure`` exists because "nothing was worth remembering" and "the
	call did not work" both came back as ``[]``, so a caller could not tell a
	quiet turn from a broken model and had nothing to retry. Left ``False`` the
	contract is unchanged and this never raises. The writeback passes ``True``
	so it can retry, and record what it gave up on.
	"""
	text = agent_output if isinstance(agent_output, str) else str(agent_output or "")
	if not text.strip():
		return []

	# No hardcoded fallback model: distillation runs with the model the caller
	# resolved (the task's aiModel or an explicit aiMemoryDistillModel). Without
	# one there is nothing valid to call, so skip — visibly.
	if not model:
		if raise_on_failure:
			raise DistillationFailed("no model configured; pass the task's aiModel or set aiMemoryDistillModel")
		frappe.log_error(
			title="AI Memory: distillation skipped (no model configured)",
			message=f"agent={agent} scope={scope} — pass the task's aiModel or set aiMemoryDistillModel.",
		)
		return []

	exclude_text = str(exclude_context or "").strip()[:_MAX_EXCLUDE_LEN]
	user_prompt = _USER_PROMPT.format(output=text[:_MAX_INPUT_LEN])
	if exclude_text:
		user_prompt += _EXCLUDE_SUFFIX.format(exclude_context=exclude_text)

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
			user_prompt=user_prompt,
			temperature=0.0,
			max_tokens=800,
			response_format="json",
			response_schema=_DISTILL_SCHEMA,
		)
		result = get_executor(config.backend)().run(config, ExecutorContext())
		if result.error_code != ErrorCode.SUCCESS:
			if raise_on_failure:
				# .value, not the enum: this string is the Error field on an AI
				# Memory Dead Letter, which somebody reads. On prod-backup it
				# read "the model returned ErrorCode.PROVIDER_DISABLED".
				code = getattr(result.error_code, "value", result.error_code)
				raise DistillationFailed(f"the model returned {code}: {getattr(result, 'error_message', '')}")
			return []
		raw = _coerce_memories(result.output)
	except DistillationFailed:
		raise
	except Exception:
		if raise_on_failure:
			raise
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
		if exclude_text and _is_echo(content, exclude_text):
			frappe.logger("one_bpmn").info(
				f"AI Memory: distillation rejected echo — agent={agent} "
				f"content={content[:120]!r}"
			)
			continue
		topic = _slug(m.get("topic") or content[:40])
		dedup_key = f"{agent}:{topic}"
		if dedup_key in seen:
			continue
		seen.add(dedup_key)
		facts.append(
			{
				"content": content,
				"topic": topic,
				"dedup_key": dedup_key,
				"importance": _importance(m.get("importance")),
				"source_type": _source_type(m.get("source_type")),
			}
		)
	return facts
