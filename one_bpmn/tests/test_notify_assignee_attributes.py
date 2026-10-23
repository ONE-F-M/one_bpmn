# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The Notification Editor's settings reach the task config, the AI configurer and the readiness check."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.bpmn_task_config import resolve_node_attrs
from one_bpmn.api.compilation import _extract_user_task_config
from one_bpmn.api.process_map_api import _extract_bpmn_references, validate_bpmn_readiness
from one_bpmn.api.utils import get_doctype_email_thread

FACTS = "[&quot;description&quot;, [&quot;allocated_to&quot;, &quot;assigned_by.full_name&quot;]]"
DETAILS = "[&quot;reference_type&quot;]"
ACTIONS = (
	"{&quot;Close&quot;: {&quot;primary&quot;: true, &quot;reason&quot;: true, &quot;reasonField&quot;: &quot;no_such_reason&quot;},"
	" &quot;Cancel&quot;: {&quot;reason&quot;: false}}"
)


def _map(start_attrs="", task_attrs=""):
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
	xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="Defs">
	<bpmn:process id="notify_settings" isExecutable="true">
		<bpmn:startEvent id="Start" {start_attrs} />
		<bpmn:userTask id="Activity_review" name="Review" spiffworkflow:notifyAssignee="true" {task_attrs} />
		<bpmn:endEvent id="End" />
	</bpmn:process>
</bpmn:definitions>"""


SETTINGS = (
	f'spiffworkflow:notifyLayout="card" spiffworkflow:notifyQuestionEn="Close {{{{ doc.name }}}}?" '
	f'spiffworkflow:notifyFacts="{FACTS}" spiffworkflow:notifyDetails="{DETAILS}" '
	f'spiffworkflow:notifyActions="{ACTIONS}" spiffworkflow:notifyTokenHours="24"'
)


class TestNotifyAssigneeAttributes(FrappeTestCase):
	def test_facts_details_and_reason_fields_are_referenced_on_the_trigger_doctype(self):
		refs = _extract_bpmn_references(_map('spiffworkflow:triggerDoctype="ToDo"', SETTINGS))

		fields = {f for dt, f in refs["fields"] if dt == "ToDo"}
		self.assertEqual(
			fields, {"description", "allocated_to", "assigned_by", "reference_type", "no_such_reason"}
		)

	def test_the_task_target_doctype_is_used_when_the_start_event_has_none(self):
		refs = _extract_bpmn_references(_map(task_attrs=f'spiffworkflow:targetDoctype="ToDo" {SETTINGS}'))

		self.assertIn(("ToDo", "no_such_reason"), refs["fields"])

	def test_an_unreadable_setting_names_the_task(self):
		xml = _map('spiffworkflow:triggerDoctype="ToDo"', 'spiffworkflow:notifyFacts="[broken"')

		with self.assertRaises(frappe.ValidationError) as ctx:
			_extract_bpmn_references(xml)
		self.assertIn("Activity_review", str(ctx.exception))
		self.assertIn("notifyFacts", str(ctx.exception))

	def test_the_readiness_check_lists_a_reason_field_missing_on_this_site(self):
		result = validate_bpmn_readiness(_map('spiffworkflow:triggerDoctype="ToDo"', SETTINGS))

		fields = next(c for c in result["categories"] if c["label"] == "Fields")
		missing = {i["name"] for i in fields["items"] if not i["exists"]}
		self.assertEqual(missing, {"no_such_reason on ToDo"})

	def test_a_deployed_task_config_carries_every_setting(self):
		config = _extract_user_task_config(_map(task_attrs=SETTINGS))["Activity_review"]

		self.assertEqual(config["notifyLayout"], "card")
		self.assertEqual(config["notifyTokenHours"], "24")
		self.assertEqual(config["notifyQuestionEn"], "Close {{ doc.name }}?")
		self.assertIn("allocated_to", config["notifyFacts"])
		self.assertIn("no_such_reason", config["notifyActions"])

	def test_the_ai_configurer_accepts_the_new_settings(self):
		attrs, problems = resolve_node_attrs(
			{
				"id": "task_u",
				"type": "userTask",
				"name": "Review",
				"config": {
					"notifyLayout": "card",
					"notifySubjectAr": "مراجعة",
					"notifyFacts": ["description", ["allocated_to", "assigned_by.full_name"]],
					"notifyActions": {"Close": {"primary": True}},
					"notifyTokenHours": 24,
				},
			}
		)

		self.assertEqual(problems, [])
		self.assertEqual(attrs["notifyLayout"], "card")
		self.assertEqual(attrs["notifyFacts"], '["description", ["allocated_to", "assigned_by.full_name"]]')
		self.assertEqual(attrs["notifyTokenHours"], "24")

	def test_the_editor_learns_whether_a_doctype_keeps_an_email_thread(self):
		self.assertEqual(
			get_doctype_email_thread("HD Ticket"), {"email_append_to": True, "sender_field": "raised_by"}
		)
		self.assertEqual(get_doctype_email_thread("Role"), {"email_append_to": False, "sender_field": ""})

	def test_only_a_process_map_editor_may_ask(self):
		with self.set_user("Guest"), self.assertRaises(frappe.PermissionError):
			get_doctype_email_thread("HD Ticket")
