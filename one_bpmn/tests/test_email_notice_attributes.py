# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The Email Notification editor's Notice settings reach the task config, the AI configurer and the readiness check."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.bpmn_task_config import resolve_node_attrs
from one_bpmn.api.compilation import _extract_service_task_config
from one_bpmn.api.process_map_api import _extract_bpmn_references, validate_bpmn_readiness

FACTS = "[&quot;description&quot;, [&quot;allocated_to&quot;, &quot;assigned_by.full_name&quot;]]"
DETAILS = "[&quot;no_such_detail&quot;]"
SETTINGS = (
	'spiffworkflow:serviceType="send_email" spiffworkflow:emailUseDoctype="true" spiffworkflow:emailDoctype="ToDo" '
	'spiffworkflow:emailLayout="notice" spiffworkflow:emailHeadingEn="Closed" spiffworkflow:emailHeadingAr="مغلق" '
	f'spiffworkflow:emailFacts="{FACTS}" spiffworkflow:emailDetails="{DETAILS}" spiffworkflow:emailShowStatus="true"'
)


def _map(task_attrs=SETTINGS):
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
	xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="Defs">
	<bpmn:process id="notice_settings" isExecutable="true">
		<bpmn:startEvent id="Start" />
		<bpmn:serviceTask id="Activity_notice" name="Tell" {task_attrs} />
		<bpmn:endEvent id="End" />
	</bpmn:process>
</bpmn:definitions>"""


class TestEmailNoticeAttributes(FrappeTestCase):
	def test_facts_and_details_are_referenced_on_the_email_doctype(self):
		refs = _extract_bpmn_references(_map())

		fields = {f for dt, f in refs["fields"] if dt == "ToDo"}
		self.assertTrue({"description", "allocated_to", "no_such_detail"} <= fields)
		self.assertNotIn("assigned_by.full_name", fields)

	def test_an_unreadable_setting_names_the_task(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			_extract_bpmn_references(
				_map(SETTINGS.replace(f'emailDetails="{DETAILS}"', 'emailDetails="[broken"'))
			)
		self.assertIn("Activity_notice", str(ctx.exception))
		self.assertIn("emailDetails", str(ctx.exception))

	def test_the_readiness_check_lists_a_detail_missing_on_this_site(self):
		result = validate_bpmn_readiness(_map())

		fields = next(c for c in result["categories"] if c["label"] == "Fields")
		missing = {i["name"] for i in fields["items"] if not i["exists"]}
		self.assertIn("no_such_detail on ToDo", missing)

	def test_a_deployed_task_config_carries_the_notice_settings(self):
		config = _extract_service_task_config(_map())["Activity_notice"]

		self.assertEqual(config["emailLayout"], "notice")
		self.assertEqual(config["emailHeadingAr"], "مغلق")
		self.assertEqual(config["emailShowStatus"], "true")
		self.assertIn("allocated_to", config["emailFacts"])

	def test_the_ai_configurer_accepts_the_notice_keys(self):
		attrs, problems = resolve_node_attrs(
			{
				"id": "task_n",
				"type": "serviceTask",
				"name": "Tell",
				"config": {
					"serviceType": "send_email",
					"emailLayout": "notice",
					"emailSubjectAr": "تم",
					"emailHeadingEn": "Closed",
					"emailMessageEn": "The ToDo {{ doc.name }} is closed.",
					"emailFacts": ["description"],
					"emailAttachments": "true",
					"emailArabicEdited": ["emailHeadingAr"],
				},
			}
		)

		self.assertEqual(problems, [])
		self.assertEqual(attrs["emailLayout"], "notice")
		self.assertEqual(attrs["emailFacts"], '["description"]')
