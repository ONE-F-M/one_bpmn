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


# A fake reconciler that supersedes whatever candidates it is handed, so the test
# doesn't depend on a live model. Patched in for `one_bpmn.agents.memory.reconcile.reconcile`.
def _fake_reconcile_replace(content, candidates, **kw):
	return {"action": "replace", "supersedes": [c["name"] for c in candidates]}


def _fake_reconcile_add(content, candidates, **kw):
	return {"action": "add", "supersedes": []}


def _fake_reconcile_boom(content, candidates, **kw):
	raise RuntimeError("reconciler exploded")


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
			# Must not raise; falls back to a plain insert.
			new = T.memory_write(
				"Agent", agent, "customer wants net-15 payment terms",
				ignore_permissions=True, reconcile=True, reconcile_ctx=self._CTX,
			)
		self.assertTrue(frappe.db.exists("AI Memory", new["name"]))
		# Old memory untouched (not invalidated) because reconciliation blew up.
		self.assertIsNone(frappe.db.get_value("AI Memory", old["name"], "expires_on"))

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
			{"action": "add", "supersedes": []},
		)

	def test_no_candidates_is_add(self):
		from one_bpmn.agents.memory import reconcile as R
		self.assertEqual(R.reconcile("f", [], provider_name="p", model="m"), {"action": "add", "supersedes": []})

	def test_foreign_supersede_ids_are_dropped(self):
		# The model returns a hallucinated id plus a real one; only the real
		# in-candidate id survives so a foreign record can never be invalidated.
		out = self._run_with_executor_output(
			{"action": "replace", "supersedes": ["GHOST", "REAL"]},
			[{"name": "REAL", "content": "c"}],
		)
		self.assertEqual(out, {"action": "replace", "supersedes": ["REAL"]})

	def test_update_with_no_real_supersede_becomes_add(self):
		out = self._run_with_executor_output(
			{"action": "update", "supersedes": ["GHOST"]},
			[{"name": "REAL", "content": "c"}],
		)
		self.assertEqual(out, {"action": "add", "supersedes": []})


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
