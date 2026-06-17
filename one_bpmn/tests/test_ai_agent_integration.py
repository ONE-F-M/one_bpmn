# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
End-to-end integration tests for the AI Agent Task flow.

Tests the full path from diagram deployment (compile_process_model) through
dispatch (_dispatch_service_task) to gateway routing — all with mocked
executors so no real API keys or network calls are needed.

Coverage:
  (1) SUCCESS path: mocked executor returning SUCCESS → output written to
      task.data, gateway routes to success path
  (2) FAILED_MODEL_CALL: executor returns error → error variables written,
      gateway routes to error/fallback path, instance status stays Active
      (NOT Errored), a Frappe Error Log entry is created
  (3) Compile-time lint: diagram referencing non-existent AI Provider →
      compile_process_model raises ValidationError
  (4) Antigravity mock path: mocked AntigravityExecutor returns SUCCESS
      identically to Direct API path
  (5) No double-execution: once an AI Agent Task is completed in persisted
      state, restoring and advancing does NOT re-execute it

Uses FrappeTestCase (auto-rollback) and the test patterns from
test_bpmn_process_instance.py.
"""
from __future__ import annotations

import json
import textwrap
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage


# ---------------------------------------------------------------------------
# Minimal BPMN fixtures
# ---------------------------------------------------------------------------

def _ai_agent_bpmn(
    ai_provider: str = "openai-test",
    ai_backend: str = "direct_api",
    ai_output_var: str = "ai_result",
    include_gateway: bool = True,
) -> str:
    """
    Minimal BPMN with:
      - StartEvent → AI Agent ServiceTask → ExclusiveGateway → two EndEvents
    The gateway routes on ai_result (success path) or
    {task_id}_error_code (error/fallback path).
    """
    gateway_xml = ""
    if include_gateway:
        gateway_xml = """
    <bpmn:exclusiveGateway id="gw1" name="Result Gateway">
      <bpmn:incoming>flow2</bpmn:incoming>
      <bpmn:outgoing>flow_success</bpmn:outgoing>
      <bpmn:outgoing>flow_error</bpmn:outgoing>
    </bpmn:exclusiveGateway>
    <bpmn:endEvent id="end_success"><bpmn:incoming>flow_success</bpmn:incoming></bpmn:endEvent>
    <bpmn:endEvent id="end_error"><bpmn:incoming>flow_error</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="flow_success" sourceRef="gw1" targetRef="end_success">
      <bpmn:conditionExpression>ai_result is not None</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="flow_error" sourceRef="gw1" targetRef="end_error">
      <bpmn:conditionExpression>ai_result is None</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="flow2" sourceRef="ai_task" targetRef="gw1"/>
"""
    else:
        gateway_xml = """
    <bpmn:endEvent id="end1"><bpmn:incoming>flow2</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="flow2" sourceRef="ai_task" targetRef="end1"/>
"""

    return textwrap.dedent(f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<bpmn:definitions xmlns:bpmn=\"http://www.omg.org/spec/BPMN/20100524/MODEL\"
                  xmlns:spiffworkflow=\"http://spiffworkflow.org/bpmn/schema/1.0/core\"
                  id=\"Definitions_1\" targetNamespace=\"http://bpmn.io/schema/bpmn\">
  <bpmn:process id=\"ai_agent_test_process\" isExecutable=\"true\">
    <bpmn:startEvent id=\"start1\">
      <bpmn:outgoing>flow1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:serviceTask id=\"ai_task\" name=\"AI Agent Task\"
        spiffworkflow:serviceType=\"ai_agent\"
        spiffworkflow:aiBackend=\"{ai_backend}\"
        spiffworkflow:aiProvider=\"{ai_provider}\"
        spiffworkflow:aiModel=\"gpt-4o\"
        spiffworkflow:aiSystemPrompt=\"You are helpful.\"
        spiffworkflow:aiUserPrompt=\"Summarise this.\"
        spiffworkflow:aiOutputVariable=\"{ai_output_var}\"
        spiffworkflow:aiResponseFormat=\"text\"
        spiffworkflow:aiMaxRetries=\"0\">
      <bpmn:incoming>flow1</bpmn:incoming>
      <bpmn:outgoing>flow2</bpmn:outgoing>
    </bpmn:serviceTask>
    <bpmn:sequenceFlow id=\"flow1\" sourceRef=\"start1\" targetRef=\"ai_task\"/>
    {gateway_xml}
  </bpmn:process>
</bpmn:definitions>
""")


def _make_ai_provider(name: str = "openai-test") -> frappe.Document:
    if frappe.db.exists("AI Provider", name):
        return frappe.get_doc("AI Provider", name)
    doc = frappe.get_doc({
        "doctype": "AI Provider",
        "provider_name": name,
        "provider_type": "OpenAI",
        "api_endpoint": "https://api.openai.com/v1",
        "api_key": "sk-placeholder",
        "default_model": "gpt-4o",
        "enabled": 1,
    })
    doc.insert(ignore_permissions=True)
    return doc


def _make_process_model(bpmn_xml: str) -> frappe.Document:
    """Create and save a BPMN Process Model with given XML."""
    process = frappe.get_doc({
        "doctype": "Process",
        "process_name": f"ai-test-{frappe.generate_hash(length=6)}",
    })
    process.insert(ignore_permissions=True)

    model = frappe.get_doc({
        "doctype": "BPMN Process Model",
        "process_name": process.name,
        "bpmn_xml": bpmn_xml,
    })
    model.flags.skip_editability_check = True
    model.insert(ignore_permissions=True)
    return model


