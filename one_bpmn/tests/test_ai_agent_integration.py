# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
End-to-end integration tests for the AI Agent Task flow.

Tests the full path from diagram deployment (compile_process_model) through
dispatch (_dispatch_service_task) to gateway routing — all with mocked
executors so no real API keys or network calls are needed.

Coverage:
  (1) SUCCESS path: mocked executor returning SUCCESS → output written to
      task.data, gateway routes to the success end event
  (2) FAILED_MODEL_CALL: executor returns error → error variables written,
      gateway routes to the error/fallback end event, instance status stays
      Active/Completed (NOT Errored), a Frappe Error Log entry is created
  (3) Compile-time lint: diagram referencing non-existent AI Provider →
      compile_process_model raises ValidationError
  (4) Antigravity mock path: mocked AntigravityExecutor returns SUCCESS
      identically to Direct API path
  (5) No double-execution: once an AI Agent Task is completed in persisted
      state, restoring and advancing does NOT re-execute it

Notes on this bench:
  - get_executor is imported *inside* dispatch_ai_agent from
    one_bpmn.agents.executor, so that module is the correct patch target
    (patching the dispatchers namespace would not take effect).
  - frappe.log_error is patched in setUp: on this bench an Error Log insert
    triggers an onefm_mcp doc-event hook that imports a broken google.adk
    chain, which would crash any test whose dispatch logs an error.

Uses FrappeTestCase (auto-rollback).
"""
from __future__ import annotations

import json
import textwrap
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from SpiffWorkflow.util.task import TaskState

import one_bpmn.one_bpmn.engine as bpmn_engine
from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage

EXECUTOR_TARGET = "one_bpmn.agents.executor.get_executor"


# ---------------------------------------------------------------------------
# Minimal BPMN fixtures
# ---------------------------------------------------------------------------

def _ai_agent_bpmn(
    ai_provider: str = "openai-test",
    ai_backend: str = "direct_api",
    ai_output_var: str = "ai_result",
    flow: str = "end",
) -> str:
    """
    Build a minimal BPMN process whose single AI Agent ServiceTask is followed
    by one of three downstream shapes (`flow`):

      "end"     StartEvent → AI Agent Task → EndEvent
      "gateway" StartEvent → AI Agent Task → ExclusiveGateway → two EndEvents.
                The gateway routes to end_success when `ai_result is not None`;
                otherwise it falls through its default flow to end_error. The
                error branch is the default (not a condition on `ai_result is
                None`) because on failure ai_result is never written, and the
                engine treats a NameError in a condition as False.
      "user"    StartEvent → AI Agent Task → UserTask → EndEvent. Used to pause
                the instance after the AI task so it can be restored + advanced.
    """
    if flow == "gateway":
        downstream = """
    <bpmn:exclusiveGateway id="gw1" name="Result Gateway" default="flow_error">
      <bpmn:incoming>flow2</bpmn:incoming>
      <bpmn:outgoing>flow_success</bpmn:outgoing>
      <bpmn:outgoing>flow_error</bpmn:outgoing>
    </bpmn:exclusiveGateway>
    <bpmn:endEvent id="end_success"><bpmn:incoming>flow_success</bpmn:incoming></bpmn:endEvent>
    <bpmn:endEvent id="end_error"><bpmn:incoming>flow_error</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="flow_success" sourceRef="gw1" targetRef="end_success">
      <bpmn:conditionExpression>ai_result is not None</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="flow_error" sourceRef="gw1" targetRef="end_error"/>
    <bpmn:sequenceFlow id="flow2" sourceRef="ai_task" targetRef="gw1"/>
"""
    elif flow == "user":
        downstream = """
    <bpmn:userTask id="user1" name="Review"><bpmn:incoming>flow2</bpmn:incoming><bpmn:outgoing>flow3</bpmn:outgoing></bpmn:userTask>
    <bpmn:endEvent id="end1"><bpmn:incoming>flow3</bpmn:incoming></bpmn:endEvent>
    <bpmn:sequenceFlow id="flow2" sourceRef="ai_task" targetRef="user1"/>
    <bpmn:sequenceFlow id="flow3" sourceRef="user1" targetRef="end1"/>
