# Copyright (c) 2026, one-fm and contributors
"""Preview and dry run of an AI Agent Task from the editor: rendered prompts, the tool list, stubbed tool results."""

from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.process_maps import dry_run_ai_task, preview_ai_task
from one_bpmn.processa_engine.agent_runtime.executor import ErrorCode, ExecutorResult
from one_bpmn.processa_engine.agent_runtime.llm_types import ToolCallRecord, TurnRecord

XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
	xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="Defs_DryRun">
	<bpmn:process id="dry_run_process" isExecutable="true">
		<bpmn:startEvent id="Start" />
		<bpmn:serviceTask id="Agent_1" name="Triage" spiffworkflow:serviceType="ai_agent"
			spiffworkflow:aiToolsAdhoc="Tools_1"
			spiffworkflow:aiSystemPrompt="You triage tickets for {{ customer }}."
			spiffworkflow:aiUserPrompt="Triage ticket {{ ticket }}." />
		<bpmn:adHocSubProcess id="Tools_1" name="Triage tools">
			<bpmn:scriptTask id="lookup_customer" name="Look up customer"
				spiffworkflow:serverScript="Dry Run Probe Script"
				spiffworkflow:aiToolParams='{"properties": {"email": {"description": "Customer email"}}, "required": ["email"]}'>
				<bpmn:documentation>Find the customer record by email.</bpmn:documentation>
			</bpmn:scriptTask>
			<bpmn:userTask id="ask_agent" name="Ask a support agent" />
		</bpmn:adHocSubProcess>
		<bpmn:endEvent id="End" />
	</bpmn:process>
