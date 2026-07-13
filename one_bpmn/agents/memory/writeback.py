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
) -> list[str]:
	"""Distill ``agent_output`` into durable facts and ``memory_write`` each one.

	Each fact is stored with a deterministic ``dedup_key`` (so re-runs overwrite),
	``source_run`` provenance, and ``metadata`` tagging it as distilled — the same
	shape as the curated memories already in the store. Returns the names of the
	written AI Memory records (for tests / observability).
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
