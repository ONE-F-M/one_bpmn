# Copyright (c) 2026, one-fm and contributors
# Tests for writeback.distill_and_write: within-batch reconciliation
# (_reconcile_batch) and that a fact's dedup_key actually reaches memory_write
# instead of being discarded.

from __future__ import annotations

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.memory import writeback as W

_CTX = {"provider_name": "p", "backend": "direct_api", "model": "m"}


def _fake_reconcile_dup_of_first(content, candidates, **kw):
	# Whatever the new fact is, treat it as restating the first kept candidate.
	return {"action": "update", "supersedes": [candidates[0]["name"]], "degraded": None}


def _fake_reconcile_add(content, candidates, **kw):
	return {"action": "add", "supersedes": [], "degraded": None}


def _fake_reconcile_boom(content, candidates, **kw):
	raise RuntimeError("reconciler exploded")


class TestReconcileBatch(FrappeTestCase):
	def test_single_fact_is_a_noop(self):
		facts = [{"content": "c", "topic": "t", "dedup_key": "a:t"}]
		self.assertEqual(W._reconcile_batch(facts, _CTX), facts)

	def test_duplicate_fact_under_different_topic_is_dropped(self):
		# distill.py only collapses facts sharing the SAME dedup_key; two facts
		# restating one underlying fact under different topic slugs both survive
		# it and reach here — this is the gap _reconcile_batch closes.
		facts = [
			{"content": "the agent cannot see the conversation", "topic": "convo-a", "dedup_key": "a:convo-a"},
			{"content": "the agent cannot see the conversation itself", "topic": "convo-b", "dedup_key": "a:convo-b"},
		]
		with patch("one_bpmn.agents.memory.reconcile.reconcile", _fake_reconcile_dup_of_first):
			kept = W._reconcile_batch(facts, _CTX)
		self.assertEqual(len(kept), 1)
		# The later fact survives, carrying its own (not a merged) dedup_key.
		self.assertEqual(kept[0]["topic"], "convo-b")

	def test_genuinely_distinct_facts_all_kept(self):
		facts = [
			{"content": "fact one", "topic": "t1", "dedup_key": "a:t1"},
			{"content": "fact two", "topic": "t2", "dedup_key": "a:t2"},
		]
		with patch("one_bpmn.agents.memory.reconcile.reconcile", _fake_reconcile_add):
			kept = W._reconcile_batch(facts, _CTX)
		self.assertEqual(len(kept), 2)

	def test_failure_falls_back_to_unreduced_list(self):
		# Must never fail closed to zero writes: a blown-up batch reconcile call
		# degrades to "write everything the distiller returned", not "write
		# nothing".
		facts = [
			{"content": "fact one", "topic": "t1", "dedup_key": "a:t1"},
			{"content": "fact two", "topic": "t2", "dedup_key": "a:t2"},
		]
		with patch("one_bpmn.agents.memory.reconcile.reconcile", _fake_reconcile_boom):
			kept = W._reconcile_batch(facts, _CTX)
		self.assertEqual(kept, facts)


class TestDistillAndWrite(FrappeTestCase):
	def test_batch_duplicate_produces_one_write(self):
		facts = [
			{"content": "cannot see conversation v1", "topic": "convo-a", "dedup_key": "agentx:convo-a"},
			{"content": "cannot see conversation v2", "topic": "convo-b", "dedup_key": "agentx:convo-b"},
		]
		with patch("one_bpmn.agents.memory.distill.distill_memories", return_value=facts), \
				patch("one_bpmn.agents.memory.reconcile.reconcile", _fake_reconcile_dup_of_first), \
				patch("one_bpmn.agents.memory.tools.memory_write", return_value={"name": "M1"}) as mw:
			written = W.distill_and_write(
				agent_output="raw output",
				agent="agentx",
				scope="Agent",
				scope_key="agentx",
				provider_name="p",
				backend="direct_api",
				model="m",
				source_run="RUN-1",
			)
		mw.assert_called_once()
		self.assertEqual(mw.call_args.kwargs["dedup_key"], "agentx:convo-b")
		self.assertEqual(written, ["M1"])

	def test_dedup_key_is_forwarded_not_discarded(self):
		# Regression: writeback used to hardcode dedup_key=None at the
		# memory_write call site, throwing away exactly what distill.py computed.
		facts = [{"content": "single fact", "topic": "solo", "dedup_key": "agentx:solo"}]
		with patch("one_bpmn.agents.memory.distill.distill_memories", return_value=facts), \
				patch("one_bpmn.agents.memory.tools.memory_write", return_value={"name": "M1"}) as mw:
			W.distill_and_write(
				agent_output="raw output",
				agent="agentx",
				scope="Agent",
				scope_key="agentx",
				provider_name="p",
				backend="direct_api",
				model="m",
				source_run="RUN-1",
			)
		mw.assert_called_once()
		self.assertEqual(mw.call_args.kwargs["dedup_key"], "agentx:solo")
