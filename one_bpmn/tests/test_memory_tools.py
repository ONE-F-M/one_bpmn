# Copyright (c) 2026, one-fm and contributors
# Tests for the memory tools: search scope isolation / keyword / empty results,
# write insert + dedup overwrite, and JSON-Schema validity of the registry.

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.agents.memory import tools as T


# Seed under unique scope keys so each test is hermetic regardless of any
# other AI Memory rows already in the table.
def _seed_agent_memories():
	agent = f"A_{frappe.generate_hash(length=8)}"
	other = f"B_{frappe.generate_hash(length=8)}"
	T.memory_write("Agent", agent, "customer prefers net-30 terms", ignore_permissions=True)
	T.memory_write("Agent", agent, "ship via DHL", ignore_permissions=True)
	T.memory_write("Agent", other, "net-30 for a different agent", ignore_permissions=True)
	return agent, other


class TestMemorySearch(FrappeTestCase):
	def test_scope_isolation_and_keyword(self):
		agent, _ = _seed_agent_memories()
		res = T.memory_search("Agent", agent, "net-30", ignore_permissions=True)
		# only the in-scope, keyword-matching memory — not "ship via DHL"
		# (no keyword) and not the other agent's "net-30" memory (scope isolation)
		self.assertEqual(len(res), 1)
		self.assertEqual(res[0]["content"], "customer prefers net-30 terms")

	def test_empty_results(self):
		agent, _ = _seed_agent_memories()
		self.assertEqual(T.memory_search("Agent", agent, "zzzznomatch", ignore_permissions=True), [])

	def test_result_shape(self):
		agent, _ = _seed_agent_memories()
		row = T.memory_search("Agent", agent, "", ignore_permissions=True)[0]
		self.assertEqual(set(row), {"name", "content", "metadata"})


class TestQueryTokenizer(FrappeTestCase):
	def test_stopwords_and_short_tokens_dropped(self):
		# "the"/"with" are stopwords; "of"/"a" are below the min length; only the
		# content words survive so a whole prompt no longer matches everything.
		toks = [t.lower() for t in T._query_tokens("Please create the invoice with a lot of items")]
		self.assertNotIn("the", toks)
		self.assertNotIn("with", toks)
		self.assertNotIn("of", toks)
		self.assertNotIn("please", toks)
		self.assertIn("invoice", toks)
		self.assertIn("items", toks)

	def test_distinct_tokens_only(self):
		self.assertEqual(T._query_tokens("invoice invoice invoice"), ["invoice"])


class TestFulltextPath(FrappeTestCase):
	def test_trusted_search_returns_only_in_scope(self):
		# Exercises the relevance (FULLTEXT) path; it must never leak another
		# scope key regardless of which path (fulltext or like) actually serves.
		agent, other = _seed_agent_memories()
		res = T.memory_search("Agent", agent, "net-30 terms", ignore_permissions=True)
		self.assertTrue(all(r["content"] != "net-30 for a different agent" for r in res))
		self.assertIn("customer prefers net-30 terms", [r["content"] for r in res])


