# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Who may receive delegated work (WI-002010).

The rule, in one line: **exposure is the grant, the list only narrows it.**

Marking an agent Exposed over A2A is what makes it available for
agent-to-agent work. The delegating agent needs no list, because the tools
drawn on its process map already decide who it actually calls — a second
copy of that decision on the configuration would be bookkeeping that has
to be updated every time an agent is added.

Ticking Restrict Delegation narrows the set to named agents, for the cases
where the map is not a tight enough boundary on its own.
"""

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.agents.a2a import guardrails


class TestExposureIsTheGrant(FrappeTestCase):
	def test_any_exposed_agent_may_receive_work_by_default(self):
		orchestrator = make_agent_configuration()
		exposed = make_agent_configuration(a2a_exposed=1)

		self.assertFalse(orchestrator.restrict_delegates, "restriction is off by default")
		self.assertTrue(guardrails.may_delegate_to(orchestrator.name, exposed.name))

	def test_an_unexposed_agent_never_receives_work(self):
		orchestrator = make_agent_configuration()
		unexposed = make_agent_configuration()

		self.assertFalse(guardrails.may_delegate_to(orchestrator.name, unexposed.name))
		with self.assertRaises(guardrails.DelegationRefused) as caught:
			guardrails.check_allowed(orchestrator.name, unexposed.name)
		self.assertEqual(caught.exception.reason_code, "target_not_exposed")
		self.assertIn("Exposed over A2A", str(caught.exception))

	def test_a_draft_agent_never_receives_work(self):
		orchestrator = make_agent_configuration()
		draft = make_agent_configuration(a2a_exposed=1, lifecycle_status="Draft")
		self.assertFalse(guardrails.may_delegate_to(orchestrator.name, draft.name))

	def test_adding_an_agent_needs_no_edit_anywhere_else(self):
		"""The point of the design: a new specialist is one tick, not N edits."""
		orchestrator = make_agent_configuration()
		for _ in range(3):
			newcomer = make_agent_configuration(a2a_exposed=1)
			self.assertTrue(guardrails.may_delegate_to(orchestrator.name, newcomer.name))


class TestOptionalRestriction(FrappeTestCase):
	def test_restriction_limits_to_the_listed_agents(self):
		listed = make_agent_configuration(a2a_exposed=1)
		unlisted = make_agent_configuration(a2a_exposed=1)
		orchestrator = make_agent_configuration(restrict_delegates=1)
		orchestrator.append("allowed_delegates", {"agent_configuration": listed.name})
		orchestrator.save(ignore_permissions=True)

		self.assertTrue(guardrails.may_delegate_to(orchestrator.name, listed.name))
		self.assertFalse(guardrails.may_delegate_to(orchestrator.name, unlisted.name))
		with self.assertRaises(guardrails.DelegationRefused) as caught:
			guardrails.check_allowed(orchestrator.name, unlisted.name)
		self.assertEqual(caught.exception.reason_code, "target_not_allowed")

	def test_restriction_with_an_empty_list_allows_nothing(self):
		orchestrator = make_agent_configuration(restrict_delegates=1)
		exposed = make_agent_configuration(a2a_exposed=1)
		self.assertFalse(guardrails.may_delegate_to(orchestrator.name, exposed.name))

	def test_a_listed_agent_still_has_to_be_exposed(self):
		"""The list narrows the grant; it cannot substitute for it."""
		unexposed = make_agent_configuration()
		orchestrator = make_agent_configuration(restrict_delegates=1)
		orchestrator.append("allowed_delegates", {"agent_configuration": unexposed.name})
		orchestrator.save(ignore_permissions=True)
		self.assertFalse(guardrails.may_delegate_to(orchestrator.name, unexposed.name))

	def test_list_edits_take_effect_immediately(self):
		first = make_agent_configuration(a2a_exposed=1)
		second = make_agent_configuration(a2a_exposed=1)
		orchestrator = make_agent_configuration(restrict_delegates=1)
		orchestrator.append("allowed_delegates", {"agent_configuration": first.name})
		orchestrator.save(ignore_permissions=True)

		orchestrator.allowed_delegates = []
		orchestrator.append("allowed_delegates", {"agent_configuration": second.name})
		orchestrator.save(ignore_permissions=True)

		self.assertFalse(guardrails.may_delegate_to(orchestrator.name, first.name))
		self.assertTrue(guardrails.may_delegate_to(orchestrator.name, second.name))

	def test_a_list_left_under_an_unticked_restriction_is_inert(self):
		"""Saving in that state is allowed — it just does not restrict, and the
		form says so rather than letting it look locked down."""
		listed = make_agent_configuration(a2a_exposed=1)
		other = make_agent_configuration(a2a_exposed=1)
		orchestrator = make_agent_configuration(restrict_delegates=1)
		orchestrator.append("allowed_delegates", {"agent_configuration": listed.name})
		orchestrator.save(ignore_permissions=True)

		orchestrator.restrict_delegates = 0
		orchestrator.save(ignore_permissions=True)
		orchestrator.reload()

		self.assertTrue(orchestrator.allowed_delegates, "the rows are kept")
		self.assertTrue(
			guardrails.may_delegate_to(orchestrator.name, other.name),
			"but they no longer narrow anything",
		)


class TestGuardrailsAreIndependent(FrappeTestCase):
	def test_limits_apply_whether_or_not_delegation_is_restricted(self):
		"""Depth and handoff caps are loop protection, not an allow-list, so
		they are not gated behind the restriction."""
		for restricted in (0, 1):
			agent = make_agent_configuration(restrict_delegates=restricted)
			limits = guardrails.guardrails_for(agent.name)
			self.assertEqual(limits["max_recursion_depth"], 5)
			self.assertEqual(limits["max_task_handoffs"], 10)
			self.assertEqual(limits["max_delegation_retries"], 3)
