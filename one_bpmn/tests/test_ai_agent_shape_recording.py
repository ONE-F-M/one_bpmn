# Copyright (c) 2026, one-fm and contributors
# WI-001420: each AI Agent tool call is recorded in the AI Agent Step's
# ai_agent_tool_call child table (tool_source = diagram_task).

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch

from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage


class TestAgentShapeRecording(FrappeTestCase):
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

	def test_tool_calls_recorded_with_diagram_source(self):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		task_cfg = {
			"serviceType": "ai_agent",
			"aiProvider": "",
			"aiModel": "gpt-4o",
			"aiUserPrompt": "Do it.",
			"aiOutputVariable": "agent_out",
			"aiToolShapes": json.dumps([{"bpmn_id": "lookup", "serverScript": "S1"}]),
		}
		result = ExecutorResult(
			output="done",
			error_code=ErrorCode.SUCCESS,
			token_usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
			trace=[
				{"role": "tool", "content": "", "tool_calls": [
					{"name": "lookup", "arguments": {"x": 1}, "result": '{"ok": true}'}
				]},
				{"role": "assistant", "content": "done", "tool_calls": []},
			],
		)

		def fake_run(_self, config, context):
			return result

		with patch("one_bpmn.agents.executor.direct_api.DirectApiExecutor.run", new=fake_run):
			dispatchers.dispatch_ai_agent(self.instance, self.task, task_cfg, self.bpmn_id)

		runs = frappe.get_all(
			"AI Agent Run",
			filters={"instance": self.instance.name, "bpmn_id": self.bpmn_id},
			pluck="name",
		)
		self.assertEqual(len(runs), 1)

		steps = frappe.get_all("AI Agent Step", filters={"run": runs[0]}, pluck="name")
		self.assertTrue(steps)

		tool_calls = frappe.get_all(
			"AI Agent Tool Call",
			filters={"parent": ["in", steps], "tool_name": "lookup"},
			fields=["tool_name", "tool_source", "status"],
		)
		self.assertEqual(len(tool_calls), 1)
		self.assertEqual(tool_calls[0].tool_source, "diagram_task")
		self.assertEqual(tool_calls[0].status, "Success")
