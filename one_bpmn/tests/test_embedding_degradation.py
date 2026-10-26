# A site whose embeddings stop working used to say so only in a log line that
# production never writes: frappe.logger sits at ERROR unless DEV_SERVER is set.
# These cover the record that replaces it.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.llm_provider import embedding as E
from one_bpmn.agents.memory import tools as T

TITLE = "AI Memory: embedding unavailable, keyword search only"


def _logs(title: str) -> int:
	return frappe.db.count("Error Log", {"method": title})


class TestDegradationIsRecorded(FrappeTestCase):
	def setUp(self):
		E._reported.clear()
		for title in (TITLE, "AI Memory: embedding could not be stored"):
			frappe.cache.delete_value(f"one_bpmn:memory_degraded:{title}")

	def test_an_embedding_that_cannot_be_produced_reaches_the_error_log(self):
		before = _logs(TITLE)
		with patch.object(E, "_vectors", side_effect=RuntimeError("no fastembed")):
			self.assertIsNone(E.embed(["anything"]))
		self.assertEqual(_logs(TITLE), before + 1)

	def test_the_same_failure_again_does_not_fill_the_log(self):
		"""A backfill meets the same broken model on every row it walks."""
		with patch.object(E, "_vectors", side_effect=RuntimeError("no fastembed")):
			E.embed(["one"])
			before = _logs(TITLE)
			for _ in range(5):
				E.embed(["another"])
		self.assertEqual(_logs(TITLE), before)

	def test_switching_semantic_search_off_is_not_a_failure(self):
		"""Disabled is somebody's decision, not something to report."""
		before = _logs(TITLE)
		with patch.object(E, "model_name", return_value=E.SEMANTIC_DISABLED):
			self.assertIsNone(E.embed(["anything"]))
		self.assertEqual(_logs(TITLE), before)

	def test_a_row_whose_vector_will_not_store_is_named_in_the_message(self):
		title = "AI Memory: embedding could not be stored"
		before = _logs(title)
		real_sql = frappe.db.sql

		def only_the_update_fails(query, *args, **kwargs):
			# Everything else, the Error Log insert included, still has to work.
			if "VEC_FromText" in str(query):
				raise RuntimeError("no VEC_FromText on this MariaDB")
			return real_sql(query, *args, **kwargs)

		with (
			patch.object(T, "_vector_supported", return_value=True),
			patch.object(E, "embed", return_value=[[0.1, 0.2]]),
			patch.object(frappe.db, "sql", side_effect=only_the_update_fails),
		):
			self.assertFalse(T.store_embedding("mem0001", "content"))
		self.assertEqual(_logs(title), before + 1)
		error = frappe.get_last_doc("Error Log", filters={"method": title})
		self.assertIn("mem0001", error.error)

	def test_reporting_never_raises_over_the_thing_it_reports(self):
		with patch.object(frappe, "log_error", side_effect=RuntimeError("Error Log is full")):
			E.report_degraded(TITLE, "detail")
