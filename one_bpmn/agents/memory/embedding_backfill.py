"""
Backfill embeddings onto AI Memory rows written before semantic retrieval
existed, so semantic search covers the whole corpus.

Idempotent and resumable by construction: the job only ever selects rows whose
``embedding`` is NULL and walks them in name order, so a re-run embeds what is
still missing and an interruption loses nothing but the batch in flight. A row
whose embedding cannot be produced is logged and skipped; it stays findable by
the keyword paths.

Runs as a background job (``enqueue_backfill``) so it never sits on a request.
``backfill_embeddings`` is also callable directly, for ``bench execute`` or a
patch.
"""

from __future__ import annotations

import frappe

from one_bpmn.agents.memory import tools

BATCH_SIZE = 200


def backfill_embeddings(batch_size: int = BATCH_SIZE) -> dict:
	"""Embed every AI Memory row without an embedding. Returns counts."""
	if not tools._vector_supported():
		frappe.logger("one_bpmn").info("AI Memory backfill skipped: no VECTOR column (MariaDB 11.7+ required).")
		return {"embedded": 0, "failed": 0, "skipped": "no vector column"}

	embedded = failed = 0
	last_name = ""
	while True:
		# Keyset pagination on name (the primary key), not OFFSET: rows that fail
		# keep a NULL embedding, so a plain "WHERE embedding IS NULL" loop would
		# revisit them forever.
		rows = frappe.db.sql(
			"""
			SELECT name, content FROM `tabAI Memory`
			WHERE embedding IS NULL AND name > %s
			ORDER BY name LIMIT %s
			""",
			(last_name, int(batch_size)),
			as_dict=True,
		)
		if not rows:
			break
		for row in rows:
			if tools.store_embedding(row["name"], row["content"] or ""):
				embedded += 1
			else:
				failed += 1
				frappe.logger("one_bpmn").warning(f"AI Memory backfill: no embedding produced for {row['name']}, left as is.")
		last_name = rows[-1]["name"]
		frappe.db.commit()

	frappe.logger("one_bpmn").info(f"AI Memory backfill: embedded={embedded} failed={failed}")
	return {"embedded": embedded, "failed": failed}


def enqueue_backfill() -> None:
	"""Queue the backfill on the long queue. Safe to call repeatedly."""
	frappe.enqueue(
		"one_bpmn.agents.memory.embedding_backfill.backfill_embeddings",
		queue="long",
		timeout=3600,
		job_id="ai_memory_embedding_backfill",
		deduplicate=True,
	)
