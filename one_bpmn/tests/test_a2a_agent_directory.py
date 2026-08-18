# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The agent directory as a TOOL (WI-001933).

A delegating agent should not need its targets drawn into its diagram.
Give it this tool and it reads the roster at run time — the same card data
the A2A page shows a person — then calls the delegate tool with the one it
picked.

The one rule that matters here: an agent must never read about a
specialist it would then be refused, so the directory is scoped by exactly
the guardrail that would block the delegation.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.one_bpmn.connectors import a2a_client_ops


def look_up(delegating_agent=None):
	return a2a_client_ops.list_delegatable_agents(
		{"delegating_agent": delegating_agent} if delegating_agent else {}, {}
	)


class TestTheDirectory(FrappeTestCase):
	def test_an_exposed_agent_appears_with_what_it_is_for(self):
		caller = make_agent_configuration()
		worker = make_agent_configuration(
			a2a_exposed=1,
			a2a_skill_tags="safety, hse",
			description="Assesses site safety and writes up findings.",
		)

		result = look_up(caller.name)
		row = next(a for a in result["agents"] if a["agent"] == worker.name)
		self.assertEqual(row["tags"], ["safety", "hse"])
		self.assertIn("site safety", row["description"].lower())
		self.assertEqual(result["count"], len(result["agents"]))
		self.assertTrue(result["note"], "the model needs telling what to do with the list")

	def test_the_agent_value_is_what_the_delegate_tool_wants(self):
		caller = make_agent_configuration()
		worker = make_agent_configuration(a2a_exposed=1)
		row = next(a for a in look_up(caller.name)["agents"] if a["agent"] == worker.name)
		self.assertIn(row["agent"], a2a_client_ops.local_agent_choices())

	def test_an_unexposed_agent_is_invisible(self):
		caller = make_agent_configuration()
		hidden = make_agent_configuration()
		names = {a["agent"] for a in look_up(caller.name)["agents"]}
		self.assertNotIn(hidden.name, names, "not exposed, so delegation would be refused")

	def test_a_draft_agent_is_invisible(self):
		caller = make_agent_configuration()
		draft = make_agent_configuration(a2a_exposed=1, lifecycle_status="Draft")
		names = {a["agent"] for a in look_up(caller.name)["agents"]}
		self.assertNotIn(draft.name, names)

	def test_an_agent_is_never_offered_itself(self):
		caller = make_agent_configuration(a2a_exposed=1)
		names = {a["agent"] for a in look_up(caller.name)["agents"]}
		self.assertNotIn(caller.name, names)

	def test_restricting_delegation_narrows_the_directory(self):
		listed = make_agent_configuration(a2a_exposed=1)
		unlisted = make_agent_configuration(a2a_exposed=1)
		caller = make_agent_configuration(restrict_delegates=1)
		caller.append("allowed_delegates", {"agent_configuration": listed.name})
		caller.save(ignore_permissions=True)

		names = {a["agent"] for a in look_up(caller.name)["agents"]}
		self.assertIn(listed.name, names)
		self.assertNotIn(unlisted.name, names, "reading about it would only lead to a refusal")

	def test_everything_listed_would_actually_be_allowed(self):
		"""The invariant, stated directly: the directory and the gate agree."""
		from one_bpmn.agents.a2a import guardrails

		make_agent_configuration(a2a_exposed=1)
		caller = make_agent_configuration()
		for row in look_up(caller.name)["agents"]:
			self.assertTrue(
				guardrails.may_delegate_to(caller.name, row["agent"]),
				f"{row['agent']} was advertised but would be refused",
			)

	def test_no_delegating_agent_still_answers(self):
		"""A map with no agent behind it (a plain process calling the tool)
		gets the public roster rather than an error."""
		worker = make_agent_configuration(a2a_exposed=1)
		names = {a["agent"] for a in look_up()["agents"]}
		self.assertIn(worker.name, names)

	def test_the_operation_is_registered_on_the_connector(self):
		"""Otherwise it cannot be dropped into a toolbox, which is the point."""
		self.assertTrue(
			frappe.db.exists(
				"BPMN Connector Operation",
				{"connector": "a2a", "operation_id": "list_delegatable_agents"},
			)
		)
