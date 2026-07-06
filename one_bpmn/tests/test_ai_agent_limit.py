# Copyright (c) 2026, one-fm and contributors
# WI-001422: enforce a "Maximum model calls" limit (aiMaxToolCalls) on the AI
# Agent Task's tool-calling loop.

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch

from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage


class TestAgentMaxToolCalls(FrappeTestCase):
	def setUp(self):
		self.instance = frappe.get_doc(
			{"doctype": "BPMN Process Instance", "process_id": f"t-{frappe.generate_hash(length=6)}", "status": "Active"}
		)
		self.instance.flags.ignore_mandatory = True
		self.instance.insert(ignore_permissions=True, ignore_mandatory=True)
		self.task = frappe._dict({"data": {}, "task_spec": frappe._dict({"name": "A", "description": "A"})})

	def _captured_config(self, task_cfg):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		captured = {}
		result = ExecutorResult(
			output="ok", error_code=ErrorCode.SUCCESS,
			token_usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
		)

		def fake_run(_self, config, context):
			captured["config"] = config
			return result

		with patch("one_bpmn.agents.executor.direct_api.DirectApiExecutor.run", new=fake_run):
			dispatchers.dispatch_ai_agent(self.instance, self.task, task_cfg, "A")
		return captured["config"]

	def test_explicit_limit_threads_to_config(self):
		cfg = self._captured_config(
			{"serviceType": "ai_agent", "aiUserPrompt": "x", "aiMaxToolCalls": "3",
			 "aiToolShapes": json.dumps([{"bpmn_id": "t", "serverScript": "S"}])}
		)
		self.assertEqual(cfg.max_tool_calls, 3)

	def test_default_limit_is_ten(self):
		cfg = self._captured_config({"serviceType": "ai_agent", "aiUserPrompt": "x"})
		self.assertEqual(cfg.max_tool_calls, 10)

	def test_adapters_accept_max_turns(self):
		# Every tool-loop adapter's complete() must accept max_turns so the cap
		# actually reaches the loop bound.
		import inspect

		from one_bpmn.agents.llm_provider.anthropic_adapter import AnthropicAdapter
		from one_bpmn.agents.llm_provider.openai_adapter import OpenAIAdapter
		from one_bpmn.agents.llm_provider.gemini import GeminiAdapter

		for cls in (AnthropicAdapter, OpenAIAdapter, GeminiAdapter):
			self.assertIn("max_turns", inspect.signature(cls.complete).parameters, cls.__name__)
