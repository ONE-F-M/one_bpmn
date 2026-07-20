# Copyright (c) 2026, one-fm and contributors
# Tests for the memory tools: search scope isolation / keyword / empty results,
# write insert + dedup overwrite, and JSON-Schema validity of the registry.

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

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
