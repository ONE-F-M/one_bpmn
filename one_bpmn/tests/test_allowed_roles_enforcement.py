# Copyright (c) 2026, one-fm and contributors
# See license.txt
"""
allowed_roles is a control, not a filter.

The field existed and was applied only when building the chat picker, so it
decided what a user was OFFERED and placed no limit on what they could CALL.
``invoke_agent`` is whitelisted, so naming an agent_id directly went straight
past it.

These tests pin the fix, and the property that caused the bug: the picker and
the gate must read one rule, not two.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.agent_invocation import (
	_authorize,
	allowed_roles_for,
	user_may_use_agent,
)

AGENT = "Allowed Roles Test Agent"
ROLE = "Allowed Roles Test Role"
INSIDER = "allowed-roles-insider@example.com"
OUTSIDER = "allowed-roles-outsider@example.com"


class TestAllowedRolesEnforcement(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._purge()
		if not frappe.db.exists("Role", ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": ROLE}).insert(ignore_permissions=True)
		for email, roles in ((INSIDER, [ROLE]), (OUTSIDER, [])):
			user = frappe.get_doc({
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
			}).insert(ignore_permissions=True)
			for r in roles:
				user.add_roles(r)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls._purge()
		super().tearDownClass()

	@classmethod
	def _purge(cls):
		frappe.set_user("Administrator")
		for email in (INSIDER, OUTSIDER):
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		if frappe.db.exists("AI Agent Configuration", AGENT):
			frappe.delete_doc("AI Agent Configuration", AGENT, force=True)
		if frappe.db.exists("Role", ROLE):
			frappe.delete_doc("Role", ROLE, force=True)
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		if frappe.db.exists("AI Agent Configuration", AGENT):
			frappe.delete_doc("AI Agent Configuration", AGENT, force=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _agent(self, roles=(), lifecycle="Live"):
		doc = frappe.get_doc({
			"doctype": "AI Agent Configuration",
			"agent_name": AGENT,
			"agent_id": "zz_allowed_roles_test",
			"agent_type": "Chat",
			"agent_framework": "Direct API",
			"chat_mode_label": "Allowed Roles Test",
			"enabled": 1,
			"lifecycle_status": lifecycle,
		})
		for r in roles:
			doc.append("allowed_roles", {"role": r})
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return doc.name

	def _config(self, lifecycle="Live"):
		return {
			"agent_id": "zz_allowed_roles_test",
			"lifecycle_status": lifecycle,
			"chat_mode_label": "Allowed Roles Test",
		}

	# ── The bug this closes ──────────────────────────────────────────────
	def test_naming_the_agent_directly_no_longer_bypasses_the_restriction(self):
		"""The whole defect: the picker hid it, the endpoint ran it anyway."""
		self._agent(roles=[ROLE])
		frappe.set_user(OUTSIDER)

		with self.assertRaises(frappe.PermissionError):
			_authorize(self._config())

	def test_a_user_with_the_role_is_allowed(self):
		self._agent(roles=[ROLE])
		frappe.set_user(INSIDER)

		_authorize(self._config())  # must not raise

	# ── Empty means everyone, and that must not change ───────────────────
	def test_an_unrestricted_agent_stays_open_to_everyone(self):
		"""Every Live agent today has an empty table.

		Reading empty as "nobody" would take the entire fleet offline the moment
		this shipped, so it is pinned by a test rather than left to a comment.
		"""
		self._agent(roles=[])
		frappe.set_user(OUTSIDER)

		self.assertEqual(allowed_roles_for(AGENT), set())
		_authorize(self._config())  # must not raise

	def test_system_manager_is_allowed_through_a_restriction(self):
		"""It can edit the roles anyway — refusing it would be appearance only."""
		self._agent(roles=[ROLE])
		frappe.set_user("Administrator")

		self.assertTrue(user_may_use_agent(AGENT))

	# ── The picker and the gate must not disagree ────────────────────────
	def test_the_picker_never_offers_what_the_gate_would_refuse(self):
		"""The root cause was two readings of one field, so this is the real fix.

		Stated one-directionally on purpose. The picker applies filters the gate
		does not — an agent with no deployed map is hidden from chat but is still
		invocable by a task — so "offered == callable" is not true and asserting
		it would be testing the wrong thing. The invariant that matters is that
		the picker can never offer something the gate then refuses.
		"""
		from one_bpmn.api.agent_invocation import list_available_agents

		self._agent(roles=[ROLE])

		for user in (INSIDER, OUTSIDER):
			frappe.set_user(user)
			offered = [a["agent_id"] for a in list_available_agents(include_legacy=0)]
			for agent_id in offered:
				name = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name")
				if not name:
					continue
				self.assertTrue(
					user_may_use_agent(name),
					f"{user} was offered '{agent_id}' but the gate refuses it",
				)

	def test_the_restricted_agent_is_hidden_from_a_user_without_the_role(self):
		from one_bpmn.api.agent_invocation import list_available_agents

		self._agent(roles=[ROLE])
		frappe.set_user(OUTSIDER)

		offered = [a["agent_id"] for a in list_available_agents(include_legacy=0)]
		self.assertNotIn("zz_allowed_roles_test", offered)
		self.assertFalse(user_may_use_agent(AGENT))

	# ── The Draft gate still works ───────────────────────────────────────
	def test_a_draft_agent_is_still_author_only(self):
		self._agent(roles=[], lifecycle="Draft")
		frappe.set_user(OUTSIDER)

		with self.assertRaises(frappe.PermissionError):
			_authorize(self._config(lifecycle="Draft"))

	# ── Fails open on a read fault, not closed ───────────────────────────
	def test_an_unreadable_role_table_does_not_lock_everyone_out(self):
		from unittest.mock import patch

		self._agent(roles=[ROLE])
		with patch("frappe.get_all", side_effect=RuntimeError("db down")):
			self.assertEqual(allowed_roles_for(AGENT), set())
