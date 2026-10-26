# Copyright (c) 2026, one-fm and contributors
"""Walking the A2A delegation chain to total a work item's AI spend.

The walk is capped, so the interesting cases are the ones where a wrong answer
still looks like a right one: a total that is short because the cap cut the
chain, and a complete total wrongly flagged as short. Both are covered here.

The chain is driven by patching the A2A Task query rather than inserting A2A
Task rows: inserting one starts the specialist's process for real, which would
make this suite issue live model calls.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.insights_api import _delegation_chain_instances


def _chain(edges: dict):
	"""Stand in for frappe.get_all over A2A Task, following *edges*."""
	real = frappe.get_all

	def fake(doctype, *args, **kwargs):
		if doctype != "A2A Task":
			return real(doctype, *args, **kwargs)
		callers = kwargs["filters"]["caller_instance"][1]
		return [
			frappe._dict({"instance": child})
			for caller in callers
			for child in edges.get(caller, [])
		]

	return patch.object(frappe, "get_all", fake)


class TestWorkItemDelegationCost(FrappeTestCase):
	def test_a_specialist_that_delegates_again_is_counted(self):
		with _chain({"root": ["a"], "a": ["b"]}):
			instances, truncated = _delegation_chain_instances(["root"])
		self.assertEqual(instances, ["root", "a", "b"])
		self.assertFalse(truncated)

	def test_a_chain_that_ends_exactly_at_the_cap_is_not_called_short(self):
		"""The frontier is still full at the last level, but nothing follows it
		— reporting this total as truncated would discredit a correct figure."""
		edges = {"root": ["a"], "a": ["b"], "b": ["c"], "c": ["d"]}
		with _chain(edges):
			instances, truncated = _delegation_chain_instances(["root"])
		self.assertEqual(instances, ["root", "a", "b", "c", "d"])
		self.assertFalse(truncated)

	def test_a_chain_past_the_cap_says_so(self):
		edges = {"root": ["a"], "a": ["b"], "b": ["c"], "c": ["d"], "d": ["e"]}
		with _chain(edges):
			instances, truncated = _delegation_chain_instances(["root"])
		self.assertNotIn("e", instances)
		self.assertTrue(truncated, "a total missing a level must not look complete")

	def test_a_cycle_terminates(self):
		with _chain({"root": ["a"], "a": ["b"], "b": ["root", "a"]}):
			instances, truncated = _delegation_chain_instances(["root"])
		self.assertEqual(instances, ["root", "a", "b"])
		self.assertFalse(truncated)

	def test_a_work_item_with_no_runs_is_not_an_error(self):
		from one_bpmn.api.insights_api import get_work_item_delegation_cost

		result = get_work_item_delegation_cost("WI-DOES-NOT-EXIST")
		self.assertEqual(
			result,
			{"total_cost": 0.0, "total_tokens": 0, "breakdown": [], "chain_truncated": False},
		)

	def test_the_totals_equal_the_breakdown(self):
		"""Whatever the walk finds, the headline figure has to be the sum of the
		rows offered as its explanation."""
		from one_bpmn.api.insights_api import get_work_item_delegation_cost

		instance = frappe.db.get_value(
			"BPMN Process Instance", {"context_doctype": "Work Item"}, ["name", "context_docname"], as_dict=True
		)
		if not instance:
			self.skipTest("no work item has a process instance on this site")

		result = get_work_item_delegation_cost(instance.context_docname)
		self.assertAlmostEqual(result["total_cost"], sum(r["cost"] for r in result["breakdown"]), places=6)
		self.assertEqual(result["total_tokens"], sum(r["tokens"] for r in result["breakdown"]))
