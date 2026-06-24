"""
Tests for dispatch_ai_agent observability integration.

Verifies that dispatch_ai_agent creates AI Agent Run and Step records
via the instrumentation layer when the executor is mocked.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch

from one_bpmn.agents.executor import ErrorCode, ExecutorResult


class TestDispatchObservability(FrappeTestCase):

	def setUp(self):
		# Create a minimal BPMN Process Instance as context
		self.instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_id": f"test-{frappe.generate_hash(length=6)}",
			"status": "Running",
		})
		self.instance.flags.ignore_mandatory = True
		self.instance.insert(ignore_permissions=True, ignore_mandatory=True)

		self.mock_task = frappe._dict({"data": {}})
		self.bpmn_id = "Activity_1A2B3C"
		self.task_cfg = {
			"serviceType": "ai_agent",
			"aiBackend": "direct_api",
			"aiProvider": "",
			"aiModel": "gpt-4o",
			"aiSystemPrompt": "Be helpful.",
			"aiUserPrompt": "Say hi.",
			"aiOutputVariable": "ai_result",
		}

	def _run_dispatch(self, mock_result: ExecutorResult):
		"""Run dispatch_ai_agent with a mocked executor."""
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import dispatch_ai_agent

		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=mock_result,
		):
			dispatch_ai_agent(self.instance, self.mock_task, self.task_cfg, self.bpmn_id)

	def test_success_creates_run_and_steps(self):
		"""dispatch_ai_agent with a mocked successful executor creates 1 Run
		(status=Success) and 3 Steps (system, user, assistant)."""
		result = ExecutorResult(
			output="Hi there!",
			error_code=ErrorCode.SUCCESS,
		)
		self._run_dispatch(result)

		# Check Run
		runs = frappe.get_all(
			"AI Agent Run",
			filters={"instance": self.instance.name, "bpmn_id": self.bpmn_id},
			pluck="name",
		)
		self.assertEqual(len(runs), 1)
		run = frappe.get_doc("AI Agent Run", runs[0])
		self.assertEqual(run.status, "Success")

		# Check Steps
		steps = frappe.get_all(
			"AI Agent Step",
			filters={"run": runs[0]},
			fields=["role", "step_index"],
			order_by="step_index asc",
		)
		self.assertEqual(len(steps), 3)
		self.assertEqual(steps[0].role, "system")
		self.assertEqual(steps[1].role, "user")
		self.assertEqual(steps[2].role, "assistant")

		# Check backward compat: task.data has output
		self.assertIn("ai_result", self.mock_task.data)
		self.assertEqual(self.mock_task.data["ai_result"], "Hi there!")

	def test_error_creates_run_and_partial_steps(self):
		"""dispatch_ai_agent with a mocked error executor creates 1 Run
		(status=Error) and 2 Steps (system, user — no assistant)."""
		result = ExecutorResult(
			output=None,
			error_code=ErrorCode.FAILED_MODEL_CALL,
			error_message="Model unavailable",
		)
		self._run_dispatch(result)

		# Check Run
		runs = frappe.get_all(
			"AI Agent Run",
			filters={"instance": self.instance.name, "bpmn_id": self.bpmn_id},
			pluck="name",
		)
		self.assertEqual(len(runs), 1)
		run = frappe.get_doc("AI Agent Run", runs[0])
		self.assertEqual(run.status, "Error")
		self.assertEqual(run.error_code, "FAILED_MODEL_CALL")

		# Check Steps — only system + user (no assistant on error)
		steps = frappe.get_all(
			"AI Agent Step",
			filters={"run": runs[0]},
			fields=["role", "step_index"],
			order_by="step_index asc",
		)
		self.assertEqual(len(steps), 2)
		self.assertEqual(steps[0].role, "system")
		self.assertEqual(steps[1].role, "user")

		# Check backward compat: task.data has error code
		self.assertIn(f"{self.bpmn_id}_error_code", self.mock_task.data)
		self.assertEqual(self.mock_task.data[f"{self.bpmn_id}_error_code"], "FAILED_MODEL_CALL")
		self.assertIn(f"{self.bpmn_id}_error_message", self.mock_task.data)

	def test_backwards_compat_output_and_error(self):
		"""Task.data still contains output variable and frappe.log_error is still called."""
		import frappe

		result = ExecutorResult(
			output="OK",
			error_code=ErrorCode.SUCCESS,
		)
		self._run_dispatch(result)
		self.assertIn("ai_result", self.mock_task.data)
		self.assertEqual(self.mock_task.data["ai_result"], "OK")
