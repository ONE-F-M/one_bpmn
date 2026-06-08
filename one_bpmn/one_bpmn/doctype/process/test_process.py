# Copyright (c) 2025, ONE FM and Contributors
# See license.txt

import json
from unittest.mock import MagicMock, patch
import frappe
from frappe.tests.utils import FrappeTestCase


class TestProcess(FrappeTestCase):

	@patch("one_bpmn.ai_executor.requests.post")
	def test_ai_agent_task_and_subprocess(self, mock_post):
		# Define mock post side effect to simulate ReAct loop
		def mock_post_side_effect(url, headers=None, json=None, timeout=None):
			res = MagicMock()
			res.status_code = 200
			
			messages = json.get("messages", [])
			last_msg = messages[-1] if messages else {}
			
			if last_msg.get("role") == "user":
				# First turn -> return tool call for Sub_Tool_1
				res.json.return_value = {
					"choices": [{
						"message": {
							"role": "assistant",
							"content": None,
							"tool_calls": [{
								"id": "call_123",
								"type": "function",
								"function": {
									"name": "Sub_Tool_1",
									"arguments": "{\"threshold\": 1000}"
								}
							}]
						}
					}]
				}
			else:
				# Second turn -> return final answer
				res.json.return_value = {
					"choices": [{
						"message": {
							"role": "assistant",
							"content": "Audit completed: volume is above threshold."
						}
					}]
				}
			return res

		mock_post.side_effect = mock_post_side_effect

		# 1. Create a mock BPMN Process Model with custom AI Agent adHocSubProcess
		xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
                  id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_AI_Agent" isExecutable="true">
    <bpmn:startEvent id="Start_1">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="AI_Subprocess_1" />
    <bpmn:adHocSubProcess id="AI_Subprocess_1" name="AI Subprocess 1" spiffworkflow:serviceType="ai_agent" spiffworkflow:aiExecutionMode="direct_api" spiffworkflow:aiLlmProvider="openai_compatible" spiffworkflow:aiModelId="mock-model" spiffworkflow:aiUserMessage="Solve this" spiffworkflow:aiContextVariable="output_var_sub" spiffworkflow:aiApiEndpoint="http://mock-api/v1" spiffworkflow:aiApiKeySecret="mock-key">
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
      <bpmn:startEvent id="Sub_Start_1">
        <bpmn:outgoing>Sub_Flow_1</bpmn:outgoing>
      </bpmn:startEvent>
      <bpmn:sequenceFlow id="Sub_Flow_1" sourceRef="Sub_Start_1" targetRef="Sub_Tool_1" />
      <bpmn:serviceTask id="Sub_Tool_1" name="Audit Volume">
        <bpmn:incoming>Sub_Flow_1</bpmn:incoming>
        <bpmn:outgoing>Sub_Flow_2</bpmn:outgoing>
        <bpmn:extensionElements>
          <spiffworkflow:preVariableMapping>
            <spiffworkflow:mapping>
              <spiffworkflow:target>threshold</spiffworkflow:target>
              <spiffworkflow:expression>fromAi("threshold", "Volume threshold", "number")</spiffworkflow:expression>
            </spiffworkflow:mapping>
          </spiffworkflow:preVariableMapping>
        </bpmn:extensionElements>
      </bpmn:serviceTask>
      <bpmn:sequenceFlow id="Sub_Flow_2" sourceRef="Sub_Tool_1" targetRef="Sub_End_1" />
      <bpmn:endEvent id="Sub_End_1">
        <bpmn:incoming>Sub_Flow_2</bpmn:incoming>
      </bpmn:endEvent>
    </bpmn:adHocSubProcess>
    <bpmn:sequenceFlow id="Flow_2" sourceRef="AI_Subprocess_1" targetRef="End_1" />
    <bpmn:endEvent id="End_1">
      <bpmn:incoming>Flow_2</bpmn:incoming>
    </bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""

		model = frappe.new_doc("BPMN Process Model")
		model.title = "Test AI Agent Process"
		model.process_id = "Process_AI_Agent"
		model.bpmn_xml = xml_content
		model.insert(ignore_permissions=True)

		try:
			# 2. Compile model
			from one_bpmn.api.compilation import compile_process_model
			compile_process_model(model.name)
			
			# Reload and verify compilation
			model.reload()
			spec = json.loads(model.serialized_spec)
			self.assertIn("service_task_extensions", spec)
			self.assertIn("AI_Subprocess_1", spec["service_task_extensions"])
			self.assertEqual(spec["service_task_extensions"]["AI_Subprocess_1"]["aiExecutionMode"], "direct_api")

			# 3. Create process instance
			instance = frappe.new_doc("BPMN Process Instance")
			instance.process_model = model.name
			instance.status = "Active"
			instance.insert(ignore_permissions=True)

			try:
				# 4. Start instance execution
				instance.start()
				
				# Reload and verify completion
				instance.reload()
				self.assertEqual(instance.status, "Completed")
				
				# Verify output variable was populated by restoring the workflow object
				from one_bpmn.one_bpmn import engine as bpmn_engine
				wf = bpmn_engine.restore_workflow(
					workflow_state=json.loads(instance.workflow_state)
				)
				self.assertEqual(wf.task_tree.data.get("output_var_sub"), "Audit completed: volume is above threshold.")
				
			finally:
				# Direct delete to bypass LinkExistsError
				frappe.db.delete("BPMN Active Task", {"parent": instance.name})
				frappe.db.delete("BPMN Activity Log", {"instance": instance.name})
				frappe.db.delete("BPMN Process Instance", {"name": instance.name})
		finally:
			# Direct delete to bypass LinkExistsError
			frappe.db.delete("BPMN Process Model", {"name": model.name})

	@patch("google.antigravity.Agent")
	def test_ai_agent_antigravity_sdk_mode(self, mock_agent_class):
		# Setup mock agent instance
		mock_agent = MagicMock()
		
		# Mock async context manager __aenter__ / __aexit__
		async def async_aenter(*args, **kwargs):
			return mock_agent
		async def async_aexit(*args, **kwargs):
			pass
			
		mock_agent_class.return_value.__aenter__ = async_aenter
		mock_agent_class.return_value.__aexit__ = async_aexit
		
		# Mock conversation messages and usage
		mock_agent.conversation = MagicMock()
		mock_agent.conversation.messages = [
			MagicMock(role="user", content="Solve this with SDK"),
			MagicMock(role="model", content="Mocked SDK Response")
		]
		mock_agent.conversation.total_usage = MagicMock(
			prompt_token_count=10,
			candidates_token_count=20,
			total_token_count=30
		)
		
		# Mock chat response (which is an async generator returning tokens)
		class AsyncTokenStream:
			def __init__(self, tokens):
				self.tokens = tokens
			def __aiter__(self):
				return self
			async def __anext__(self):
				if not self.tokens:
					raise StopAsyncIteration
				return self.tokens.pop(0)
				
		async def mock_chat(prompt):
			return AsyncTokenStream(["Mocked ", "SDK ", "Response"])
			
		mock_agent.chat = mock_chat

		# 1. Create a mock BPMN Process Model with custom AI Agent adHocSubProcess in antigravity_sdk mode
		xml_content = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
                  id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_AI_Agent_SDK" isExecutable="true">
    <bpmn:startEvent id="Start_1">
      <bpmn:outgoing>Flow_1</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="AI_Subprocess_1" />
    <bpmn:adHocSubProcess id="AI_Subprocess_1" name="AI Subprocess 1" spiffworkflow:serviceType="ai_agent" spiffworkflow:aiExecutionMode="antigravity_sdk" spiffworkflow:aiModelId="gemini-3.5-flash" spiffworkflow:aiUserMessage="Solve this with SDK" spiffworkflow:aiContextVariable="output_var_sub">
      <bpmn:incoming>Flow_1</bpmn:incoming>
      <bpmn:outgoing>Flow_2</bpmn:outgoing>
      <bpmn:startEvent id="Sub_Start_1">
        <bpmn:outgoing>Sub_Flow_1</bpmn:outgoing>
      </bpmn:startEvent>
      <bpmn:sequenceFlow id="Sub_Flow_1" sourceRef="Sub_Start_1" targetRef="Sub_Tool_1" />
      <bpmn:serviceTask id="Sub_Tool_1" name="Audit Volume">
        <bpmn:incoming>Sub_Flow_1</bpmn:incoming>
        <bpmn:outgoing>Sub_Flow_2</bpmn:outgoing>
        <bpmn:extensionElements>
          <spiffworkflow:preVariableMapping>
            <spiffworkflow:mapping>
              <spiffworkflow:target>threshold</spiffworkflow:target>
              <spiffworkflow:expression>fromAi("threshold", "Volume threshold", "number")</spiffworkflow:expression>
            </spiffworkflow:mapping>
          </spiffworkflow:preVariableMapping>
        </bpmn:extensionElements>
      </bpmn:serviceTask>
      <bpmn:sequenceFlow id="Sub_Flow_2" sourceRef="Sub_Tool_1" targetRef="Sub_End_1" />
      <bpmn:endEvent id="Sub_End_1">
        <bpmn:incoming>Sub_Flow_2</bpmn:incoming>
      </bpmn:endEvent>
    </bpmn:adHocSubProcess>
    <bpmn:sequenceFlow id="Flow_2" sourceRef="AI_Subprocess_1" targetRef="End_1" />
    <bpmn:endEvent id="End_1">
      <bpmn:incoming>Flow_2</bpmn:incoming>
    </bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""

		model = frappe.new_doc("BPMN Process Model")
		model.title = "Test AI Agent SDK Process"
		model.process_id = "Process_AI_Agent_SDK"
		model.bpmn_xml = xml_content
		model.insert(ignore_permissions=True)

		try:
			# 2. Compile model
			from one_bpmn.api.compilation import compile_process_model
			compile_process_model(model.name)
			
			# Reload and verify compilation
			model.reload()
			spec = json.loads(model.serialized_spec)
			self.assertIn("service_task_extensions", spec)
			self.assertIn("AI_Subprocess_1", spec["service_task_extensions"])
			self.assertEqual(spec["service_task_extensions"]["AI_Subprocess_1"]["aiExecutionMode"], "antigravity_sdk")

			# 3. Create process instance
			instance = frappe.new_doc("BPMN Process Instance")
			instance.process_model = model.name
			instance.status = "Active"
			instance.insert(ignore_permissions=True)

			try:
				# 4. Start instance execution
				instance.start()
				
				# Reload and verify completion
				instance.reload()
				self.assertEqual(instance.status, "Completed")
				
				# Verify output variable was populated by restoring the workflow object
				from one_bpmn.one_bpmn import engine as bpmn_engine
				wf = bpmn_engine.restore_workflow(
					workflow_state=json.loads(instance.workflow_state)
				)
				self.assertEqual(wf.task_tree.data.get("output_var_sub"), "Mocked SDK Response")
				
			finally:
				# Direct delete to bypass LinkExistsError
				frappe.db.delete("BPMN Active Task", {"parent": instance.name})
				frappe.db.delete("BPMN Activity Log", {"instance": instance.name})
				frappe.db.delete("BPMN Process Instance", {"name": instance.name})
		finally:
			# Direct delete to bypass LinkExistsError
			frappe.db.delete("BPMN Process Model", {"name": model.name})