</bpmn:definitions>"""

SAMPLE = json.dumps({"customer": "Acme", "ticket": "T-42"})


class FakeExecutor:
	"""Calls each tool once with sample arguments and answers, standing in for the model."""

	seen = None

	def run(self, config, context):
		FakeExecutor.seen = config
		calls = [
			ToolCallRecord(name=t.name, arguments={"email": "a@acme.test"}, result=t.fn(email="a@acme.test"))
			for t in config.tools
		]
		return ExecutorResult(
			output="Routed to billing.",
			trace=[asdict(TurnRecord(role="assistant", content="Checking.", tool_calls=calls))],
		)


class TestAiTaskPreview(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		suffix = frappe.generate_hash(length=6)
		cls.model = (
			frappe.get_doc(
				{
					"doctype": "BPMN Process Model",
					"title": f"_Test Dry Run {suffix}",
					"process_id": f"_dry_{suffix}",
					"version": 1,
				}
			)
			.insert()
			.name
		)

	def setUp(self):
		frappe.set_user("Administrator")

	def _preview(self, **kwargs):
		return preview_ai_task(self.model, XML, "Agent_1", sample_variables=SAMPLE, **kwargs)

	def test_preview_renders_the_prompts_with_sample_variables(self):
		preview = self._preview(sample_message="My invoice is wrong")

		self.assertEqual(preview["system_prompt"], "You triage tickets for Acme.")
		self.assertIn("Triage ticket T-42.", preview["user_prompt"])
		self.assertTrue(preview["user_prompt"].endswith("User message: My invoice is wrong"))

	def test_preview_lists_every_tool_with_its_description_and_schema(self):
		tools = {t["name"]: t for t in self._preview()["tools"]}

		self.assertEqual(set(tools), {"lookup_customer", "ask_agent"})
		lookup = tools["lookup_customer"]
		self.assertEqual(lookup["description"], "Find the customer record by email.")
		self.assertEqual(lookup["parameters"]["required"], ["email"])
		self.assertEqual(lookup["parameters"]["properties"]["email"]["description"], "Customer email")
		self.assertFalse(lookup["human"])
		self.assertTrue(tools["ask_agent"]["human"])

	def test_unsaved_form_values_replace_the_shapes_own(self):
		preview = self._preview(
			form=json.dumps({"aiSystemPrompt": "Edited for {{ customer }}.", "aiOutputVariable": "x"})
		)

		self.assertEqual(preview["system_prompt"], "Edited for Acme.")

	def test_a_shape_that_is_not_an_ai_agent_task_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			preview_ai_task(self.model, XML, "Tools_1")

	def test_a_prompt_that_does_not_render_is_reported(self):
		form = json.dumps({"aiSystemPrompt": "{{ customer.name( }}"})

		with self.assertRaisesRegex(frappe.ValidationError, "System Prompt does not render"):
			self._preview(form=form)

	def test_dry_run_returns_the_transcript_with_sample_tool_results_and_saves_nothing(self):
		runs_before = frappe.db.count("AI Agent Run")
		messages_before = frappe.db.count("Chat Message")
		declared = json.dumps({"lookup_customer": {"customer": "Acme Ltd"}})

		with patch("one_bpmn.processa_engine.agent_runtime.dry_run.get_executor", return_value=FakeExecutor):
			result = dry_run_ai_task(
				self.model,
				XML,
				"Agent_1",
				sample_variables=SAMPLE,
				sample_message="Help",
				sample_results=declared,
			)

		results = {c["name"]: c["result"] for c in result["turns"][0]["tool_calls"]}
		self.assertEqual(results["lookup_customer"], '{"customer": "Acme Ltd"}')
		self.assertEqual(json.loads(results["ask_agent"])["dry_run"], True)
		self.assertEqual(
			(result["output"], result["error_code"]), ("Routed to billing.", ErrorCode.SUCCESS.value)
		)
		self.assertEqual(FakeExecutor.seen.system_prompt, "You triage tickets for Acme.")
		self.assertEqual(frappe.db.count("AI Agent Run"), runs_before)
		self.assertEqual(frappe.db.count("Chat Message"), messages_before)

	def test_a_prompt_cannot_reach_frappe(self):
		marker = f"_dry_run_probe_{frappe.generate_hash(length=6)}"
		for template in (
			"{{ frappe.set_user('Guest') }}",
			f"{{{{ frappe.db.set_value('BPMN Process Model', '{self.model}', 'description', '{marker}') }}}}",
		):
			with self.subTest(template=template), self.assertRaises(frappe.ValidationError):
				self._preview(form=json.dumps({"aiSystemPrompt": template}))
		self.assertEqual(frappe.session.user, "Administrator")
		self.assertNotEqual(frappe.db.get_value("BPMN Process Model", self.model, "description"), marker)

	def test_a_linked_configuration_the_user_cannot_read_is_refused(self):
		suffix = frappe.generate_hash(length=6)
		config = frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": f"Dry Run Probe {suffix}",
				"agent_id": f"dry_run_probe_{suffix}",
				"agent_framework": "Direct API",
				"agent_type": "Background",
				"enabled": 1,
				"system_prompt": "Hidden instructions.",
			}
		).insert()
		email = f"dryrun-owner-{suffix}@example.com"
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Owner", "send_welcome_email": 0}
		)
		user.append("roles", {"role": "Process Owner"})
		user.insert()
		self.addCleanup(lambda: frappe.set_user("Administrator"))
		frappe.set_user(email)

		with self.assertRaises(frappe.PermissionError):
			self._preview(form=json.dumps({"aiAgentConfig": config.name}))

	def test_a_failed_model_call_reaches_the_response(self):
		class FailingExecutor:
			def run(self, config, context):
				return ExecutorResult(
					error_code=ErrorCode.TIMEOUT, error_message="The model did not answer in time."
				)

		with patch(
			"one_bpmn.processa_engine.agent_runtime.dry_run.get_executor", return_value=FailingExecutor
		):
			result = dry_run_ai_task(
				self.model, XML, "Agent_1", sample_variables=SAMPLE, sample_message="Help"
			)

		self.assertEqual(result["error_code"], ErrorCode.TIMEOUT.value)
		self.assertEqual(result["error_message"], "The model did not answer in time.")
		self.assertEqual(result["turns"], [])

	def test_a_user_who_cannot_edit_the_map_is_refused(self):
		email = f"dryrun-{frappe.generate_hash(length=6)}@example.com"
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Dry", "send_welcome_email": 0}
		).insert()
		self.addCleanup(lambda: frappe.set_user("Administrator"))
		frappe.set_user(email)

		with self.assertRaises(frappe.PermissionError):
			preview_ai_task(self.model, XML, "Agent_1")
		with self.assertRaises(frappe.PermissionError):
			dry_run_ai_task(self.model, XML, "Agent_1")