class TestMemoryWrite(FrappeTestCase):
	def test_insert_and_dedup_overwrite(self):
		agent = f"D_{frappe.generate_hash(length=8)}"
		d1 = T.memory_write("Agent", agent, "v1", dedup_key="k", metadata={"a": 1}, ignore_permissions=True)
		d2 = T.memory_write("Agent", agent, "v2", dedup_key="k", metadata={"a": 2}, ignore_permissions=True)
		# in-place overwrite: same record, latest content/metadata
		self.assertEqual(d1["name"], d2["name"])
		self.assertEqual(frappe.db.count("AI Memory", {"agent_element": agent, "dedup_key": "k"}), 1)
		self.assertEqual(frappe.get_doc("AI Memory", d1["name"]).content, "v2")
		self.assertEqual(d2["metadata"], {"a": 2})

	def test_insert_without_dedup_key(self):
		agent = f"D_{frappe.generate_hash(length=8)}"
		n1 = T.memory_write("Agent", agent, "x", ignore_permissions=True)
		n2 = T.memory_write("Agent", agent, "y", ignore_permissions=True)
		self.assertNotEqual(n1["name"], n2["name"])
		self.assertEqual(frappe.db.count("AI Memory", {"agent_element": agent}), 2)

	def test_dedup_overwrite_updates_in_place_no_delete(self):
		# memory_write's own dedup_key lookup (as opposed to the AI Memory
		# controller's separate _dedup_overwrite, exercised at the doctype level
		# in test_ai_memory_doctype.py) finds the existing row and calls
		# doc.save() on it — never a delete, so there is nothing to audit here;
		# the row that comes back is the SAME row, just updated in place.
		agent = f"D_{frappe.generate_hash(length=8)}"
		d1 = T.memory_write("Agent", agent, "v1", dedup_key="k2", ignore_permissions=True)
		d2 = T.memory_write("Agent", agent, "v2", dedup_key="k2", ignore_permissions=True)
		self.assertEqual(d1["name"], d2["name"])
		self.assertTrue(frappe.db.exists("AI Memory", d1["name"]))
		self.assertEqual(frappe.db.get_value("AI Memory", d1["name"], "content"), "v2")

	def test_agent_scope_carries_optional_process_model(self):
		# process_model is provenance on an Agent-scoped row, not a scope key —
		# writing it must not disturb the agent_element key it's actually looked
		# up by.
		pm = frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"title": f"Test PM {frappe.generate_hash(length=6)}",
				"process_id": frappe.generate_hash(length=6),
				"version": 1,
			}
		)
		pm.insert(ignore_permissions=True)
		agent = f"D_{frappe.generate_hash(length=8)}"
		rec = T.memory_write("Agent", agent, "learned a fact", process_model=pm.name, ignore_permissions=True)
		doc = frappe.get_doc("AI Memory", rec["name"])
		self.assertEqual(doc.agent_element, agent)
		self.assertEqual(doc.process_model, pm.name)

	def test_content_round_trips_without_html_entity_escaping(self):
		# Regression: a row was observed live with "&lt;PROJECT&gt;" stored
		# verbatim instead of "<PROJECT>". memory_write/the AI Memory Long Text
		# field must not introduce or preserve escaping of its own — whatever
		# content is handed to it comes back out unchanged.
		agent = f"D_{frappe.generate_hash(length=8)}"
		content = "Use the pattern <PROJECT>-<YEAR>-<SEQ> for document names."
		rec = T.memory_write("Agent", agent, content, ignore_permissions=True)
		self.assertEqual(rec["content"], content)
		self.assertEqual(frappe.db.get_value("AI Memory", rec["name"], "content"), content)


class TestMemoryWriteUserDirected(FrappeTestCase):
	def test_user_directed_flag_defaults_false(self):
		agent = f"U_{frappe.generate_hash(length=8)}"
		rec = T.memory_write("Agent", agent, "some agent-produced fact", ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("AI Memory", rec["name"], "user_directed"), 0)

	def test_user_directed_flag_set_on_insert(self):
		agent = f"U_{frappe.generate_hash(length=8)}"
		rec = T.memory_write(
			"Agent", agent, "remember that every form needs a Site link field",
			ignore_permissions=True, user_directed=True,
		)
		self.assertEqual(frappe.db.get_value("AI Memory", rec["name"], "user_directed"), 1)

	def test_user_directed_flag_set_on_dedup_overwrite(self):
		agent = f"U_{frappe.generate_hash(length=8)}"
		d1 = T.memory_write("Agent", agent, "v1", dedup_key="k", ignore_permissions=True)
		d2 = T.memory_write(
			"Agent", agent, "v2", dedup_key="k", ignore_permissions=True, user_directed=True,
		)
		self.assertEqual(d1["name"], d2["name"])
		self.assertEqual(frappe.db.get_value("AI Memory", d1["name"], "user_directed"), 1)


class TestValidOnlySearch(FrappeTestCase):
	def test_expired_memory_is_hidden(self):
		agent = f"E_{frappe.generate_hash(length=8)}"
		valid = T.memory_write("Agent", agent, "quarterly report is due friday", ignore_permissions=True)
		expired = T.memory_write("Agent", agent, "quarterly report is due monday", ignore_permissions=True)
		# Mark one memory as superseded/expired (expires_on in the past).
		frappe.db.set_value("AI Memory", expired["name"], "expires_on", add_to_date(now_datetime(), days=-1))

		res = T.memory_search("Agent", agent, "quarterly report", ignore_permissions=True)
		names = [r["name"] for r in res]
		self.assertIn(valid["name"], names)
		self.assertNotIn(expired["name"], names)

	def test_future_expiry_stays_visible(self):
		agent = f"E_{frappe.generate_hash(length=8)}"
		rec = T.memory_write("Agent", agent, "annual audit checklist", ignore_permissions=True)
		frappe.db.set_value("AI Memory", rec["name"], "expires_on", add_to_date(now_datetime(), days=30))
		res = T.memory_search("Agent", agent, "annual audit", ignore_permissions=True)
		self.assertIn(rec["name"], [r["name"] for r in res])


