# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A Docu writer that could not reach its model is reported as that failure, not as a request to rephrase."""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

from one_bpmn.agents.observability import _tool_call_status
from one_bpmn.agents.shape_tools import execute_shape
from one_bpmn.agents.turn_state import get_turn, set_turn
from one_bpmn.api.server_script_api import turn_failure_text
from one_bpmn.tests.test_failed_tool_turn import ChatTurnFixture

PROVIDER_MESSAGE = "AI Model 'claude-sonnet-5' is unavailable: Anthropic rejected the API key (HTTP 401): invalid x-api-key."
WRITER_CFG = {"serviceType": "ai_agent", "aiAgentConfig": "Docu – Schema Writer"}


def _site_script(name: str) -> str:
	# The Docu scripts ship with the map export, so the test runs the copy on this site.
	return frappe.db.get_value("Server Script", name, "script")


class DocuTurnFixture(ChatTurnFixture):
	def setUp(self):
		super().setUp()
		self.instance.name = f"docu-writer-test-{frappe.generate_hash(length=6)}"

	def _writer_fails(self, error_code: str, error_message: str):
		def dispatch(task, task_cfg):
			task.data["write_schema_error_code"] = error_code
			task.data["write_schema_error_message"] = error_message
			task.data["write_schema_output"] = None

		self.instance._dispatch_service_task = dispatch
		return execute_shape(self.instance, "write_schema", dict(WRITER_CFG), {})

	def _finalize(self) -> dict:
		self._exec(_site_script("Docu – Tool Finalize"))
		return get_turn(self.conversation.name)["output"]


class TestAWriterThatCouldNotReachItsModelIsAFailedToolCall(DocuTurnFixture):
	def test_the_tool_result_is_an_error_carrying_the_writer_code(self):
		out = self._writer_fails("PROVIDER_DISABLED", PROVIDER_MESSAGE)

		self.assertEqual(_tool_call_status(out), "Error")
		self.assertEqual(json.loads(out)["error_code"], "PROVIDER_DISABLED")
		tool_error = get_turn(self.conversation.name)["tool_error"]
		self.assertEqual(tool_error["tool"], "write_schema")
		self.assertEqual(tool_error["error_code"], "PROVIDER_DISABLED")
		self.assertEqual(tool_error["error"], PROVIDER_MESSAGE)


class TestDocuFinalizeNamesTheFailure(DocuTurnFixture):
	def test_an_unavailable_model_is_named_and_the_user_is_not_asked_to_rephrase(self):
		self._writer_fails("PROVIDER_DISABLED", PROVIDER_MESSAGE)

		output = self._finalize()

		self.assertIn("AI model Docu uses to write forms is unavailable", output["response"])
		self.assertNotIn("rephrase", output["response"].lower())
		self.assertEqual(output["error_code"], "PROVIDER_DISABLED")

	def test_a_timeout_reads_as_the_chat_timeout_message(self):
		self._writer_fails("TIMEOUT", "The model did not answer in time.")

		self.assertEqual(self._finalize()["response"], turn_failure_text("TIMEOUT", "The model did not answer in time."))

	def test_a_design_that_failed_validation_keeps_the_safety_refusal(self):
		set_turn(
			self.conversation.name,
			{"intent": "CREATE", "schema_safe": False, "violations": ["field #1: missing 'label'."]},
		)

		output = self._finalize()

		self.assertTrue(output["response"].startswith("I couldn't produce a safe form definition"))
		self.assertIsNone(output["error_code"])


class TestDocuSaveResponseMarksTheRunAsError(DocuTurnFixture):
	def _run(self) -> str:
		run = frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"bpmn_id": "run_docu_agent",
				"instance": self.instance.name,
				"status": "Success",
				"started_at": now_datetime(),
			}
		)
		# The fixture's instance is not a stored record, so the row is written directly.
		run.db_insert()
		return run.name

	def _save_response(self):
		self._exec(
			_site_script("Docu – Save Response"),
			task_data={"conversation_id": self.conversation.name},
			instance=self.instance,
		)

	def test_a_turn_ending_on_a_writer_error_is_an_error_run(self):
		run = self._run()
		self._writer_fails("PROVIDER_DISABLED", PROVIDER_MESSAGE)
		self._finalize()

		self._save_response()

		status, code, message = frappe.db.get_value("AI Agent Run", run, ["status", "error_code", "error_message"])
		self.assertEqual((status, code, message), ("Error", "PROVIDER_DISABLED", PROVIDER_MESSAGE))

	def test_a_refused_design_leaves_the_run_a_success(self):
		run = self._run()
		set_turn(self.conversation.name, {"intent": "CREATE", "schema_safe": False, "violations": ["x"]})
		self._finalize()

		self._save_response()

		self.assertEqual(frappe.db.get_value("AI Agent Run", run, "status"), "Success")
