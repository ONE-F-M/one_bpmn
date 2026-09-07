# Copyright (c) 2026, one-fm and contributors
"""A delegation carries the Work Item and pull request it is about, and the
specialists may read that Work Item as their own identity."""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import identity
from one_bpmn.agents.a2a import local
from one_bpmn.one_bpmn.connectors import a2a_client_ops as ops
from one_bpmn.one_bpmn.patches.v1_0 import add_work_item_refs_to_a2a_connector as fields_patch
from one_bpmn.one_bpmn.patches.v1_0 import grant_specialists_work_item_read as roles_patch


class TestRequestPayload(FrappeTestCase):
	def test_references_ride_alongside_the_instruction(self):
		self.assertEqual(
			local.request_payload("Fix it.", "WI-000001", "https://github.com/o/r/pull/9"),
			{"instruction": "Fix it.", "work_item": "WI-000001", "pull_request": "https://github.com/o/r/pull/9"},
		)

	def test_absent_references_are_not_written_as_nulls(self):
		self.assertEqual(local.request_payload("Fix it."), {"instruction": "Fix it."})


class TestWorkItemRefs(FrappeTestCase):
	def test_the_callers_work_item_wins_over_whatever_the_model_typed(self):
		instance = frappe._dict(context_doctype="Work Item", context_docname="WI-000042")
		with patch.object(frappe.db, "get_value", return_value="https://github.com/o/r/pull/7"):
			self.assertEqual(
				ops._work_item_refs(instance, {"work_item": "WI-999999"}),
				("WI-000042", "https://github.com/o/r/pull/7"),
			)

	def test_params_stand_in_when_the_caller_has_no_work_item(self):
		instance = frappe._dict(context_doctype="A2A Task", context_docname="A2A-1")
		self.assertEqual(ops._work_item_refs(instance, {"work_item": " WI-000005 ", "pull_request": ""}), ("WI-000005", None))
		self.assertEqual(ops._work_item_refs(None, {}), (None, None))

	def test_a_pull_request_given_on_the_shape_is_kept_when_the_work_item_has_none(self):
		instance = frappe._dict(context_doctype="Work Item", context_docname="WI-000042")
		with patch.object(frappe.db, "get_value", return_value=None):
			self.assertEqual(ops._work_item_refs(instance, {"pull_request": "https://github.com/o/r/pull/1"})[1], "https://github.com/o/r/pull/1")


class TestConnectorFieldsPatch(FrappeTestCase):
	def test_fields_are_added_once_and_the_override_fields_stay_last(self):
		if not frappe.db.exists("BPMN Connector Operation", fields_patch.OPERATION):
			self.skipTest("a2a connector not on this site")
		fields_patch.execute()
		fields_patch.execute()
		names = [r.field_name for r in frappe.get_doc("BPMN Connector Operation", fields_patch.OPERATION).fields]
		self.assertEqual(names.count("work_item"), 1)
		self.assertEqual(names.count("pull_request"), 1)
		self.assertEqual(names[-2:], ["required_capability", "timeout_minutes"])


class TestGrantSpecialistsRead(FrappeTestCase):
	def test_every_specialist_gets_an_identity_that_can_read_a_work_item(self):
		for agent in roles_patch.AGENTS:
			if not frappe.db.exists("AI Agent Configuration", agent):
				self.skipTest(f"{agent} is not on this site")
		roles_patch.execute()
		roles_patch.execute()  # idempotent
		wi = frappe.get_all("Work Item", pluck="name", limit=1)
		for agent in roles_patch.AGENTS:
			doc = frappe.get_doc("AI Agent Configuration", agent)
			self.assertEqual([r.role for r in doc.agent_roles].count(roles_patch.ROLE), 1, agent)
			user = identity.user_for(agent)
			self.assertTrue(user and frappe.db.exists("User", user), f"{agent} has no identity")
			self.assertIn(roles_patch.ROLE, frappe.get_roles(user), agent)
			if wi:
				self.assertTrue(frappe.has_permission("Work Item", "read", doc=wi[0], user=user), agent)