class TestMemoryListUserDirected(FrappeTestCase):
	def test_returns_only_user_directed_in_scope(self):
		agent = f"V_{frappe.generate_hash(length=8)}"
		other = f"V_{frappe.generate_hash(length=8)}"
		directed = T.memory_write(
			"Agent", agent, "remember: always cc compliance on GRD emails",
			ignore_permissions=True, user_directed=True,
		)
		T.memory_write("Agent", agent, "an incidental fact from a run", ignore_permissions=True)
		T.memory_write(
			"Agent", other, "remember: a different agent's convention",
			ignore_permissions=True, user_directed=True,
		)

		res = T.memory_list_user_directed("Agent", agent, ignore_permissions=True)
		names = [r["name"] for r in res]
		self.assertEqual(names, [directed["name"]])

	def test_no_keyword_required(self):
		# The whole point: recall is unconditional, unlike memory_search, which
		# needs the query to share vocabulary with stored content.
		agent = f"V_{frappe.generate_hash(length=8)}"
		directed = T.memory_write(
			"Agent", agent, "always include a Site link field on every form we build",
			ignore_permissions=True, user_directed=True,
		)
		res = T.memory_list_user_directed("Agent", agent, ignore_permissions=True)
		self.assertEqual([r["name"] for r in res], [directed["name"]])

	def test_expired_user_directed_memory_is_hidden(self):
		agent = f"V_{frappe.generate_hash(length=8)}"
		rec = T.memory_write(
			"Agent", agent, "superseded convention", ignore_permissions=True, user_directed=True,
		)
		frappe.db.set_value("AI Memory", rec["name"], "expires_on", add_to_date(now_datetime(), days=-1))
		res = T.memory_list_user_directed("Agent", agent, ignore_permissions=True)
		self.assertNotIn(rec["name"], [r["name"] for r in res])


# A fake reconciler that supersedes whatever candidates it is handed, so the test
# doesn't depend on a live model. Patched in for `one_bpmn.agents.memory.reconcile.reconcile`.
def _fake_reconcile_replace(content, candidates, **kw):
	return {"action": "replace", "supersedes": [c["name"] for c in candidates], "degraded": None}


def _fake_reconcile_add(content, candidates, **kw):
	return {"action": "add", "supersedes": [], "degraded": None}


def _fake_reconcile_boom(content, candidates, **kw):
	raise RuntimeError("reconciler exploded")


# Mimics what the real reconcile() returns after catching its own internal
# failure (never raises) — distinct from _fake_reconcile_boom, which simulates a
# caller-side exception instead, so it never reaches reconcile()'s own "degraded"
# translation.
def _fake_reconcile_degraded(content, candidates, **kw):
	return {"action": "add", "supersedes": [], "degraded": "exec_error"}


