# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The Delegates to Other Agents toggle.

Exposure and delegation are independent: exposure is who may call THIS
agent, delegation is who this agent calls. An orchestrator normally
delegates without being exposed at all, so the toggle exists to keep the
delegation fields off every other agent's form without tying them to
exposure.

The toggle is presentation; the sub-agent list is the truth the
delegation gate actually reads. These tests pin that relationship down.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.agents.a2a import guardrails


class TestDelegationToggle(FrappeTestCase):
	def test_new_agent_does_not_delegate(self):
		agent = make_agent_configuration()
		self.assertFalse(agent.delegates_to_agents)

	def test_listing_a_sub_agent_turns_the_toggle_on(self):
		worker = make_agent_configuration()
		agent = make_agent_configuration()
		agent.append("allowed_delegates", {"agent_configuration": worker.name})
		agent.save(ignore_permissions=True)
		self.assertTrue(
			agent.delegates_to_agents,
			"the list is the truth — the toggle follows it, so a live allow-list is never hidden",
		)

	def test_toggle_cannot_be_turned_off_while_sub_agents_remain(self):
		worker = make_agent_configuration()
		agent = make_agent_configuration()
		agent.append("allowed_delegates", {"agent_configuration": worker.name})
		agent.save(ignore_permissions=True)

		agent.delegates_to_agents = 0
		agent.save(ignore_permissions=True)
		agent.reload()
		self.assertTrue(agent.delegates_to_agents)
		self.assertTrue(guardrails.may_delegate_to(agent.name, worker.name))

	def test_clearing_the_list_lets_the_toggle_go_off(self):
		worker = make_agent_configuration()
		agent = make_agent_configuration()
		agent.append("allowed_delegates", {"agent_configuration": worker.name})
		agent.save(ignore_permissions=True)

		agent.allowed_delegates = []
		agent.delegates_to_agents = 0
		agent.save(ignore_permissions=True)
		agent.reload()
		self.assertFalse(agent.delegates_to_agents)
		self.assertFalse(guardrails.may_delegate_to(agent.name, worker.name))

	def test_delegation_does_not_require_exposure(self):
		"""The orchestrator case: delegates to four workers, exposed to nobody."""
		workers = [make_agent_configuration() for _ in range(2)]
		orchestrator = make_agent_configuration(delegates_to_agents=1)
		for worker in workers:
			orchestrator.append("allowed_delegates", {"agent_configuration": worker.name})
		orchestrator.save(ignore_permissions=True)

		self.assertFalse(orchestrator.a2a_exposed)
		self.assertTrue(orchestrator.delegates_to_agents)
		for worker in workers:
			self.assertTrue(guardrails.may_delegate_to(orchestrator.name, worker.name))

	def test_exposure_does_not_require_delegation(self):
		"""And the worker case: reachable over A2A, delegates to nobody."""
		worker = make_agent_configuration(a2a_exposed=1)
		self.assertTrue(worker.a2a_exposed)
		self.assertFalse(worker.delegates_to_agents)

	def test_guardrail_defaults_survive_the_toggle(self):
		agent = make_agent_configuration(delegates_to_agents=1)
		limits = guardrails.guardrails_for(agent.name)
		self.assertEqual(limits["max_recursion_depth"], 5)
		self.assertEqual(limits["max_task_handoffs"], 10)
		self.assertEqual(limits["max_delegation_retries"], 3)
