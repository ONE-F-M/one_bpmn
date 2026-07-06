# Copyright (c) 2026, one-fm and contributors
# Standalone AI Agent Task + registry tools (Camunda "AI Agent Task connector"
# analog): a plain service task that calls registry tools it declares on itself,
# with no ad-hoc sub-process. Covers the allow-list resolver, the dispatch
# tool-path (tools attached + per-tool evidence written), and compile-time
# validation of the tool list.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch

from one_bpmn.agents.executor import ErrorCode, ExecutorResult, TokenUsage
from one_bpmn.agents.tool_pool import resolve_agent_tools


def _make_server_script(name: str) -> str:
	if not frappe.db.exists("Server Script", name):
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": name,
				"script_type": "API",
				"api_method": name.lower().replace(" ", "_"),
				"script": "frappe.response['message'] = {'ok': True}",
			}
		).insert(ignore_permissions=True)
	return name


def _make_process_model(title: str) -> str:
	if not frappe.db.exists("BPMN Process Model", title):
		doc = frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"title": title,
				"process_id": title.lower().replace(" ", "_"),
				"version": 1,
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True, ignore_mandatory=True)
	return title


def _make_tool(tool_name: str, is_active: int = 1, processes: list | None = None) -> str:
	if frappe.db.exists("AI Agent Tool", tool_name):
		return tool_name
	doc = {
		"doctype": "AI Agent Tool",
		"tool_name": tool_name,
		"description": f"Test tool {tool_name}.",
		"input_schema": '{"x": {"type": "string"}}',
		"handler_type": "server_script",
		"handler_reference": _make_server_script(f"{tool_name} handler"),
		"is_active": is_active,
	}
	if processes:
		doc["applicable_processes"] = [{"process_model": p} for p in processes]
	frappe.get_doc(doc).insert(ignore_permissions=True)
	return tool_name


class TestResolveAgentTools(FrappeTestCase):
	def test_resolves_named_active_global_tool(self):
		_make_tool("agent_tool_alpha")
		specs = resolve_agent_tools(["agent_tool_alpha"], process_model="")
		self.assertEqual([s.name for s in specs], ["agent_tool_alpha"])
		# The compiled spec is callable — the adapter loop invokes spec.fn.
		self.assertTrue(callable(specs[0].fn))

	def test_skips_unknown_name(self):
		self.assertEqual(resolve_agent_tools(["does_not_exist_xyz"]), [])

	def test_skips_inactive_tool(self):
		_make_tool("agent_tool_inactive", is_active=0)
		self.assertEqual(resolve_agent_tools(["agent_tool_inactive"]), [])

	def test_respects_process_scoping(self):
		_make_process_model("Some Other Model")
		_make_tool("agent_tool_scoped", processes=["Some Other Model"])
		# Not applicable to this process → excluded.
		self.assertEqual(resolve_agent_tools(["agent_tool_scoped"], "This Model"), [])
		# Applicable → included.
		names = [s.name for s in resolve_agent_tools(["agent_tool_scoped"], "Some Other Model")]
		self.assertEqual(names, ["agent_tool_scoped"])

	def test_dedupes_and_ignores_blanks(self):
		_make_tool("agent_tool_dedupe")
		specs = resolve_agent_tools(["agent_tool_dedupe", " agent_tool_dedupe ", ""], "")
		self.assertEqual([s.name for s in specs], ["agent_tool_dedupe"])


class TestDispatchAgentWithTools(FrappeTestCase):
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
		self.bpmn_id = "Activity_Tools1"
		self.task = frappe._dict(
			{
				"data": {},
				"task_spec": frappe._dict({"name": self.bpmn_id, "description": "Agent w/ tools"}),
			}
		)

	def _dispatch(self, task_cfg, result):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		captured = {}

		def fake_run(_self, config, context):
			captured["config"] = config
			return result

		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			new=fake_run,
		):
			dispatchers.dispatch_ai_agent(self.instance, self.task, task_cfg, self.bpmn_id)
		return captured

	def test_allowlist_attaches_tools_and_writes_evidence(self):
		_make_tool("dispatch_tool_beta")
		task_cfg = {
			"serviceType": "ai_agent",
			"aiProvider": "",
			"aiModel": "gpt-4o",
			"aiUserPrompt": "Do the thing.",
			"aiOutputVariable": "agent_out",
			"aiTools": "dispatch_tool_beta",
		}
		result = ExecutorResult(
			output="All done.",
			error_code=ErrorCode.SUCCESS,
			token_usage=TokenUsage(prompt_tokens=12, completion_tokens=6, total_tokens=18),
			trace=[
				{
					"role": "tool",
					"content": "",
					"tool_calls": [
						{"name": "dispatch_tool_beta", "arguments": {"x": "1"}, "result": '{"ok": true}'}
					],
					"prompt_tokens": 10,
					"completion_tokens": 2,
					"latency_ms": 5,
				},
				{
					"role": "assistant",
					"content": "All done.",
					"tool_calls": [],
					"prompt_tokens": 2,
					"completion_tokens": 4,
					"latency_ms": 6,
				},
			],
		)
		captured = self._dispatch(task_cfg, result)

		# 1) The allow-list was resolved and handed to the executor.
		self.assertIsNotNone(captured["config"].tools)
		self.assertEqual([t.name for t in captured["config"].tools], ["dispatch_tool_beta"])

		# 2) Output variable written.
		self.assertEqual(self.task.data["agent_out"], "All done.")

		# 3) Per-tool evidence exposed for downstream steps.
		self.assertEqual(self.task.data["dispatch_tool_beta_toolCallResult"], '{"ok": true}')

	def test_no_tools_is_plain_llm_call(self):
		task_cfg = {
			"serviceType": "ai_agent",
			"aiProvider": "",
			"aiModel": "gpt-4o",
			"aiUserPrompt": "Say hi.",
			"aiOutputVariable": "agent_out",
			# no aiTools
		}
		result = ExecutorResult(
			output="hi",
			error_code=ErrorCode.SUCCESS,
			token_usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
		)
		captured = self._dispatch(task_cfg, result)
		self.assertIsNone(captured["config"].tools)
		self.assertEqual(self.task.data["agent_out"], "hi")


class TestAgentToolsCompileValidation(FrappeTestCase):
	def _lint(self, ai_tools_value):
		from one_bpmn.api.compilation import _lint_ai_provider_config

		_lint_ai_provider_config(
			"", {"Activity_X": {"serviceType": "ai_agent", "aiTools": ai_tools_value}}
		)

	def test_unknown_tool_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self._lint("no_such_tool_qqq")

	def test_inactive_tool_rejected(self):
		_make_tool("compile_tool_inactive", is_active=0)
		with self.assertRaises(frappe.ValidationError):
			self._lint("compile_tool_inactive")

	def test_active_tool_passes(self):
		_make_tool("compile_tool_active")
		self._lint("compile_tool_active")  # must not raise

	def test_empty_tool_list_passes(self):
		self._lint("")  # must not raise
