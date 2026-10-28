# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Deploy and the readiness check require an Assignment Mode and a Task Action on every executable User Task."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import _validate_user_task_config
from one_bpmn.api.process_map_api import validate_bpmn_readiness

MAP = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
	xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="Defs">
	<bpmn:process id="user_task_gate" isExecutable="{executable}">
		<bpmn:startEvent id="Start" />
		<bpmn:userTask id="Activity_review" name="Review" {attrs} />
		<bpmn:endEvent id="End" />
	</bpmn:process>
</bpmn:definitions>"""

ACTIONS = 'spiffworkflow:taskActions="[{&quot;action&quot;:&quot;Approve&quot;}]"'
MODE = 'spiffworkflow:assigneeMode="User" spiffworkflow:assigneeUser="a@b.com"'


def _xml(attrs: str, executable: str = "true") -> str:
	return MAP.format(attrs=attrs, executable=executable)


def _user_task_items(xml: str) -> list:
	categories = validate_bpmn_readiness(xml)["categories"]
	return [i for c in categories if c["label"] == "User Task Configuration" for i in c["items"]]


class TestUserTaskConfigGate(FrappeTestCase):
	def test_deploy_is_blocked_without_an_assignment_mode(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			_validate_user_task_config(_xml(ACTIONS))

		self.assertIn('User Task "Review" requires an Assignment Mode.', str(ctx.exception))

	def test_deploy_is_blocked_without_a_task_action(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			_validate_user_task_config(_xml(MODE))

		self.assertIn("requires at least one Task Action", str(ctx.exception))

	def test_a_blank_action_row_does_not_count(self):
		blank = 'spiffworkflow:taskActions="[{&quot;action&quot;:&quot;&quot;}]"'

		with self.assertRaises(frappe.ValidationError):
			_validate_user_task_config(_xml(f"{MODE} {blank}"))

	def test_a_configured_task_passes(self):
		_validate_user_task_config(_xml(f"{MODE} {ACTIONS}"))

	def test_a_non_executable_process_is_exempt(self):
		_validate_user_task_config(_xml("", executable="false"))

	def test_readiness_check_fails_for_an_unconfigured_task(self):
		result = validate_bpmn_readiness(_xml(""))
		items = _user_task_items(_xml(""))

		self.assertEqual(len(items), 2)
		self.assertFalse(result["all_ready"])

	def test_readiness_check_has_no_user_task_category_when_configured(self):
		self.assertEqual(_user_task_items(_xml(f"{MODE} {ACTIONS}")), [])
