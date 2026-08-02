# Copyright (c) 2026, one-fm and contributors
# See license.txt
"""The agent-creation grant (WI-001751 follow-up).

Which process carries a new agent from Draft to Live used to be a hardcoded
name ("AI Agent Creation Process") that nothing shipped, so a site without that
exact record silently lost the ability to take agents Live. It is now a grant on
AI Agent Configuration: one configuration ticks ``can_create_agents`` and links
the map in ``agent_creation_process``, and everything resolves from there.

These tests pin the three rules that make the lookup safe: the grant is unique,
it cannot be held without a linked process, and a site with no grant refuses to
create agents instead of stranding them as permanent Drafts.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.agent_config_resolver import (
	create_agent_configuration,
	get_creation_grant_holder,
	get_creation_process_model,
)

GRANT_HOLDER = "Grant Holder Agent"
OTHER_AGENT = "Second Grant Agent"
CREATION_MAP = "Test Agent Creation Map"


class TestAgentCreationGrant(FrappeTestCase):
	def setUp(self):
		self._purge()
		self.map_name = self._make_map(CREATION_MAP, is_active=1)

	def tearDown(self):
		self._purge()

	# ── helpers ─────────────────────────────────────────────────────────────
	def _purge(self):
		for name in (GRANT_HOLDER, OTHER_AGENT):
			if frappe.db.exists("AI Agent Configuration", name):
				frappe.delete_doc("AI Agent Configuration", name, force=True)
		if frappe.db.exists("BPMN Process Model", CREATION_MAP):
			frappe.delete_doc("BPMN Process Model", CREATION_MAP, force=True)
		frappe.db.commit()

	def _make_map(self, title, is_active=1):
		# autoname is field:title, so doc.name == title.
		doc = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"title": title,
			"process_id": frappe.scrub(title),
			"version": "1.0",
			"is_active": is_active,
		})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_agent(self, name, **kwargs):
		values = {
			"doctype": "AI Agent Configuration",
			"agent_name": name,
			"agent_id": frappe.scrub(name),
			"agent_framework": "Direct API",
			"agent_type": "Chat",
			"chat_mode_label": name,
			"enabled": 1,
			"system_prompt": "You are a test agent.",
		}
		values.update(kwargs)
		doc = frappe.get_doc(values)
		doc.insert(ignore_permissions=True)
		return doc

	# ── the grant is unique ─────────────────────────────────────────────────
	def test_second_grant_holder_is_rejected(self):
		self._make_agent(GRANT_HOLDER, can_create_agents=1, agent_creation_process=self.map_name)

		with self.assertRaises(frappe.ValidationError) as ctx:
			self._make_agent(
				OTHER_AGENT, can_create_agents=1, agent_creation_process=self.map_name
			)
		# The message must name the existing holder — "already taken" with no
		# culprit sends the user hunting through every agent.
		self.assertIn(GRANT_HOLDER, str(ctx.exception))

	def test_grant_can_move_between_agents(self):
		"""Clearing the checkbox must free the grant, or it can never be moved."""
		holder = self._make_agent(
			GRANT_HOLDER, can_create_agents=1, agent_creation_process=self.map_name
		)
		holder.can_create_agents = 0
		holder.save(ignore_permissions=True)

		self._make_agent(OTHER_AGENT, can_create_agents=1, agent_creation_process=self.map_name)
		self.assertEqual(get_creation_grant_holder(), OTHER_AGENT)

	def test_holder_can_be_saved_again(self):
		"""Re-saving the holder must not trip the uniqueness check on itself."""
		holder = self._make_agent(
			GRANT_HOLDER, can_create_agents=1, agent_creation_process=self.map_name
		)
		holder.max_tokens = 2048
		holder.save(ignore_permissions=True)  # must not raise
		self.assertEqual(get_creation_grant_holder(), GRANT_HOLDER)

	# ── the grant needs a linked process ────────────────────────────────────
	def test_grant_without_process_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self._make_agent(GRANT_HOLDER, can_create_agents=1)

	# ── lookup ──────────────────────────────────────────────────────────────
	def test_lookup_returns_the_linked_map(self):
		self._make_agent(GRANT_HOLDER, can_create_agents=1, agent_creation_process=self.map_name)
		self.assertEqual(get_creation_process_model(), self.map_name)

	def test_lookup_is_none_without_a_grant(self):
		self._make_agent(GRANT_HOLDER)
		self.assertIsNone(get_creation_process_model())
		self.assertIsNone(get_creation_grant_holder())

	def test_lookup_is_none_when_the_map_is_not_deployed(self):
		"""A grant pointing at an undeployed map cannot run — the holder is
		still reported, so the error can say which agent to fix."""
		frappe.db.set_value("BPMN Process Model", self.map_name, "is_active", 0)
		self._make_agent(GRANT_HOLDER, can_create_agents=1, agent_creation_process=self.map_name)

		self.assertIsNone(get_creation_process_model())
		self.assertEqual(get_creation_grant_holder(), GRANT_HOLDER)

	def test_lookup_ignores_a_disabled_holder(self):
		self._make_agent(
			GRANT_HOLDER, can_create_agents=1, agent_creation_process=self.map_name, enabled=0
		)
		self.assertIsNone(get_creation_process_model())

	# ── creation refuses without a grant ────────────────────────────────────
	def test_create_agent_configuration_refuses_without_a_grant(self):
		"""Creating a Chat agent with no creation process would strand it as a
		permanent Draft — apply_background_lifecycle only auto-lives Background
		agents — so the endpoint must refuse rather than write the record."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			create_agent_configuration({
				"agent_name": "Stranded Agent",
				"chat_mode_label": "Stranded Agent",
				"ai_model": "",
				"description": "should never be written",
			})
		self.assertIn("has not been linked", str(ctx.exception))
		self.assertFalse(frappe.db.exists("AI Agent Configuration", "Stranded Agent"))
