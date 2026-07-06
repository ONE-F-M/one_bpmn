# Copyright (c) 2026, one-fm and contributors
# WI-001419: the AI Agent Task executes its referenced sub-process shapes as
# function-tools — dispatch attaches the shape-tools and writes tool-call
# results.

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch

from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage


class TestAgentShapeDispatch(FrappeTestCase):
	def setUp(self):
		self.instance = frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_id": f"test-{frappe.generate_hash(length=6)}",
				"status": "Active",
			}
		)
		self.instance.flags.ignore_mandatory = True
		self.instance.insert(ignore_permissions=True, ignore_mandatory=True)
		self.bpmn_id = "Agent_1"
		self.task = frappe._dict(
			{"data": {}, "task_spec": frappe._dict({"name": self.bpmn_id, "description": "Agent"})}
		)

	def _dispatch(self, task_cfg, result):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		captured = {}

		def fake_run(_self, config, context):
			captured["config"] = config
			return result

		with patch("one_bpmn.agents.executor.direct_api.DirectApiExecutor.run", new=fake_run):
			dispatchers.dispatch_ai_agent(self.instance, self.task, task_cfg, self.bpmn_id)
		return captured

	def test_shape_tools_attached_and_results_written(self):
		task_cfg = {
			"serviceType": "ai_agent",
			"aiProvider": "",
			"aiModel": "gpt-4o",
			"aiUserPrompt": "Do the thing.",
			"aiOutputVariable": "agent_out",
			"aiToolShapes": json.dumps(
				[{"bpmn_id": "lookup", "description": "Look up.", "serverScript": "S1"}]
			),
		}
		result = ExecutorResult(
			output="done",
			error_code=ErrorCode.SUCCESS,
			token_usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
			trace=[
				{
					"role": "tool",
					"tool_calls": [{"name": "lookup", "arguments": {}, "result": '{"found": true}'}],
				},
				{"role": "assistant", "content": "done", "tool_calls": []},
			],
		)
		captured = self._dispatch(task_cfg, result)

		# The referenced sub-process's shape became a function-tool on the config.
		self.assertIsNotNone(captured["config"].tools)
		self.assertEqual([t.name for t in captured["config"].tools], ["lookup"])
		# Output + tool-call evidence written.
		self.assertEqual(self.task.data["agent_out"], "done")
		self.assertEqual(self.task.data["lookup_toolCallResult"], '{"found": true}')
		self.assertEqual(
			self.task.data[f"{self.bpmn_id}_toolCallResults"],
			[{"tool": "lookup", "result": '{"found": true}'}],
		)

	def test_no_tool_shapes_is_plain_call(self):
		task_cfg = {
			"serviceType": "ai_agent",
			"aiProvider": "",
			"aiModel": "gpt-4o",
			"aiUserPrompt": "hi",
			"aiOutputVariable": "agent_out",
		}
		result = ExecutorResult(
			output="hi", error_code=ErrorCode.SUCCESS,
			token_usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
		)
		captured = self._dispatch(task_cfg, result)
		self.assertIsNone(captured["config"].tools)
		self.assertEqual(self.task.data["agent_out"], "hi")
