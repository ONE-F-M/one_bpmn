# Tests for the AI Memory embedding backfill: idempotent, resumable, and a row
# the model cannot embed is skipped instead of failing the batch.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.memory import embedding_backfill as B
from one_bpmn.agents.memory import tools as T


def _null_embedding_count(agent: str) -> int:
	return frappe.db.sql(
		"select count(*) from `tabAI Memory` where agent_element=%s and embedding is null", agent
	)[0][0]


class TestEmbeddingBackfill(FrappeTestCase):
	def setUp(self):
		if not T._vector_supported():
			self.skipTest("AI Memory has no VECTOR column (MariaDB 11.7+ required)")
		from one_bpmn.agents.llm_provider import embedding

		if embedding.embed(["probe"]) is None:
			self.skipTest("embedding model unavailable")
		# Rows written while the model is "down" land without an embedding, the
		# same state as rows written before the column existed.
		self.agent = f"BF_{frappe.generate_hash(length=8)}"
		with patch("one_bpmn.agents.llm_provider.embedding.embed", return_value=None):
			for text in ("net-30 terms", "ship via DHL", "invoices need a VAT number"):
				T.memory_write("Agent", self.agent, text, ignore_permissions=True)
		self.assertEqual(_null_embedding_count(self.agent), 3)
		# The job commits per batch; keep the test's rollback intact.
		p = patch("frappe.db.commit")
		p.start()
		self.addCleanup(p.stop)

	def test_embeds_missing_rows_and_second_run_does_nothing(self):
		first = B.backfill_embeddings(batch_size=2)
		self.assertEqual(_null_embedding_count(self.agent), 0)
		self.assertGreaterEqual(first["embedded"], 3)

		second = B.backfill_embeddings(batch_size=2)
		self.assertEqual(second, {"embedded": 0, "failed": 0})

	def test_row_that_cannot_embed_is_skipped_not_fatal(self):
		from one_bpmn.agents.llm_provider import embedding

		real = embedding._vectors

		def flaky(texts):
			if any("DHL" in t for t in texts):
				raise RuntimeError("model hiccup")
			return real(texts)

		with patch.object(embedding, "_vectors", side_effect=flaky):
			result = B.backfill_embeddings(batch_size=10)
		self.assertGreaterEqual(result["failed"], 1)
		self.assertEqual(_null_embedding_count(self.agent), 1)
		# the skipped row is still reachable by keyword
		res = T.memory_search("Agent", self.agent, "DHL", ignore_permissions=True)
		self.assertIn("ship via DHL", [r["content"] for r in res])

	def test_no_vector_column_exits_cleanly(self):
		with patch.object(T, "_vector_supported", return_value=False):
			self.assertEqual(B.backfill_embeddings()["embedded"], 0)
