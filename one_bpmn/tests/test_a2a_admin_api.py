# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001934: the admin surface — both registries and the task monitor.

Every endpoint here is System Manager only: the registries decide who
may reach our agents, and the monitor shows what those agents are being
asked to do.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.api import a2a_admin_api
from one_bpmn.tests.test_a2a_client import make_remote_for
from one_bpmn.tests.test_a2a_client_registry import approve, make_client


def make_nobody():
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": f"a2a-admin-nobody-{frappe.generate_hash(length=6)}@example.com",
			"first_name": "Nobody",
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)


def make_task(**kwargs):
	defaults = {"doctype": "A2A Task", "direction": "Inbound", "state": "working"}
	defaults.update(kwargs)
	task = frappe.get_doc(defaults)
	task.flags.ignore_links = True
	return task.insert(ignore_permissions=True)


class TestA2AAdminPermissions(FrappeTestCase):
	def test_every_endpoint_refuses_a_non_admin(self):
		nobody = make_nobody()
		with self.set_user(nobody.name):
			self.assertFalse(a2a_admin_api.get_permissions()["administer"])
			for call, kwargs in (
				(a2a_admin_api.list_remote_agents, {}),
				(a2a_admin_api.list_clients, {}),
				(a2a_admin_api.list_tasks, {}),
				(a2a_admin_api.exposed_agents, {}),
				(a2a_admin_api.fetch_remote_card, {"name": "x"}),
				(a2a_admin_api.set_remote_approval, {"name": "x", "approval_status": "Approved"}),
				(a2a_admin_api.set_client_approval, {"name": "x", "approval_status": "Approved"}),
				(a2a_admin_api.get_client_credentials, {"name": "x"}),
			):
				with self.assertRaises(frappe.PermissionError):
					call(**kwargs)

	def test_admin_sees_administer_true(self):
		self.assertTrue(a2a_admin_api.get_permissions()["administer"])


class TestA2AAdminRegistries(FrappeTestCase):
	def test_clients_carry_their_allow_list(self):
		agent = make_agent_configuration(a2a_exposed=1)
		client = approve(make_client(agents=[agent.name]))
		row = next(c for c in a2a_admin_api.list_clients() if c["name"] == client.name)
		self.assertEqual(row["allowed_agents"], [agent.name])
		self.assertEqual(row["user"], client.user)

	def test_exposed_agents_are_the_only_candidates(self):
		exposed = make_agent_configuration(a2a_exposed=1)
		unexposed = make_agent_configuration()
		draft = make_agent_configuration(a2a_exposed=1, lifecycle_status="Draft")
		names = {a["name"] for a in a2a_admin_api.exposed_agents()}
		self.assertIn(exposed.name, names)
		self.assertNotIn(unexposed.name, names)
		self.assertNotIn(draft.name, names)

	def test_remote_approval_round_trip(self):
		remote = make_remote_for(make_agent_configuration())
		result = a2a_admin_api.set_remote_approval(remote.name, "Revoked")
		self.assertEqual(result["approval_status"], "Revoked")
		result = a2a_admin_api.set_remote_approval(remote.name, "Approved")
		self.assertEqual(result["approval_status"], "Approved")

	def test_client_approval_issues_the_user(self):
		client = make_client()
		result = a2a_admin_api.set_client_approval(client.name, "Approved")
		self.assertTrue(result["user"])
		self.assertEqual(result["approval_status"], "Approved")

	def test_unknown_approval_status_is_refused(self):
		client = make_client()
		with self.assertRaises(frappe.ValidationError):
			a2a_admin_api.set_client_approval(client.name, "Whatever")


class TestA2AAdminTaskMonitor(FrappeTestCase):
	def test_lists_both_directions_with_counters(self):
		make_task(direction="Inbound", state="working", delegation_depth=1, handoff_count=1)
		make_task(direction="Outbound", state="completed", delegation_depth=2, handoff_count=3)
		result = a2a_admin_api.list_tasks()
		self.assertGreaterEqual(result["total"], 2)
		self.assertIn("delegation_depth", result["tasks"][0])
		self.assertIn("handoff_count", result["tasks"][0])

	def test_direction_and_state_filters(self):
		make_task(direction="Outbound", state="timed-out")
		outbound = a2a_admin_api.list_tasks(direction="Outbound")
		self.assertTrue(all(t["direction"] == "Outbound" for t in outbound["tasks"]))
		timed_out = a2a_admin_api.list_tasks(state="timed-out")
		self.assertTrue(all(t["state"] == "timed-out" for t in timed_out["tasks"]))

	def test_page_length_is_capped(self):
		result = a2a_admin_api.list_tasks(page_length=5000)
		self.assertLessEqual(result["page_length"], a2a_admin_api.MAX_PAGE_LENGTH)