class TestReconcileWrite(FrappeTestCase):
	_CTX = {"provider_name": "p", "backend": "direct_api", "model": "m"}

	def test_replace_invalidates_old_and_inserts_new(self):
		agent = f"R_{frappe.generate_hash(length=8)}"
		old = T.memory_write("Agent", agent, "customer prefers net-30 payment terms", ignore_permissions=True)

		with patch("one_bpmn.agents.memory.reconcile.reconcile", _fake_reconcile_replace):
			new = T.memory_write(
				"Agent", agent, "the customer now wants net-15 payment terms",
				ignore_permissions=True, reconcile=True, reconcile_ctx=self._CTX,
			)

		# Old memory is invalidated (expires_on set) but NOT deleted.
		self.assertTrue(frappe.db.exists("AI Memory", old["name"]))
		old_expiry = frappe.db.get_value("AI Memory", old["name"], "expires_on")
		self.assertIsNotNone(old_expiry)
		self.assertLessEqual(old_expiry, now_datetime())
		# New memory is inserted fresh, tagged with the reconcile action.
		self.assertNotEqual(new["name"], old["name"])
		self.assertEqual((new["metadata"] or {}).get("reconcile_action"), "replace")
		# Search returns only the current fact — the superseded one is gone.
		names = [r["name"] for r in T.memory_search("Agent", agent, "net payment terms", ignore_permissions=True)]
		self.assertIn(new["name"], names)
		self.assertNotIn(old["name"], names)
		# History preserved for free via Frappe Version (track_changes on AI Memory).
		self.assertTrue(frappe.get_all("Version", filters={"ref_doctype": "AI Memory", "docname": old["name"]}, limit=1))

	def test_add_keeps_both(self):
		agent = f"R_{frappe.generate_hash(length=8)}"
		old = T.memory_write("Agent", agent, "customer prefers net-30 payment terms", ignore_permissions=True)
		with patch("one_bpmn.agents.memory.reconcile.reconcile", _fake_reconcile_add):
			new = T.memory_write(
				"Agent", agent, "customer prefers payment via wire transfer",
				ignore_permissions=True, reconcile=True, reconcile_ctx=self._CTX,
			)
		# Nothing invalidated; both remain valid and searchable.
		self.assertIsNone(frappe.db.get_value("AI Memory", old["name"], "expires_on"))
		names = [r["name"] for r in T.memory_search("Agent", agent, "customer payment", ignore_permissions=True)]
		self.assertIn(old["name"], names)
		self.assertIn(new["name"], names)

	def test_reconciler_failure_degrades_to_plain_insert(self):
		agent = f"R_{frappe.generate_hash(length=8)}"
		old = T.memory_write("Agent", agent, "customer prefers net-30 payment terms", ignore_permissions=True)
		with patch("one_bpmn.agents.memory.reconcile.reconcile", _fake_reconcile_boom):
			# Must not raise; falls back to a plain insert. No dedup_key/exact
			# match exists here, so there's nothing for the deterministic
			# short-circuit to catch — this really is "unrelated fact, LLM
			# unavailable" and a plain insert is correct.
			new = T.memory_write(
				"Agent", agent, "customer wants net-15 payment terms",
				ignore_permissions=True, reconcile=True, reconcile_ctx=self._CTX,
			)
		self.assertTrue(frappe.db.exists("AI Memory", new["name"]))
		# Old memory untouched (not invalidated) because reconciliation blew up.
		self.assertIsNone(frappe.db.get_value("AI Memory", old["name"], "expires_on"))

	def test_exact_duplicate_blocked_even_when_reconciler_raises(self):
		# The one case that used to guarantee a duplicate: an exact restatement
		# under the same dedup_key must never insert again, even if the LLM call
		# itself blows up — the deterministic short-circuit means the LLM is
		# never reached for this decision at all.
		agent = f"R_{frappe.generate_hash(length=8)}"
		content = "the agent cannot see the conversation directly"
		old = T.memory_write(
			"Agent", agent, content, dedup_key="logix:convo",
			ignore_permissions=True, reconcile=True, reconcile_ctx=self._CTX,
		)
		with patch(
			"one_bpmn.agents.memory.reconcile.reconcile", side_effect=_fake_reconcile_boom
		) as mock_reconcile:
			dup = T.memory_write(
				"Agent", agent, content, dedup_key="logix:convo",
				ignore_permissions=True, reconcile=True, reconcile_ctx=self._CTX,
			)
		mock_reconcile.assert_not_called()
		self.assertEqual(old["name"], dup["name"])
		self.assertEqual(frappe.db.count("AI Memory", {"agent_element": agent, "dedup_key": "logix:convo"}), 1)

	def test_dedup_key_short_circuits_llm(self):
		agent = f"R_{frappe.generate_hash(length=8)}"
		content = "widgets ship via freight carrier alpha"
		first = T.memory_write(
			"Agent", agent, content, dedup_key="logix:shipping",
			ignore_permissions=True, reconcile=True, reconcile_ctx=self._CTX,
		)
		with patch("one_bpmn.agents.memory.reconcile.reconcile") as mock_reconcile:
			second = T.memory_write(
				"Agent", agent, content, dedup_key="logix:shipping",
				ignore_permissions=True, reconcile=True, reconcile_ctx=self._CTX,
			)
		mock_reconcile.assert_not_called()
		self.assertEqual(first["name"], second["name"])
		self.assertEqual(frappe.db.count("AI Memory", {"agent_element": agent, "dedup_key": "logix:shipping"}), 1)

	def test_candidates_include_same_dedup_key_outside_keyword_match(self):
		agent = f"R_{frappe.generate_hash(length=8)}"
		# Wording shares no keyword tokens with the new content below, so
		# memory_search's keyword/FULLTEXT path alone would never surface it —
		# only the shared dedup_key does.
		old = T.memory_write(
			"Agent", agent, "widgets ship via freight carrier alpha",
			dedup_key="logix:shipping", ignore_permissions=True,
		)
		seen = {}

		def _capture(content, candidates, **kw):
			seen["names"] = [c["name"] for c in candidates]
			return {"action": "add", "supersedes": [], "degraded": None}

		with patch("one_bpmn.agents.memory.reconcile.reconcile", _capture):
			T.memory_write(
				"Agent", agent, "gadgets are delivered by transport company beta",
				dedup_key="logix:shipping", ignore_permissions=True,
				reconcile=True, reconcile_ctx=self._CTX,
			)
		self.assertIn(old["name"], seen["names"])

	def test_degraded_reason_logged(self):
		agent = f"R_{frappe.generate_hash(length=8)}"
		T.memory_write("Agent", agent, "customer prefers net-30 payment terms", ignore_permissions=True)
		with patch("one_bpmn.agents.memory.reconcile.reconcile", _fake_reconcile_degraded), \
				patch("frappe.log_error") as mock_log_error:
			T.memory_write(
				"Agent", agent, "customer wants net-15 payment terms",
				ignore_permissions=True, reconcile=True, reconcile_ctx=self._CTX,
			)
		titles = [c.kwargs.get("title") for c in mock_log_error.call_args_list]
		self.assertIn("AI Memory: reconciliation degraded", titles)

	def test_reconcile_does_not_cross_scope(self):
		# The candidate a reconciler sees must never come from another scope key,
		# so a replace decision can only invalidate in-scope memories.
		agent = f"R_{frappe.generate_hash(length=8)}"
		other = f"R_{frappe.generate_hash(length=8)}"
		foreign = T.memory_write("Agent", other, "customer prefers net-30 payment terms", ignore_permissions=True)
		with patch("one_bpmn.agents.memory.reconcile.reconcile", _fake_reconcile_replace):
			T.memory_write(
				"Agent", agent, "customer prefers net-30 payment terms",
				ignore_permissions=True, reconcile=True, reconcile_ctx=self._CTX,
			)
		# The other agent's memory is untouched.
		self.assertIsNone(frappe.db.get_value("AI Memory", foreign["name"], "expires_on"))


