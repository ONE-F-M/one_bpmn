# Copyright (c) 2026, one-fm and contributors
"""The sandbox identifies the agent by the configuration linked to the running map, so a map named differently from its agent still gets that agent's Job setting and rules."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops


def _linked(links: dict, flags: dict | None = None):
	"""A stand-in for frappe.db.get_value: map name to linked agent, and agent to its flags."""

	def get_value(doctype, filters, fieldname=None, *args, **kwargs):
		if isinstance(filters, dict):
			return links.get(filters.get("process_model"))
		return (flags or {}).get(filters, {}).get(fieldname)

	return patch.object(frappe.db, "get_value", side_effect=get_value)


class TestAgentNameFor(FrappeTestCase):
	def test_the_agent_linked_to_the_map_wins_over_the_map_name(self):
		with _linked({"Dev Agent v1": "Dev Agent"}):
			self.assertEqual(ops.agent_name_for(frappe._dict(process_model="Dev Agent v1")), "Dev Agent")

	def test_a_map_with_no_linked_agent_keeps_its_own_name(self):
		with _linked({}):
			self.assertEqual(ops.agent_name_for(frappe._dict(process_model="Dev Agent")), "Dev Agent")

	def test_no_instance_and_no_map_give_none(self):
		self.assertIsNone(ops.agent_name_for(None))
		self.assertIsNone(ops.agent_name_for(frappe._dict(process_model=None)))


class TestRulesFollowTheLinkedAgent(FrappeTestCase):
	def test_reproduction_is_required_for_a_bug_map_named_differently_from_its_agent(self):
		instance = frappe._dict(process_model="Bug Programmer v1")
		with _linked(
			{"Bug Programmer v1": "Bug Programmer"}, {"Bug Programmer": {"require_reproduction": 1}}
		):
			self.assertTrue(ops.requires_reproduction(instance))

	def test_the_frontend_rules_apply_to_a_frontend_map_named_differently_from_its_agent(self):
		instance = frappe._dict(process_model="Frontend Agent v1", name="INST-1")
		with (
			_linked({"Frontend Agent v1": "Frontend Agent"}),
			patch.object(ops, "_skill_loaded", return_value=False),
		):
			self.assertIsNotNone(ops.frontend_edit_error(instance, "edit_file", "spiff/src/A.vue"))

	def test_a_map_that_is_not_a_frontend_agent_is_not_held_to_them(self):
		instance = frappe._dict(process_model="Dev Agent v1", name="INST-1")
		with _linked({"Dev Agent v1": "Dev Agent"}), patch.object(ops, "_skill_loaded", return_value=False):
			self.assertIsNone(ops.frontend_edit_error(instance, "edit_file", "spiff/src/A.vue"))


class TestJobDecisionUsesTheLinkedAgent(FrappeTestCase):
	def test_a_fast_tool_call_asks_about_the_linked_agent_not_the_map_name(self):
		instance = frappe._dict(process_model="Dev Agent v1", name="INST-1")
		settings = MagicMock(agent_sandbox_url="https://sandbox.example")
		settings.get_password.return_value = "token"
		with (
			patch.object(ops, "agent_name_for", return_value="Dev Agent"),
			patch.object(ops, "work_item_id_for", return_value="WI-1"),
			patch.object(ops.frappe, "get_cached_doc", return_value=settings),
			patch.object(ops.sessions, "uses_job", return_value=True) as uses_job,
			patch.object(ops, "_tool_call_in_session", return_value={"ok": True}) as in_session,
		):
			result = ops.sandbox_dispatch(
				"list_files", "one_bpmn", "staging", "Fix it.", {}, a2a_task="A2A-x", instance=instance
			)
		uses_job.assert_called_once_with("Dev Agent")
		in_session.assert_called_once()
		self.assertTrue(result["ok"])
