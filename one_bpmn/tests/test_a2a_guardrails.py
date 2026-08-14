# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-002008 + WI-002010: delegation limits and the sub-agent allow-list.

Both live on the delegating agent's own configuration, and both are
enforced at the one hand-off gate — whichever direction the work goes.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import a2a_contract
from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.agents.a2a import guardrails


def with_sub_agents(parent, subs, **limits):
	"""An agent that restricts delegation to exactly these agents."""
	parent.restrict_delegates = 1
	for sub in subs:
		parent.append("allowed_delegates", {"agent_configuration": sub.name})
	for field, value in limits.items():
		parent.set(field, value)
	parent.save(ignore_permissions=True)
	return parent


def make_task(execution_id, depth=1, handoffs=1):
	task = frappe.get_doc(
		{
			"doctype": "A2A Task",
			"direction": "Outbound",
			"state": "working",
			"task_execution_id": execution_id,
			"delegation_depth": depth,
			"handoff_count": handoffs,
		}
	)
	task.flags.ignore_links = True
	return task.insert(ignore_permissions=True)


class TestSubAgentAllowList(FrappeTestCase):
	def test_only_listed_sub_agents_are_allowed(self):
		worker = make_agent_configuration(a2a_exposed=1)
		stranger = make_agent_configuration(a2a_exposed=1)
		orchestrator = with_sub_agents(make_agent_configuration(), [worker])

		self.assertTrue(guardrails.may_delegate_to(orchestrator.name, worker.name))
		self.assertFalse(guardrails.may_delegate_to(orchestrator.name, stranger.name))
		with self.assertRaises(guardrails.DelegationRefused):
			guardrails.check_allowed(orchestrator.name, stranger.name)

	def test_restriction_with_an_empty_list_delegates_to_nobody(self):
		orchestrator = make_agent_configuration(restrict_delegates=1)
		worker = make_agent_configuration(a2a_exposed=1)
		self.assertFalse(guardrails.may_delegate_to(orchestrator.name, worker.name))

	def test_unrestricted_agent_may_delegate_to_any_exposed_agent(self):
		"""The default: exposure is the grant, no list to maintain."""
		orchestrator = make_agent_configuration()
		exposed = make_agent_configuration(a2a_exposed=1)
		unexposed = make_agent_configuration()
		self.assertTrue(guardrails.may_delegate_to(orchestrator.name, exposed.name))
		self.assertFalse(guardrails.may_delegate_to(orchestrator.name, unexposed.name))

	def test_list_edits_take_effect_immediately(self):
		worker = make_agent_configuration(a2a_exposed=1)
		swapped_in = make_agent_configuration(a2a_exposed=1)
		orchestrator = with_sub_agents(make_agent_configuration(), [worker])

		orchestrator.allowed_delegates = []
		orchestrator.append("allowed_delegates", {"agent_configuration": swapped_in.name})
		orchestrator.save(ignore_permissions=True)

		self.assertFalse(guardrails.may_delegate_to(orchestrator.name, worker.name))
		self.assertTrue(guardrails.may_delegate_to(orchestrator.name, swapped_in.name))


class TestDelegationLimits(FrappeTestCase):
	def test_defaults_when_unset(self):
		agent = make_agent_configuration()
		limits = guardrails.guardrails_for(agent.name)
		self.assertEqual(limits["max_recursion_depth"], 5)
		self.assertEqual(limits["max_task_handoffs"], 10)
		self.assertEqual(limits["max_delegation_retries"], 3)

	def test_configured_limits_win(self):
		agent = make_agent_configuration(max_recursion_depth=2, max_task_handoffs=3)
		limits = guardrails.guardrails_for(agent.name)
		self.assertEqual(limits["max_recursion_depth"], 2)
		self.assertEqual(limits["max_task_handoffs"], 3)

	def test_depth_limit_stops_the_chain(self):
		worker = make_agent_configuration(a2a_exposed=1)
		orchestrator = with_sub_agents(
			make_agent_configuration(), [worker], max_recursion_depth=2
		)
		guardrails.enforce(orchestrator.name, worker.name, {"delegation_depth": 2, "handoff_count": 1})
		with self.assertRaises(guardrails.DelegationRefused) as caught:
			guardrails.enforce(
				orchestrator.name, worker.name, {"delegation_depth": 3, "handoff_count": 1}
			)
		self.assertEqual(caught.exception.reason_code, "max_recursion_depth")
		self.assertIn("nested", str(caught.exception))

	def test_handoff_limit_stops_sideways_loops(self):
		worker = make_agent_configuration(a2a_exposed=1)
		orchestrator = with_sub_agents(make_agent_configuration(), [worker], max_task_handoffs=2)
		with self.assertRaises(guardrails.DelegationRefused) as caught:
			guardrails.enforce(
				orchestrator.name, worker.name, {"delegation_depth": 1, "handoff_count": 3}
			)
		self.assertEqual(caught.exception.reason_code, "max_task_handoffs")

	def test_counters_reset_for_a_new_top_level_request(self):
		counters = guardrails.next_counters(None)
		self.assertEqual(counters["delegation_depth"], 1)
		self.assertEqual(counters["handoff_count"], 1)
		self.assertIsNone(counters["task_execution_id"])

	def test_counters_advance_down_the_chain(self):
		execution_id = f"exec-{frappe.generate_hash(length=6)}"
		parent = make_task(execution_id, depth=2, handoffs=2)
		counters = guardrails.next_counters(parent.name)
		self.assertEqual(counters["task_execution_id"], execution_id)
		self.assertEqual(counters["delegation_depth"], 3)
		self.assertEqual(counters["handoff_count"], 2)

	def test_chain_handoffs_counts_the_task_rows(self):
		execution_id = f"exec-{frappe.generate_hash(length=6)}"
		make_task(execution_id)
		make_task(execution_id)
		self.assertEqual(guardrails.chain_handoffs(execution_id), 2)
		self.assertEqual(guardrails.chain_handoffs(None), 0)

	def test_trace_metadata_round_trips_through_the_protocol(self):
		from one_bpmn.agents.a2a.protocol import read_trace

		counters = {"task_execution_id": "exec-abc", "delegation_depth": 3, "handoff_count": 7}
		metadata = guardrails.trace_metadata(counters)
		self.assertEqual(metadata[a2a_contract.trace_key("delegationDepth")], 3)
		self.assertEqual(read_trace({"metadata": metadata}), counters)