class TestReconciler(FrappeTestCase):
	"""Unit-test one_bpmn.agents.memory.reconcile.reconcile in isolation, stubbing
	the executor so no live model is called."""

	def _run_with_executor_output(self, output, candidates):
		from one_bpmn.agents import executor as E
		from one_bpmn.agents.memory import reconcile as R

		class _Res:
			error_code = E.ErrorCode.SUCCESS

		_Res.output = output

		class _Exec:
			def run(self, cfg, ctx):
				return _Res()

		with patch("one_bpmn.agents.executor.get_executor", lambda backend: _Exec):
			return R.reconcile("new fact", candidates, provider_name="p", backend="direct_api", model="m")

	def test_safe_add_without_model(self):
		from one_bpmn.agents.memory import reconcile as R
		self.assertEqual(
			R.reconcile("f", [{"name": "X", "content": "c"}], provider_name="p", model=None),
			{"action": "add", "supersedes": [], "degraded": "no_model"},
		)

	def test_no_candidates_is_add(self):
		from one_bpmn.agents.memory import reconcile as R
		self.assertEqual(
			R.reconcile("f", [], provider_name="p", model="m"),
			{"action": "add", "supersedes": [], "degraded": "no_candidates"},
		)

	def test_foreign_supersede_ids_are_dropped(self):
		# The model returns a hallucinated id plus a real one; only the real
		# in-candidate id survives so a foreign record can never be invalidated.
		out = self._run_with_executor_output(
			{"action": "replace", "supersedes": ["GHOST", "REAL"]},
			[{"name": "REAL", "content": "c"}],
		)
		self.assertEqual(out, {"action": "replace", "supersedes": ["REAL"], "degraded": None})

	def test_update_with_no_real_supersede_becomes_add(self):
		out = self._run_with_executor_output(
			{"action": "update", "supersedes": ["GHOST"]},
			[{"name": "REAL", "content": "c"}],
		)
		self.assertEqual(out, {"action": "add", "supersedes": [], "degraded": None})


class TestMemoryToolRegistry(FrappeTestCase):
	def test_registry_definitions_are_valid_json_schema(self):
		self.assertEqual(set(T.MEMORY_TOOLS), {"memory_search", "memory_write"})
		try:
			from jsonschema import Draft7Validator
		except Exception:
			Draft7Validator = None
		for name, defn in T.MEMORY_TOOLS.items():
			self.assertLessEqual({"name", "description", "input_schema"}, set(defn))
			schema = defn["input_schema"]
			self.assertEqual(schema["type"], "object")
			self.assertIsInstance(schema["properties"], dict)
			self.assertIsInstance(schema["required"], list)
			json.dumps(schema)  # must be JSON-serialisable for provider payloads
			if Draft7Validator is not None:
				Draft7Validator.check_schema(schema)  # valid JSON Schema
			self.assertTrue(callable(defn["handler"]))