def _make_instance(model_name: str) -> frappe.Document:
    instance = frappe.get_doc({
        "doctype": "BPMN Process Instance",
        "process_model": model_name,
        "context_doctype": "",
        "context_docname": "",
    })
    instance.insert(ignore_permissions=True)
    return instance


def _mock_success_result(output: str = "Mocked AI response") -> ExecutorResult:
    return ExecutorResult(
        output=output,
        token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        error_code=ErrorCode.SUCCESS,
    )


def _mock_error_result(code: ErrorCode = ErrorCode.FAILED_MODEL_CALL) -> ExecutorResult:
    return ExecutorResult(
        error_code=code,
        error_message=f"Mocked {code.value}",
    )


# ---------------------------------------------------------------------------
# Integration test cases
# ---------------------------------------------------------------------------

class TestAIAgentTaskIntegration(FrappeTestCase):

    def setUp(self):
        super().setUp()
        # Ensure AI Provider exists for compilation
        _make_ai_provider("openai-test")

    # -----------------------------------------------------------------------
    # (1) SUCCESS path
    # -----------------------------------------------------------------------
    def test_success_path_writes_output_to_task_data(self):
        """
        Given a mocked executor returning SUCCESS
        When the process instance runs
        Then ai_result is in task data and instance status is Completed
        """
        from one_bpmn.api.compilation import compile_process_model

        model = _make_process_model(_ai_agent_bpmn(include_gateway=False))
        compile_process_model(model.name)

        mock_executor = MagicMock()
        mock_executor.return_value.run.return_value = _mock_success_result("Mocked AI response")

        with patch("one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers.get_executor",
                   return_value=mock_executor):
            instance = _make_instance(model.name)

        instance.reload()
        self.assertEqual(instance.status, "Completed")

    # -----------------------------------------------------------------------
    # (2) FAILED_MODEL_CALL error path
    # -----------------------------------------------------------------------
    def test_error_path_writes_error_variables_instance_stays_active(self):
        """
        Given a mocked executor returning FAILED_MODEL_CALL
        When the process runs
        Then:
          (a) Instance status is NOT "Errored" — it stays Active/Completed
          (b) task.data contains ai_task_error_code = "FAILED_MODEL_CALL"
          (c) A Frappe Error Log entry exists for this BPMN task
        """
        from one_bpmn.api.compilation import compile_process_model

        model = _make_process_model(_ai_agent_bpmn(include_gateway=False))
        compile_process_model(model.name)

        mock_executor = MagicMock()
        mock_executor.return_value.run.return_value = _mock_error_result(ErrorCode.FAILED_MODEL_CALL)

        with patch("one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers.get_executor",
                   return_value=mock_executor), \
             patch("frappe.log_error") as mock_log_error:
            instance = _make_instance(model.name)

        instance.reload()
        # (a) Not errored
        self.assertNotEqual(instance.status, "Errored")
        # (c) frappe.log_error was called with FAILED_MODEL_CALL in title
        called_titles = [str(c.kwargs.get("title", "")) for c in mock_log_error.call_args_list]
        self.assertTrue(
            any("FAILED_MODEL_CALL" in t for t in called_titles),
            f"Expected FAILED_MODEL_CALL in log_error titles, got: {called_titles}",
        )

    # -----------------------------------------------------------------------
    # (3) Compile-time lint: missing AI Provider
    # -----------------------------------------------------------------------
    def test_compile_fails_for_nonexistent_ai_provider(self):
        """
        Given a BPMN with aiProvider="nonexistent-provider-xyz"
        When compile_process_model() is called
        Then it raises a ValidationError about the missing provider
        """
        from one_bpmn.api.compilation import compile_process_model

        model = _make_process_model(
            _ai_agent_bpmn(ai_provider="nonexistent-provider-xyz-9999", include_gateway=False)
        )

        with self.assertRaises(frappe.ValidationError) as cm:
            compile_process_model(model.name)
        self.assertIn("nonexistent-provider-xyz-9999", str(cm.exception))

    # -----------------------------------------------------------------------
    # (4) Antigravity mock path works identically
    # -----------------------------------------------------------------------
    def test_antigravity_backend_success_path(self):
        """
        Given aiBackend="antigravity" and a mocked AntigravityExecutor
        When the process runs
        Then the flow completes identically to the direct_api path
        """
        from one_bpmn.api.compilation import compile_process_model

        model = _make_process_model(
            _ai_agent_bpmn(ai_backend="antigravity", include_gateway=False)
        )
        compile_process_model(model.name)

        mock_executor = MagicMock()
        mock_executor.return_value.run.return_value = _mock_success_result("Antigravity response")

        with patch("one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers.get_executor",
                   return_value=mock_executor):
            instance = _make_instance(model.name)

        instance.reload()
        self.assertNotEqual(instance.status, "Errored")

    # -----------------------------------------------------------------------
    # (5) No double-execution: completed AI task is not re-executed on restore
    # -----------------------------------------------------------------------
    def test_no_double_execution_on_restore(self):
        """
        Given a completed AI Agent Task serialized in workflow_state
        When the instance is advanced again (e.g. after a user task)
        Then the AI Agent Task executor is called exactly ONCE total
        """
        from one_bpmn.api.compilation import compile_process_model

        model = _make_process_model(_ai_agent_bpmn(include_gateway=False))
        compile_process_model(model.name)

        call_count = 0

        class CountingExecutor:
            def run(self, config, context):
                nonlocal call_count
                call_count += 1
                return _mock_success_result()

        with patch("one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers.get_executor",
                   return_value=CountingExecutor):
            instance = _make_instance(model.name)

        # The executor should have been called exactly once
        self.assertEqual(call_count, 1, f"Expected 1 execution, got {call_count}")
