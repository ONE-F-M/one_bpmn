"""
Enqueued worker that distills an agent interaction and persists the resulting
durable facts.

Runs off the dispatch hot path (via ``frappe.enqueue``) so long-term memory
never adds latency to an AI Agent Task. Like the distiller it feeds, it never
raises — a background job must not surface failures into the workflow.
"""

from __future__ import annotations

import frappe


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
) -> list[str]:
	"""Distill ``agent_output`` into durable facts and ``memory_write`` each one.

	Each fact is written through write-time reconciliation (always on): rather than
	overwriting by the old ``{agent}:{topic}`` dedup_key, ``memory_write`` retrieves
	similar currently-valid memories in scope, lets the configured chat model decide
	add/update/replace, and invalidates any superseded fact instead of deleting it
	(so history is kept via Frappe Versions). ``source_run`` records provenance and
	``metadata`` tags the fact as distilled. Returns the names of the written AI
	Memory records (for tests / observability).

	``model`` distills; ``reconcile_model`` decides add/update/replace. They are
	independent (WI-001793) so reconciliation can be tuned — usually upward —
	without paying for the stronger model on every extraction. Both are resolved
	on the dispatch thread and passed in as arguments; this runs in a background
	worker and must not look configuration up itself. ``reconcile_model`` defaults
	to ``model``, which is the behaviour that predates the split.
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
		)
		# The reconciler runs on the same provider/backend as distillation — the
		# credentials are the task's — but on its own model, so the two can be
		# tuned apart. No embedding model, nothing hardcoded.
		reconcile_ctx = {
			"provider_name": provider_name,
			"backend": backend,
			"model": reconcile_model or model,
		}
		written: list[str] = []
		for f in facts:
			rec = memory_write(
				scope,
				scope_key,
				f["content"],
				dedup_key=f["dedup_key"],
				metadata={
					"topic": f["topic"],
					"learned_from": agent,
					"agent": agent,
					"distilled": True,
				},
				source_run=source_run,
				ignore_permissions=True,
			)
			written.append(rec.get("name"))
		return written
	except Exception:
		frappe.log_error(title="AI Memory: distill_and_write failed", message=frappe.get_traceback())
		return []