class TestSemanticSearch(FrappeTestCase):
	"""Hybrid semantic + FULLTEXT path. The live-model tests skip where the
	VECTOR column (MariaDB 11.7+) or the embedding model is unavailable; the
	fallback and blend tests run everywhere."""

	def _require_semantic(self):
		if not T._vector_supported():
			self.skipTest("AI Memory has no VECTOR column (MariaDB 11.7+ required)")
		from one_bpmn.agents.llm_provider import embedding

		if embedding.embed(["probe"]) is None:
			self.skipTest("embedding model unavailable")

	def test_wording_mismatch_is_found(self):
		self._require_semantic()
		agent = f"S_{frappe.generate_hash(length=8)}"
		T.memory_write("Agent", agent, "invoices need a VAT registration number before approval", ignore_permissions=True)
		T.memory_write("Agent", agent, "ship via DHL", ignore_permissions=True)
		res = T.memory_search("Agent", agent, "tax id on bills", ignore_permissions=True)
		# no shared keyword with either row: only the meaning match comes back
		self.assertEqual([r["content"] for r in res], ["invoices need a VAT registration number before approval"])

	def test_row_without_embedding_stays_findable(self):
		self._require_semantic()
		agent = f"S_{frappe.generate_hash(length=8)}"
		T.memory_write("Agent", agent, "customer prefers net-30 terms", ignore_permissions=True)
		with patch("one_bpmn.agents.llm_provider.embedding.embed", return_value=None):
			T.memory_write("Agent", agent, "warehouse closes at noon on Fridays", ignore_permissions=True)
		self.assertEqual(
			frappe.db.sql("select count(*) from `tabAI Memory` where agent_element=%s and embedding is null", agent)[0][0], 1
		)
		res = T.memory_search("Agent", agent, "warehouse Fridays", ignore_permissions=True)
		self.assertIn("warehouse closes at noon on Fridays", [r["content"] for r in res])

	def test_embedding_failure_falls_back_to_keyword(self):
		agent, _ = _seed_agent_memories()
		with patch("one_bpmn.agents.llm_provider.embedding.embed", side_effect=RuntimeError("model down")):
			res = T.memory_search("Agent", agent, "net-30", ignore_permissions=True)
		self.assertEqual([r["content"] for r in res], ["customer prefers net-30 terms"])

	def test_no_vector_column_uses_keyword_path(self):
		agent, _ = _seed_agent_memories()
		with patch.object(T, "_vector_supported", return_value=False):
			res = T.memory_search("Agent", agent, "net-30", ignore_permissions=True)
		self.assertEqual([r["content"] for r in res], ["customer prefers net-30 terms"])

	def test_blend_weight_extremes(self):
		semantic_only = {"name": "a", "_dist": 0.1, "_ft": 0.0}  # close in meaning, no keyword hit
		keyword_only = {"name": "b", "_dist": 0.9, "_ft": 5.0}  # keyword hit, far in meaning
		only_relevance = {"semantic": 1.0, "recency": 0.0, "importance": 0.0}
		self.assertEqual([r["name"] for r in T._blend([semantic_only, keyword_only], only_relevance)], ["a", "b"])
		only_relevance["semantic"] = 0.0
		self.assertEqual([r["name"] for r in T._blend([semantic_only, keyword_only], only_relevance)], ["b", "a"])

	def test_blend_drops_unrelated_rows(self):
		unrelated = {"name": "u", "_dist": 0.85, "_ft": 0.0}  # similarity 0.15, no keyword
		no_embedding_keyword_hit = {"name": "k", "_dist": None, "_ft": 2.0}
		self.assertEqual([r["name"] for r in T._blend([unrelated, no_embedding_keyword_hit], T._score_weights())], ["k"])

	def test_revisit_thresholds_recorded(self):
		self.assertEqual(T.REVISIT_SCOPE_ROWS, 10_000)
		self.assertEqual(T.REVISIT_TOTAL_ROWS, 500_000)


