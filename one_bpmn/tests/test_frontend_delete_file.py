# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""write_file refuses empty content, and the Frontend Agent removes a file with delete_file instead.

The tools are Server Scripts, which is what the agents run, so these tests execute the site's copy of each.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import frontend_agent_deletes_files as fix

ARGS = {"target_app": "one_bpmn", "git_branch": "staging", "work_item_description": "Remove the old panel."}
SENT = {"ok": True, "response": {"written": True}}


def _exec(script_name: str, task_data: dict):
	body = frappe.db.get_value("Server Script", script_name, "script")
	result = {}
	namespace = {
		"frappe": frappe,
		"__builtins__": __builtins__,
		"result": result,
		"task_data": dict(task_data),
		"context_docname": None,
		"bpmn_id": "tool",
		"instance": frappe._dict(name="delete-file-test"),
	}
	with patch(
		"one_bpmn.one_bpmn.connectors.agent_sandbox_ops.sandbox_dispatch", return_value=SENT
	) as dispatch:
		exec(body, namespace)
	return result, dispatch


class TestWriteFileRefusesEmptyContent(FrappeTestCase):
	def test_empty_content_is_refused_and_names_delete_file(self):
		result, dispatch = _exec(
			fix.WRITE_FILE, dict(ARGS, path="onefm_mcp/page/lumina/lumina.json", content="")
		)
		self.assertIn("delete_file", result["error"])
		dispatch.assert_not_called()

	def test_whitespace_only_content_is_refused(self):
		result, dispatch = _exec(fix.WRITE_FILE, dict(ARGS, path="spiff/src/a.vue", content="  \n\t"))
		self.assertIn("delete_file", result["error"])
		dispatch.assert_not_called()

	def test_an_empty_package_file_is_still_written(self):
		result, dispatch = _exec(
			fix.WRITE_FILE, dict(ARGS, path="one_bpmn/one_bpmn/doctype/x/__init__.py", content="")
		)
		self.assertNotIn("error", result)
		dispatch.assert_called_once()

	def test_real_content_is_written_as_before(self):
		_, dispatch = _exec(fix.WRITE_FILE, dict(ARGS, path="spiff/src/a.vue", content="<template/>"))
		self.assertEqual(dispatch.call_args.args[0], "write_file")


class TestDeleteFile(FrappeTestCase):
	def test_delete_file_dispatches_the_path(self):
		result, dispatch = _exec(fix.DELETE_FILE, dict(ARGS, path="spiff/src/components/Old.vue"))
		self.assertEqual(dispatch.call_args.args[0], "delete_file")
		self.assertEqual(dispatch.call_args.args[4], {"path": "spiff/src/components/Old.vue"})
		self.assertNotIn("error", result)

	def test_delete_file_without_a_path_is_refused(self):
		result, dispatch = _exec(fix.DELETE_FILE, dict(ARGS))
		self.assertIn("path is required", result["error"])
		dispatch.assert_not_called()


class TestTheFrontendAgentHasTheTool(FrappeTestCase):
	def test_the_map_has_the_shape_inside_its_tools_and_compiles_it(self):
		xml = frappe.db.get_value("BPMN Process Model", fix.MAP, "bpmn_xml")
		tools = xml[xml.index("<bpmn:adHocSubProcess") : xml.index("</bpmn:adHocSubProcess>")]
		self.assertIn('id="delete_file"', tools)
		self.assertIn('bpmnElement="delete_file"', xml)
		self.assertIn(
			"Sandbox Tool: Delete File", frappe.db.get_value("BPMN Process Model", fix.MAP, "serialized_spec")
		)

	def test_the_prompt_names_delete_file(self):
		prompt = frappe.db.get_value("AI Agent Configuration", fix.AGENT, "system_prompt")
		self.assertIn(fix.PROMPT_WRITE_RULE_WITH_DELETE, prompt)
		self.assertIn(fix.PROMPT_TOOLS_WITH_DELETE, prompt)

	def test_the_baseline_suite_checks_that_a_removal_never_writes(self):
		case = frappe.get_doc("AI Eval Case", {"title": fix.CASE_TITLE})
		self.assertEqual(
			{(a.assertion_type, a.value) for a in case.assertions},
			{("tool_calls", "ANY_ORDER"), ("no_tool_call", "write_file")},
		)
		self.assertEqual(case.expected_tool_calls[0].tool_name, "delete_file")

	def test_running_it_again_changes_nothing(self):
		before = (
			frappe.db.get_value("BPMN Process Model", fix.MAP, "bpmn_xml"),
			frappe.db.get_value("AI Agent Configuration", fix.AGENT, "system_prompt"),
			frappe.db.get_value("Server Script", fix.WRITE_FILE, "script"),
			frappe.db.count("AI Eval Case", {"title": fix.CASE_TITLE}),
		)
		frappe.db.savepoint("run_again")
		try:
			fix.execute()
			after = (
				frappe.db.get_value("BPMN Process Model", fix.MAP, "bpmn_xml"),
				frappe.db.get_value("AI Agent Configuration", fix.AGENT, "system_prompt"),
				frappe.db.get_value("Server Script", fix.WRITE_FILE, "script"),
				frappe.db.count("AI Eval Case", {"title": fix.CASE_TITLE}),
			)
		finally:
			frappe.db.rollback(save_point="run_again")
		self.assertEqual(after, before)
