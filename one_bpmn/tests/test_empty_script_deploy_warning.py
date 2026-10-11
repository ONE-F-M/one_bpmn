# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Deploy warns about Script Tasks that have no script."""

from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import _check_script_tasks_have_a_script
from one_bpmn.api.process_map_api import validate_bpmn_readiness

MAP = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
	xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="Defs">
	<bpmn:process id="script_readiness" isExecutable="true">
		<bpmn:startEvent id="Start" />
		{tasks}
		<bpmn:endEvent id="End" />
	</bpmn:process>
</bpmn:definitions>"""

EMPTY_TASK = '<bpmn:scriptTask id="Activity_empty" name="Calculate Total" />'


class TestEmptyScriptDeployWarning(FrappeTestCase):
	def _details(self, tasks: str) -> list:
		return [w["detail"] for w in _check_script_tasks_have_a_script(MAP.format(tasks=tasks))]

	def test_a_script_task_with_no_script_is_flagged(self):
		details = self._details(EMPTY_TASK)

		self.assertEqual(len(details), 1)
		self.assertIn("'Activity_empty' has no script", details[0])

	def test_a_blank_inline_script_counts_as_empty(self):
		details = self._details('<bpmn:scriptTask id="Activity_blank"><bpmn:script>  </bpmn:script></bpmn:scriptTask>')

		self.assertEqual(len(details), 1)

	def test_a_server_script_or_an_inline_script_is_enough(self):
		tasks = (
			'<bpmn:scriptTask id="Activity_server" spiffworkflow:serverScript="Set Status" />'
			'<bpmn:scriptTask id="Activity_inline"><bpmn:script>result["x"] = 1</bpmn:script></bpmn:scriptTask>'
		)

		self.assertEqual(self._details(tasks), [])

	def test_the_readiness_check_lists_an_empty_script_task_by_name_without_blocking(self):
		result = validate_bpmn_readiness(MAP.format(tasks=EMPTY_TASK))

		scripts = next(c for c in result["categories"] if c["label"] == "Script Tasks")
		self.assertEqual(scripts["items"][0]["name"], "Calculate Total")
		self.assertEqual(scripts["items"][0]["type"], "warning")
		self.assertIn("no script", scripts["items"][0]["detail"])
		self.assertTrue(result["all_ready"])