class TestMultiDimensionalScoring(FrappeTestCase):
	"""Relevance, recency and importance each change the ranking on their own.
	Rows are otherwise identical so one dimension decides."""

	NOW = now_datetime()

	@property
	def WEIGHTS(self):
		return {"semantic": 0.6, "recency": 0.2, "importance": 0.2}

	def _row(self, name, dist=0.3, ft=1.0, age_days=0, importance=3):
		return {
			"name": name,
			"_dist": dist,
			"_ft": ft,
			"modified": add_to_date(self.NOW, days=-age_days),
			"importance": importance,
		}

	def _order(self, rows):
		return [r["name"] for r in T._blend(rows, self.WEIGHTS, now=self.NOW)]

	def test_relevance_changes_ranking(self):
		closer = self._row("closer", dist=0.1)
		farther = self._row("farther", dist=0.5)
		self.assertEqual(self._order([farther, closer]), ["closer", "farther"])

	def test_recency_changes_ranking(self):
		fresh = self._row("fresh", age_days=0)
		old = self._row("old", age_days=90)
		self.assertEqual(self._order([old, fresh]), ["fresh", "old"])
		# with recency switched off the tie stands in input order
		no_recency = dict(self.WEIGHTS, recency=0.0)
		self.assertEqual([r["name"] for r in T._blend([old, fresh], no_recency, now=self.NOW)], ["old", "fresh"])

	def test_importance_changes_ranking(self):
		critical = self._row("critical", importance=5)
		minor = self._row("minor", importance=1)
		self.assertEqual(self._order([minor, critical]), ["critical", "minor"])

	def test_old_low_value_memory_does_not_outrank_fresh_critical_one(self):
		# The story's example: an old low-value memory that is slightly closer
		# in meaning still loses to a fresh critical one.
		old_minor = self._row("old_minor", dist=0.25, age_days=120, importance=1)
		fresh_critical = self._row("fresh_critical", dist=0.35, age_days=0, importance=5)
		self.assertEqual(self._order([old_minor, fresh_critical]), ["fresh_critical", "old_minor"])

	def test_recency_never_rescues_an_unrelated_memory(self):
		unrelated_fresh = self._row("u", dist=0.9, ft=0.0, age_days=0, importance=5)
		self.assertEqual(self._order([unrelated_fresh]), [])

	def test_recency_decay_half_life(self):
		self.assertAlmostEqual(T._recency(self.NOW, self.NOW), 1.0)
		self.assertAlmostEqual(T._recency(add_to_date(self.NOW, days=-30), self.NOW), 0.5, places=3)
		self.assertEqual(T._recency(None, self.NOW), 0.0)

	def test_weights_come_from_settings_and_relevance_takes_the_rest(self):
		frappe.db.set_single_value("Processa Settings", "memory_recency_weight", 0.3)
		frappe.db.set_single_value("Processa Settings", "memory_importance_weight", 0.1)
		w = T._score_weights()
		self.assertEqual((w["recency"], w["importance"]), (0.3, 0.1))
		# over-allocation is scaled back so relevance is never negative
		frappe.db.set_single_value("Processa Settings", "memory_recency_weight", 0.8)
		frappe.db.set_single_value("Processa Settings", "memory_importance_weight", 0.8)
		w = T._score_weights()
		self.assertAlmostEqual(w["recency"] + w["importance"], 1.0)

	def test_importance_persists_through_memory_write(self):
		agent = f"I_{frappe.generate_hash(length=8)}"
		rec = T.memory_write("Agent", agent, "always attach the signed PO", importance=5, ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("AI Memory", rec["name"], "importance"), 5)
		rec = T.memory_write("Agent", agent, "default currency is KWD", importance=9, ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("AI Memory", rec["name"], "importance"), 5)
		rec = T.memory_write("Agent", agent, "no importance given", ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("AI Memory", rec["name"], "importance"), 3)


class TestDistillerImportance(FrappeTestCase):
	def test_importance_is_clamped_with_a_default(self):
		from one_bpmn.agents.memory.distill import _importance

		self.assertEqual([_importance(v) for v in (5, "4", 0, 9, None, "high")], [5, 4, 1, 5, 3, 3])


def _decide(action, supersedes):
	def fake(new_content, candidates, **kwargs):
		names = [c["name"] for c in candidates][: len(supersedes)] if supersedes == "all" else supersedes
		return {"action": action, "supersedes": names, "degraded": None}

	return fake


_TRUST_CTX = {"provider_name": "p", "backend": "direct_api", "model": "m"}


