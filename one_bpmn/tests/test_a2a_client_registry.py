# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001931: the A2A Client guest list.

The user represents the CALLER. Approval issues the badge (service user
+ API key), revocation disables it without touching anyone else, and the
allowed_agents child table is the positive list the A2A door checks.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.agents.a2a.principal import (
	A2A_CLIENT_ROLE,
	client_may_invoke,
	get_client_for_user,
)


def make_client(agents=(), **kwargs):
	defaults = {
		"doctype": "A2A Client",
		"client_name": f"_Test Client {frappe.generate_hash(length=8)}",
		"enabled": 1,
		"approval_status": "Draft",
	}
	defaults.update(kwargs)
	client = frappe.get_doc(defaults)
	for agent in agents:
		client.append("allowed_agents", {"agent_configuration": agent})
	return client.insert(ignore_permissions=True)


def approve(client):
	client.approval_status = "Approved"
	client.save(ignore_permissions=True)
	return client


class TestA2AClientRegistry(FrappeTestCase):
	def test_approval_provisions_badge_user(self):
		client = approve(make_client())
		self.assertTrue(client.user)
		user = frappe.get_doc("User", client.user)
		self.assertTrue(user.enabled)
		self.assertTrue(user.api_key)
		self.assertEqual([r.role for r in user.roles], [A2A_CLIENT_ROLE])
		self.assertEqual(client.approved_by, frappe.session.user)

	def test_draft_client_has_no_user(self):
		client = make_client()
		self.assertFalse(client.user)
		self.assertIsNone(get_client_for_user("nobody@agents.internal"))

	def test_revoke_disables_user_and_reapproval_keeps_keys(self):
		client = approve(make_client())
		user_name = client.user
		api_key = frappe.db.get_value("User", user_name, "api_key")

		client.approval_status = "Revoked"
		client.save(ignore_permissions=True)
		self.assertFalse(frappe.db.get_value("User", user_name, "enabled"))
		self.assertIsNone(get_client_for_user(user_name))

		client.approval_status = "Approved"
		client.save(ignore_permissions=True)
		self.assertTrue(frappe.db.get_value("User", user_name, "enabled"))
		self.assertEqual(frappe.db.get_value("User", user_name, "api_key"), api_key)

	def test_disabling_row_disables_user(self):
		client = approve(make_client())
		client.enabled = 0
		client.save(ignore_permissions=True)
		self.assertFalse(frappe.db.get_value("User", client.user, "enabled"))
		self.assertIsNone(get_client_for_user(client.user))

	def test_get_client_for_user_resolves_only_approved(self):
		client = approve(make_client())
		self.assertEqual(get_client_for_user(client.user), client.name)

	def test_allow_list(self):
		allowed = make_agent_configuration()
		other = make_agent_configuration()
		client = approve(make_client(agents=[allowed.name]))
		self.assertTrue(client_may_invoke(client.name, allowed.name))
		self.assertFalse(client_may_invoke(client.name, other.name))

	def test_empty_allow_list_invokes_nothing(self):
		client = approve(make_client())
		agent = make_agent_configuration()
		self.assertFalse(client_may_invoke(client.name, agent.name))

	def test_get_credentials_admin_only(self):
		client = approve(make_client())
		secret = client.get_credentials()
		self.assertTrue(secret["api_key"])
		self.assertTrue(secret["api_secret"])

		nobody = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"a2a-nobody-{frappe.generate_hash(length=8)}@example.com",
				"first_name": "Nobody",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		with self.set_user(nobody.name):
			self.assertRaises(frappe.PermissionError, client.get_credentials)

	def test_trash_disables_user(self):
		client = approve(make_client())
		user_name = client.user
		client.delete(ignore_permissions=True)
		self.assertFalse(frappe.db.get_value("User", user_name, "enabled"))
