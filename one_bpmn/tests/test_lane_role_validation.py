# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Lane names are checked against the site's enabled Roles, with suggestions for near misses."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers
from one_bpmn.agents.bpmn_task_config import match_lane_role, resolve_ir_lane_roles
from one_bpmn.api.process_map_api import validate_bpmn_readiness

ROLES = ["HR Manager", "HR User", "Accounts Manager"]


def _map(*lane_names):
	lanes = "".join(f'<bpmn:lane id="Lane_{i}" name="{n}" />' for i, n in enumerate(lane_names))
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs">
	<bpmn:process id="lane_roles" isExecutable="true">
		<bpmn:laneSet id="LaneSet_1">{lanes}</bpmn:laneSet>
		<bpmn:startEvent id="Start" />
		<bpmn:endEvent id="End" />
	</bpmn:process>
</bpmn:definitions>"""


def _lane_items(xml):
	result = validate_bpmn_readiness(xml)
	return {i["name"]: i for c in result["categories"] if c["label"] == "Lane Roles" for i in c["items"]}


class TestMatchLaneRole(FrappeTestCase):
	def test_an_exact_match_ignores_case(self):
		self.assertEqual(match_lane_role("hr manager", ROLES), ["HR Manager"])

	def test_a_typo_suggests_the_closest_roles(self):
		self.assertEqual(match_lane_role("HR Managr", ROLES)[0], "HR Manager")

	def test_an_unrelated_name_has_no_suggestion(self):
		self.assertEqual(match_lane_role("Administrator", ROLES), [])


class TestResolveIrLaneRoles(FrappeTestCase):
	def test_an_exact_match_is_rewritten_to_the_role_name(self):
		ir = {"lanes": [{"id": "hr", "name": "hr manager"}]}

		problems = resolve_ir_lane_roles(ir, ROLES)

		self.assertEqual(ir["lanes"][0]["name"], "HR Manager")
		self.assertEqual(problems, [])

	def test_a_near_match_is_kept_and_reported_with_suggestions(self):
		ir = {"lanes": [{"id": "hr", "name": "HR Managr"}]}

		problems = resolve_ir_lane_roles(ir, ROLES)

		self.assertEqual(ir["lanes"][0]["name"], "HR Managr")
		self.assertEqual(len(problems), 1)
		self.assertIn("HR Manager", problems[0]["message"])

	def test_a_lane_with_no_close_role_is_left_alone(self):
		ir = {"lanes": [{"id": "system", "name": "System (Automatic)"}]}

		self.assertEqual(resolve_ir_lane_roles(ir, ROLES), [])


class TestLaneRoleReadiness(FrappeTestCase):
	def test_a_user_name_is_reported_as_not_a_role(self):
		item = _lane_items(_map("Administrator"))["Administrator"]

		self.assertFalse(item["exists"])
		self.assertIn("User", item["detail"])

	def test_a_name_that_is_neither_role_nor_user_is_missing(self):
		item = _lane_items(_map("No Such Lane Role"))["No Such Lane Role"]

		self.assertFalse(item["exists"])

	def test_a_near_miss_lists_the_matching_roles(self):
		item = _lane_items(_map("System Manage"))["System Manage"]

		self.assertFalse(item["exists"])
		self.assertIn("System Manager", item["suggestions"])

	def test_an_enabled_role_passes(self):
		self.assertTrue(_lane_items(_map("System Manager"))["System Manager"]["exists"])

	def test_a_disabled_role_is_flagged(self):
		frappe.get_doc({"doctype": "Role", "role_name": "Zz Disabled Lane Role", "disabled": 1}).insert()

		item = _lane_items(_map("Zz Disabled Lane Role"))["Zz Disabled Lane Role"]

		self.assertFalse(item["exists"])


class TestDescribeLanesSuggestsRoles(FrappeTestCase):
	def _reply(self, *lane_names):
		ir = {"lanes": [{"id": f"l{i}", "name": n} for i, n in enumerate(lane_names)]}
		with patch.object(prosally_helpers.frappe, "get_all", return_value=ROLES):
			return prosally_helpers.describe_lanes([], "", ir)

	def test_a_near_miss_lane_gets_a_did_you_mean(self):
		text = self._reply("HR Manager", "HR Managr")

		self.assertIn("Lane 'HR Managr' is not a Role. Did you mean HR Manager?", text)

	def test_an_exact_role_and_an_unrelated_lane_get_no_suggestion(self):
		text = self._reply("HR Manager", "System (Automatic)")

		self.assertIn("Lanes drawn:", text)
		self.assertNotIn("Did you mean", text)