"""
    else:
        downstream = """
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
    {downstream}
  </bpmn:process>
</bpmn:definitions>
""")


def _make_ai_provider(name: str = "openai-test") -> frappe.Document:
    if frappe.db.exists("AI Provider", name):
        return frappe.get_doc("AI Provider", name)
    doc = frappe.get_doc({
        "doctype": "AI Provider",
        "provider": name,
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
        "description": "AI Agent Task integration test process",
        "process_owner": "Administrator",
    })
    process.insert(ignore_permissions=True)

    suffix = frappe.generate_hash(length=6)
    model = frappe.get_doc({
        "doctype": "BPMN Process Model",
        "title": f"ai-test-model-{suffix}",
        "process_id": f"ai-test-{suffix}",
        "version": 1,
        "process_name": process.name,
        "bpmn_xml": bpmn_xml,
    })
    model.flags.skip_editability_check = True
    model.insert(ignore_permissions=True)
    return model


def _make_instance(model_name: str) -> frappe.Document:
    """Create AND start an instance. start() runs the engine (and dispatches the
    AI service task), so callers must enter their get_executor patch first.

    We seed ai_result=None into the root workflow data so the gateway's
    `ai_result is not None` condition is always evaluable: SpiffWorkflow's
    ExclusiveChoice raises on an undefined name (unlike ConditionalStartEvents,
    which treat it as False). On success the dispatcher overwrites ai_result;
    on failure it stays None and the gateway takes its default (error) flow —
    exactly what a real diagram would do by initialising its routing variable.
    """
    instance = frappe.get_doc({
        "doctype": "BPMN Process Instance",
        "process_model": model_name,
        "context_doctype": "",
        "context_docname": "",
    })
    instance.insert(ignore_permissions=True)
    instance.start(initial_data={"ai_result": None})
    return instance


def _completed_bpmn_ids(instance: frappe.Document) -> set:
    """Restore the persisted workflow and return the bpmn ids of COMPLETED tasks."""
    wf = bpmn_engine.restore_workflow(
        workflow_state=json.loads(instance.workflow_state),
        context_doctype="",
        context_docname="",
        script_task_extensions={},
        initiated_by="Administrator",
    )
    return {
        getattr(t.task_spec, "bpmn_id", "")
        for t in wf.get_tasks()
        if t.state == TaskState.COMPLETED
    }


def _success_executor(output: str = "Mocked AI response") -> MagicMock:
    """A get_executor stand-in whose executor instance returns SUCCESS."""
    result = ExecutorResult(
        output=output,
        token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        error_code=ErrorCode.SUCCESS,
    )
    cls = MagicMock()
    cls.return_value.run.return_value = result
    return cls


def _error_executor(code: ErrorCode = ErrorCode.FAILED_MODEL_CALL) -> MagicMock:
    result = ExecutorResult(error_code=code, error_message=f"Mocked {code.value}")
    cls = MagicMock()
    cls.return_value.run.return_value = result
    return cls


# ---------------------------------------------------------------------------
# Integration test cases
# ---------------------------------------------------------------------------

class TestAIAgentTaskIntegration(FrappeTestCase):

    def setUp(self):
        super().setUp()
        _make_ai_provider("openai-test")
        # Neutralize frappe.log_error: on this bench an Error Log insert fires
        # an onefm_mcp hook that imports a broken google.adk chain.
        patcher = patch.object(frappe, "log_error")
        patcher.start()
        self.addCleanup(patcher.stop)

    # -----------------------------------------------------------------------
    # (1) SUCCESS path → output in task.data, gateway routes to success end
    # -----------------------------------------------------------------------
    def test_success_routes_to_success_end_and_writes_output(self):
        from one_bpmn.api.compilation import compile_process_model

        model = _make_process_model(_ai_agent_bpmn(flow="gateway"))
        compile_process_model(model.name)

        with patch(EXECUTOR_TARGET, return_value=_success_executor("Mocked AI response")):
            instance = _make_instance(model.name)

        instance.reload()
        self.assertEqual(instance.status, "Completed")
        # output variable written into task data (survives serialization)
        self.assertIn("ai_result", instance.workflow_state)
        self.assertIn("Mocked AI response", instance.workflow_state)
        # gateway routed to the success end event, not the error one
        completed = _completed_bpmn_ids(instance)
        self.assertIn("end_success", completed)
        self.assertNotIn("end_error", completed)

    # -----------------------------------------------------------------------
    # (2) FAILED_MODEL_CALL → error vars, gateway routes to error end, log
    # -----------------------------------------------------------------------
    def test_error_routes_to_error_end_and_writes_error_vars(self):
        from one_bpmn.api.compilation import compile_process_model

        model = _make_process_model(_ai_agent_bpmn(flow="gateway"))
        compile_process_model(model.name)

        with patch(EXECUTOR_TARGET, return_value=_error_executor(ErrorCode.FAILED_MODEL_CALL)), \
             patch("frappe.log_error") as mock_log_error:
            instance = _make_instance(model.name)

        instance.reload()
        # (a) instance not errored — failures route, they don't crash
        self.assertNotEqual(instance.status, "Errored")
        # (b) error variables written into task data
        self.assertIn("ai_task_error_code", instance.workflow_state)
        self.assertIn("FAILED_MODEL_CALL", instance.workflow_state)
        # (c) an Error Log entry was requested with the error code in the title
        titles = [str(c.kwargs.get("title", "")) for c in mock_log_error.call_args_list]
        self.assertTrue(
            any("FAILED_MODEL_CALL" in t for t in titles),
            f"Expected FAILED_MODEL_CALL in log_error titles, got: {titles}",
        )
        # (d) gateway routed to the error/fallback end event
        completed = _completed_bpmn_ids(instance)
        self.assertIn("end_error", completed)
        self.assertNotIn("end_success", completed)

    # -----------------------------------------------------------------------
    # (3) Compile-time lint: missing AI Provider
    # -----------------------------------------------------------------------
    def test_compile_fails_for_nonexistent_ai_provider(self):
        from one_bpmn.api.compilation import compile_process_model

        model = _make_process_model(
            _ai_agent_bpmn(ai_provider="nonexistent-provider-xyz-9999")
        )
        with self.assertRaises(frappe.ValidationError) as cm:
            compile_process_model(model.name)
        self.assertIn("nonexistent-provider-xyz-9999", str(cm.exception))

    # -----------------------------------------------------------------------
    # (4) Antigravity mock path works identically
    # -----------------------------------------------------------------------
    def test_antigravity_backend_success_path(self):
        from one_bpmn.api.compilation import compile_process_model

        model = _make_process_model(_ai_agent_bpmn(ai_backend="antigravity", flow="gateway"))
        compile_process_model(model.name)

        with patch(EXECUTOR_TARGET, return_value=_success_executor("Antigravity response")):
            instance = _make_instance(model.name)

        instance.reload()
        self.assertEqual(instance.status, "Completed")
        self.assertIn("Antigravity response", instance.workflow_state)
        self.assertIn("end_success", _completed_bpmn_ids(instance))

    # -----------------------------------------------------------------------
    # (5) No double-execution: completed AI task is not re-executed on restore
    # -----------------------------------------------------------------------
    def test_no_double_execution_on_restore_and_advance(self):
        from one_bpmn.api.compilation import compile_process_model

        model = _make_process_model(_ai_agent_bpmn(flow="user"))
        compile_process_model(model.name)

        call_count = 0

        class CountingExecutor:
            def run(self, config, context):
                nonlocal call_count
                call_count += 1
                return ExecutorResult(output="x", error_code=ErrorCode.SUCCESS)

        with patch(EXECUTOR_TARGET, return_value=CountingExecutor):
            instance = _make_instance(model.name)

            # The instance pauses at the User Task; the AI task already ran once.
            instance.reload()
            self.assertEqual(instance.status, "Active")
            self.assertEqual(call_count, 1)

            # Restore from persisted state and advance past the User Task.
            waiting = [r for r in instance.active_tasks if r.status == "Waiting"]
            self.assertTrue(waiting, "expected a waiting User Task after the AI task")
            instance.advance(waiting[0].task_id, {})

        instance.reload()
        # The AI Agent Task must NOT have been re-executed on restore.
        self.assertEqual(call_count, 1, f"Expected 1 execution, got {call_count}")
        self.assertEqual(instance.status, "Completed")
