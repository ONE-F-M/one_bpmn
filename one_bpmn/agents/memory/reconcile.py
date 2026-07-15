"""
Write-time memory reconciliation: decide whether a new fact is genuinely new,
or whether it updates/replaces one or more existing memories in the same scope.

This is the mechanism that keeps long-term memory coherent instead of drifting
into near-duplicates. Rather than a string ``dedup_key``, a candidate set of the
most similar *currently-valid* memories (retrieved by the existing scoped
keyword/full-text ``memory_search``) is handed to the configured chat model,
which returns a per-write decision — add / update / replace — plus the names of
the candidates it supersedes.

It uses ONLY the provider + chat model already configured for the task (the same
executor stack as :mod:`one_bpmn.agents.memory.distill`); there is no embedding
model and nothing hardcoded. Like the distiller, it NEVER raises: any failure
degrades to ``{"action": "add", "supersedes": []}`` so the writer just inserts
the new fact and touches nothing.
"""

from __future__ import annotations

import json

import frappe

# Bound how many candidates we hand the model (also bounds the retrieval).
_MAX_CANDIDATES = 8
# Bound the text we send so a huge fact/candidate can't blow up the call.
_MAX_CONTENT_LEN = 1000

_VALID_ACTIONS = ("add", "update", "replace")

_RECONCILE_SCHEMA = json.dumps(
	{
		"type": "object",
		"properties": {
			"action": {"type": "string", "enum": list(_VALID_ACTIONS)},
			"supersedes": {"type": "array", "items": {"type": "string"}},
		},
		"required": ["action", "supersedes"],
	}
)

_SYSTEM_PROMPT = """You reconcile a new long-term memory against existing memories \
for the same agent scope, so the memory store stays coherent instead of drifting \
into near-duplicates.

You are given a NEW fact and a numbered list of EXISTING memories (each with an id).
Decide how the new fact relates to the existing ones and return JSON:

- "add"     — the new fact is genuinely new; it does not duplicate or contradict
              any existing memory. "supersedes" MUST be [].
- "update"  — the new fact refines, extends, or restates the SAME underlying fact
              as one or more existing memories (even if worded differently or filed
              under a different topic). Put their ids in "supersedes".
- "replace" — the new fact CONTRADICTS one or more existing memories; the new fact
              is the current truth. Put the contradicted ids in "supersedes".

Only list an id in "supersedes" when the new fact truly makes it stale — same fact
(update) or contradicted fact (replace). Unrelated memories are never superseded.
When unsure, prefer "add" with an empty "supersedes"."""

_USER_TEMPLATE = """NEW fact:
---
{new}
---
EXISTING memories:
{candidates}
---
Return the reconciliation decision as JSON."""


def _coerce_decision(output) -> dict:
	"""Parse the model output into a safe decision dict. Tolerates a parsed dict
	(response_format='json') or a raw JSON string; anything else -> safe 'add'."""
	if isinstance(output, dict):
		data = output
	elif isinstance(output, str):
		try:
			data = json.loads(output)
		except (ValueError, TypeError):
			return {"action": "add", "supersedes": []}
	else:
		return {"action": "add", "supersedes": []}

	action = data.get("action") if isinstance(data, dict) else None
	if action not in _VALID_ACTIONS:
		return {"action": "add", "supersedes": []}

	supersedes = data.get("supersedes")
	names = [str(n) for n in supersedes if n] if isinstance(supersedes, list) else []
	# "add" never supersedes anything, regardless of what the model returned.
	if action == "add":
		names = []
	return {"action": action, "supersedes": names}


def reconcile(
	new_content: str,
	candidates: list[dict],
	*,
	provider_name: str,
	backend: str = "direct_api",
	model: str | None = None,
) -> dict:
	"""Decide add/update/replace for ``new_content`` against ``candidates``.

	``candidates`` is the ``[{name, content, ...}]`` list returned by
	``memory_search`` — only currently-valid, in-scope memories. Returns
	``{"action": "add"|"update"|"replace", "supersedes": [candidate_name, ...]}``
	where ``supersedes`` only ever contains ids present in ``candidates``.

	Never raises. With no candidates, no model, or any failure it returns the
	safe default ``{"action": "add", "supersedes": []}`` so the caller simply
	inserts the new fact.
	"""
	safe = {"action": "add", "supersedes": []}

	text = (new_content or "").strip()
	if not text or not candidates or not model:
		return safe

	# Map presentation ids back to real names so a hallucinated/foreign id can
	# never invalidate the wrong record. We show real names too (they are opaque
	# hashes) but validate strictly against this set.
	by_name = {}
	lines = []
	for c in candidates[:_MAX_CANDIDATES]:
		name = c.get("name")
		content = str(c.get("content") or "").strip()[:_MAX_CONTENT_LEN]
		if not name or not content:
			continue
		by_name[name] = True
		lines.append(f"- id={name}: {content}")
	if not lines:
		return safe

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
			system_prompt=_SYSTEM_PROMPT,
			user_prompt=_USER_TEMPLATE.format(
				new=text[:_MAX_CONTENT_LEN], candidates="\n".join(lines)
			),
			temperature=0.0,
			max_tokens=500,
			response_format="json",
			response_schema=_RECONCILE_SCHEMA,
		)
		result = get_executor(config.backend)().run(config, ExecutorContext())
		if result.error_code != ErrorCode.SUCCESS:
			return safe
		decision = _coerce_decision(result.output)
	except Exception:
		frappe.log_error(title="AI Memory: reconciliation failed", message=frappe.get_traceback())
		return safe

	# Drop any superseded id the model invented or that isn't a real candidate.
	decision["supersedes"] = [n for n in decision["supersedes"] if n in by_name]
	if not decision["supersedes"] and decision["action"] != "add":
		# update/replace with nothing to supersede is effectively an add.
		decision["action"] = "add"
	return decision