class TestProvenanceTrust(FrappeTestCase):
	"""Source type, trust hierarchy, confidence and corroboration in memory_write."""

	@property
	def _CTX(self):
		return dict(_TRUST_CTX)

	def _write(self, agent, content, **kw):
		return T.memory_write("Agent", agent, content, ignore_permissions=True, **kw)

	def _row(self, name):
		return frappe.db.get_value(
			"AI Memory", name, ["source_type", "confidence", "corroboration_count", "last_corroborated", "expires_on"], as_dict=True
		)

	def test_defaults_follow_the_source_type(self):
		agent = f"P_{frappe.generate_hash(length=8)}"
		plain = self._row(self._write(agent, "agent worked this out")["name"])
		user = self._row(self._write(agent, "the user said so", user_directed=True)["name"])
		tool = self._row(self._write(agent, "a report returned this", source_type="Tool Output")["name"])
		self.assertEqual((plain.source_type, plain.confidence), ("Agent Inference", 0.6))
		self.assertEqual((user.source_type, user.confidence), ("User Statement", 0.9))
		self.assertEqual((tool.source_type, tool.confidence), ("Tool Output", 0.4))
		self.assertEqual(self._row(self._write(agent, "bad type", source_type="Rumour")["name"]).source_type, "Agent Inference")

	def test_user_statement_beats_tool_output_in_a_contradiction(self):
		agent = f"P_{frappe.generate_hash(length=8)}"
		stated = self._write(agent, "invoices are approved by the finance lead", user_directed=True)
		with patch("one_bpmn.agents.memory.reconcile.reconcile", _decide("replace", "all")):
			result = self._write(
				agent, "invoices are approved by the warehouse", source_type="Tool Output", reconcile=True, reconcile_ctx=self._CTX
			)
		# the standing memory is returned, still valid, and nothing new was written
		self.assertEqual(result["name"], stated["name"])
		self.assertIsNone(self._row(stated["name"]).expires_on)
		self.assertEqual(frappe.db.count("AI Memory", {"agent_element": agent}), 1)

	def test_user_statement_replaces_tool_output(self):
		agent = f"P_{frappe.generate_hash(length=8)}"
		inferred = self._write(agent, "invoices are approved by the warehouse", source_type="Tool Output")
		with patch("one_bpmn.agents.memory.reconcile.reconcile", _decide("replace", "all")):
			new = self._write(
				agent, "invoices are approved by the finance lead", user_directed=True, reconcile=True, reconcile_ctx=self._CTX
			)
		self.assertNotEqual(new["name"], inferred["name"])
		self.assertIsNotNone(self._row(inferred["name"]).expires_on)
		self.assertEqual((new["metadata"] or {}).get("reconcile_action"), "replace")

	def test_equal_trust_falls_back_to_effective_confidence(self):
		agent = f"P_{frappe.generate_hash(length=8)}"
		confident = self._write(agent, "the fiscal year starts in April", confidence=0.95)
		with patch("one_bpmn.agents.memory.reconcile.reconcile", _decide("replace", "all")):
			result = self._write(agent, "the fiscal year starts in January", confidence=0.5, reconcile=True, reconcile_ctx=self._CTX)
		self.assertEqual(result["name"], confident["name"])

	def test_restatement_corroborates(self):
		agent = f"P_{frappe.generate_hash(length=8)}"
		first = self._write(agent, "ship via DHL for exports")
		with patch("one_bpmn.agents.memory.reconcile.reconcile", _decide("update", "all")):
			second = self._write(agent, "exports always go by DHL", reconcile=True, reconcile_ctx=self._CTX)
		row = self._row(second["name"])
		self.assertEqual(row.corroboration_count, 1)
		self.assertIsNotNone(row.last_corroborated)
		self.assertAlmostEqual(row.confidence, 0.7, places=2)
		self.assertIsNotNone(self._row(first["name"]).expires_on)

	def test_confidence_decays_with_age(self):
		now = now_datetime()
		fresh = {"confidence": 0.8, "modified": now}
		aged = {"confidence": 0.8, "last_corroborated": add_to_date(now, days=-90)}
		self.assertAlmostEqual(T.effective_confidence(fresh, now), 0.8)
		self.assertAlmostEqual(T.effective_confidence(aged, now), 0.4, places=3)

	def test_trust_hierarchy_is_configurable(self):
		original = frappe.db.get_single_value("Processa Settings", "memory_trust_hierarchy")
		# set_single_value is not rolled back between tests in a class
		self.addCleanup(frappe.db.set_single_value, "Processa Settings", "memory_trust_hierarchy", original)
		frappe.db.set_single_value("Processa Settings", "memory_trust_hierarchy", None)
		self.assertEqual(T.trust_hierarchy(), ["User Statement", "Agent Inference", "Tool Output"])
		frappe.db.set_single_value("Processa Settings", "memory_trust_hierarchy", "Tool Output\nUser Statement")
		order = T.trust_hierarchy()
		self.assertEqual(order, ["Tool Output", "User Statement"])
		self.assertGreater(T._trust_rank("Tool Output", order), T._trust_rank("User Statement", order))
		self.assertEqual(T._trust_rank("Agent Inference", order), 0)


class TestDistillerSourceType(FrappeTestCase):
	def test_source_type_is_normalised(self):
		from one_bpmn.agents.memory.distill import _source_type

		self.assertEqual([_source_type(v) for v in ("User Statement", "Tool Output", "guess", None)],
			["User Statement", "Tool Output", "Agent Inference", "Agent Inference"])
