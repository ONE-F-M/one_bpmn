# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Lane names are checked against the site's enabled Roles, with suggestions for near misses."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.ai_agent_registry.definitions.prosally import tools_prompts
from one_bpmn.ai_agent_registry.provisioning.bpmn_task_config import match_lane_role, resolve_ir_lane_roles
from one_bpmn.api.process_maps import validate_bpmn_readiness

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


def _task_map(role, task):
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="Defs">
	<bpmn:process id="lane_perms" isExecutable="true">
		<bpmn:laneSet id="LaneSet_1">
			<bpmn:lane id="Lane_1" name="{role}"><bpmn:flowNodeRef>Task_1</bpmn:flowNodeRef></bpmn:lane>
		</bpmn:laneSet>
		<bpmn:startEvent id="Start" />
		{task}
		<bpmn:endEvent id="End" />
	</bpmn:process>
</bpmn:definitions>"""


class TestLaneRolePermissionWarnings(FrappeTestCase):
	USER_TASK = '<bpmn:userTask id="Task_1" name="Review" spiffworkflow:targetDoctype="ToDo" />'

	def _make_role(self):
		frappe.get_doc({"doctype": "Role", "role_name": "Zz No Perm Lane Role"}).insert(ignore_if_duplicate=True)
		self.addCleanup(frappe.delete_doc, "Role", "Zz No Perm Lane Role", force=True)

	def _warnings(self, role, task):
		return [i for i in _lane_items(_task_map(role, task)).values() if i["type"] == "warning"]

	def test_a_role_without_doctype_permission_is_warned_not_blocked(self):
		self._make_role()

		warnings = self._warnings("Zz No Perm Lane Role", self.USER_TASK)

		self.assertEqual(len(warnings), 1)
		self.assertIn("read, write", warnings[0]["detail"])
		self.assertTrue(warnings[0]["exists"])

	def test_a_role_with_the_permissions_is_not_warned(self):
		self.assertEqual(self._warnings("System Manager", self.USER_TASK), [])

	def test_a_service_task_on_a_submittable_doctype_needs_submit(self):
		self._make_role()
		task = (
			'<bpmn:serviceTask id="Task_1" name="Approve" spiffworkflow:serviceType="apply_workflow" '
			'spiffworkflow:serviceTargetDoctype="Sales Invoice" />'
		)

		warnings = self._warnings("Zz No Perm Lane Role", task)

		self.assertIn("submit", warnings[0]["detail"])

	def test_a_script_task_needs_the_doctypes_its_code_names(self):
		self._make_role()
		task = (
			'<bpmn:scriptTask id="Task_1" name="Log">'
			"<bpmn:script>doc = frappe.get_doc(\"ToDo\", name)\nnew = frappe.new_doc(\"Note\")</bpmn:script>"
			"</bpmn:scriptTask>"
		)

		warnings = self._warnings("Zz No Perm Lane Role", task)

		details = {w["name"]: w["detail"] for w in warnings}
		self.assertIn("read", details["Zz No Perm Lane Role on ToDo"])
		self.assertIn("create", details["Zz No Perm Lane Role on Note"])

	def test_a_script_that_names_no_doctype_is_not_warned(self):
		self._make_role()
		task = '<bpmn:scriptTask id="Task_1" name="Calc"><bpmn:script>total = 1 + 2</bpmn:script></bpmn:scriptTask>'

		self.assertEqual(self._warnings("Zz No Perm Lane Role", task), [])

	def test_a_field_level_permission_does_not_count(self):
		self._make_role()
		perm = frappe.get_doc({
			"doctype": "Custom DocPerm",
			"parent": "ToDo",
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": "Zz No Perm Lane Role",
			"permlevel": 1,
			"read": 1,
			"write": 1,
		}).insert()
		self.addCleanup(frappe.clear_cache, doctype="ToDo")
		self.addCleanup(frappe.delete_doc, "Custom DocPerm", perm.name, force=True)
		frappe.clear_cache(doctype="ToDo")

		warnings = self._warnings("Zz No Perm Lane Role", self.USER_TASK)

		self.assertEqual(len(warnings), 1)
		self.assertIn("read, write", warnings[0]["detail"])


class TestDescribeLanesSuggestsRoles(FrappeTestCase):
	def _reply(self, *lane_names):
		ir = {"lanes": [{"id": f"l{i}", "name": n} for i, n in enumerate(lane_names)]}
		with patch.object(tools_prompts.frappe, "get_all", return_value=ROLES):
			return tools_prompts.describe_lanes([], "", ir)

	def test_a_near_miss_lane_gets_a_did_you_mean(self):
		text = self._reply("HR Manager", "HR Managr")

		self.assertIn("Lane 'HR Managr' is not a Role. Did you mean HR Manager?", text)
		self.assertIn("Lane Role field", text)

	def test_an_exact_role_and_an_unrelated_lane_get_no_suggestion(self):
		text = self._reply("HR Manager", "System (Automatic)")

		self.assertIn("Lanes drawn:", text)
		self.assertNotIn("Did you mean", text)
		self.assertNotIn("Lane Role field", text)
