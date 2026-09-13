"""
Enqueued worker that distills an agent interaction and persists the resulting
durable facts.

Runs off the dispatch hot path (via ``frappe.enqueue``) so long-term memory
never adds latency to an AI Agent Task. Like the distiller it feeds, it never
raises — a background job must not surface failures into the workflow.
"""

from __future__ import annotations

import frappe


def _reconcile_batch(facts: list[dict], reconcile_ctx: dict) -> list[dict]:
	"""Reconcile facts extracted in ONE distill call against each other before any
	of them reach the store.

	``distill_memories`` already collapses same-``dedup_key`` facts within a call;
	the gap this closes is the SAME underlying fact extracted twice under
	different topic slugs in one call — per-fact reconciliation against the store
	(``memory_write``'s own reconcile path) never sees a fact's batch siblings, so
	both would otherwise be written.

	Sequential: keeps a running ``kept`` list and reconciles each subsequent fact
	against it using synthetic index ids (these facts have no AI Memory row yet,
	so "supersedes" here means "drop from this batch", never "invalidate a
	stored row"). Bounded to at most ``len(facts) - 1`` extra reconcile calls
	(distill.py caps a batch at 5 facts). Never raises — on any failure this
	returns the original, unreduced list rather than dropping facts.
	"""
	if len(facts) < 2:
		return facts

	from one_bpmn.agents.memory.reconcile import reconcile as _reconcile

	try:
		kept: list[dict] = [facts[0]]
		for fact in facts[1:]:
			candidates = [{"name": str(i), "content": k["content"]} for i, k in enumerate(kept)]
			decision = _reconcile(
				fact["content"],
				candidates,
				provider_name=reconcile_ctx.get("provider_name"),
				backend=reconcile_ctx.get("backend") or "direct_api",
				model=reconcile_ctx.get("model"),
			)
			degraded = decision.get("degraded")
			if degraded:
				frappe.log_error(
					title="AI Memory: batch reconciliation degraded",
					message=f"reason={degraded} topic={fact.get('topic')}",
				)
				try:
					frappe.cache().hincrby("ai_memory:reconcile_degraded", degraded, 1)
				except Exception:
					pass
			supersedes = {int(n) for n in decision.get("supersedes", []) if str(n).isdigit()}
			kept = [k for i, k in enumerate(kept) if i not in supersedes]
			kept.append(fact)
		return kept
	except Exception:
		frappe.log_error(title="AI Memory: batch reconciliation failed", message=frappe.get_traceback())
		return facts


def distill_and_write(
	*,
	agent_output,
	agent: str,
	scope: str,
	scope_key,
	provider_name: str,
	backend: str,
	model,
	source_run,
	reconcile_model=None,
	reconcile_provider=None,
	process_model=None,
	exclude_context: str | None = None,
) -> list[str]:
	"""Distill ``agent_output`` into durable facts and ``memory_write`` each one.

	Facts are reconciled twice before the store settles: first against each other
	within this batch (``_reconcile_batch``, catching the same fact re-extracted
	under two different topics in one call), then per-fact through write-time
	reconciliation (always on) — ``memory_write`` carries the distiller's
	``{agent}:{topic}`` ``dedup_key`` forward as a deterministic pre-filter, and
	for whatever isn't an exact duplicate, retrieves similar currently-valid
	memories in scope and lets the configured chat model decide add/update/
	replace, invalidating any superseded fact instead of deleting it (so history
	is kept via Frappe Versions). ``source_run`` records provenance and
	``metadata`` tags the fact as distilled. Returns the names of the written AI
	Memory records (for tests / observability).

	``model`` distills; ``reconcile_model`` decides add/update/replace, each
	against the provider that serves it. They are
	independent (WI-001793) so reconciliation can be tuned — usually upward —
	without paying for the stronger model on every extraction. Both are resolved
	on the dispatch thread and passed in as arguments; this runs in a background
	worker and must not look configuration up itself. ``reconcile_model`` defaults
	to ``model``, which is the behaviour that predates the split.

	``exclude_context`` (WI-002165) is the dispatch-thread system prompt plus
	injected memory block, passed straight through to ``distill_memories`` so
	it can reject facts that just restate what the agent was told rather than
	something it learned.
	"""
	try:
		from one_bpmn.agents.memory.distill import distill_memories
		from one_bpmn.agents.memory.tools import memory_write

		facts = distill_memories(
			agent_output,
			agent=agent,
			scope=scope,
			scope_key=scope_key,
			provider_name=provider_name,
			backend=backend,
			model=model,
			exclude_context=exclude_context,
		)
		# The reconciler runs on its own model, so the two can be tuned apart —
		# and therefore on its own provider, because a model only works against
		# the credentials that serve it. Defaults to distillation's provider,
		# which is right whenever both models come from the same place.
		# Resolved on the dispatch thread and passed in: this worker must not
		# look configuration up itself.
		reconcile_ctx = {
			"provider_name": reconcile_provider or provider_name,
			"backend": backend,
			"model": reconcile_model or model,
		}
		facts = _reconcile_batch(facts, reconcile_ctx)
		written: list[str] = []
		for f in facts:
			rec = memory_write(
				scope,
				scope_key,
				f["content"],
				dedup_key=f["dedup_key"],
				# "agent" is enough on its own: for Agent scope it duplicates
				# agent_element (the scope key itself), and "learned_from" only
				# ever duplicated "agent" -- dropped rather than kept alongside it.
				metadata={
					"topic": f["topic"],
					"agent": agent,
					"distilled": True,
				},
				source_run=source_run,
				importance=f.get("importance"),
				source_type=f.get("source_type"),
				ignore_permissions=True,
				reconcile=True,
				reconcile_ctx=reconcile_ctx,
				process_model=process_model,
			)
			written.append(rec.get("name"))
		return written
	except Exception:
		frappe.log_error(title="AI Memory: distill_and_write failed", message=frappe.get_traceback())
		return []
