# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A long file is read in windows that fit the tool result cap, and the Frontend Agent's tools point at those windows.

The behaviour lives in Server Scripts, which is what the agents run, so these tests execute the site's copy of each.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor.tool_bounds import DEFAULT_TOOL_RESULT_MAX_CHARS
from one_bpmn.one_bpmn.patches.v1_0 import frontend_agent_reads_in_windows as fix

REPO = frappe.get_app_source_path("one_bpmn")
BPMN_EDITOR = "spiff/src/components/BpmnEditor.vue"
EDITOR = "spiff/src/views/Editor.vue"
ARGS = {"target_app": "one_bpmn", "git_branch": "staging", "work_item_description": "Fix the panel."}


def _source(path: str) -> str:
	with open(os.path.join(REPO, path)) as handle:
		return handle.read()


def _exec(script_name: str, task_data: dict, **stubs) -> dict:
	body = frappe.db.get_value("Server Script", script_name, "script")
	result = {}
	namespace = {
		"frappe": frappe,
		"__builtins__": __builtins__,
		"result": result,
		"task_data": dict(task_data),
		"context_docname": None,
		"bpmn_id": "read_file",
		"instance": frappe._dict(name=f"window-{frappe.generate_hash(length=6)}"),
	}
	with patch(
		"one_bpmn.one_bpmn.connectors.agent_sandbox_ops.sandbox_dispatch",
		return_value=stubs.get("dispatch"),
	):
		exec(body, namespace)
	return result


def _read(path: str, content: str, **window) -> dict:
	dispatch = {"ok": True, "response": {"found": True, "content": content}}
	return _exec(fix.READ_FILE, dict(ARGS, path=path, **window), dispatch=dispatch)


class TestALongFileIsReadInWindows(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_a_read_with_no_limit_returns_the_first_window_with_the_count_and_a_hint(self):
		content = _source(BPMN_EDITOR)
		total = len(content.split("\n"))
		out = _read(BPMN_EDITOR, content)
		self.assertEqual(out["total_lines"], total)
		self.assertEqual(out["line_range"], f"1-400 of {total}")
		self.assertEqual(out["content"], "\n".join(content.split("\n")[:400]))
		self.assertIn("offset=401", out["hint"])
		self.assertLess(len(json.dumps(out)), DEFAULT_TOOL_RESULT_MAX_CHARS)

	def test_a_window_that_would_not_fit_the_cap_is_shortened(self):
		content = _source(EDITOR)
		out = _read(EDITOR, content)
		shown = int(out["line_range"].split("-")[1].split(" ")[0])
		self.assertLess(shown, 400)
		self.assertLess(len(json.dumps(out)), DEFAULT_TOOL_RESULT_MAX_CHARS)

	def test_the_count_and_range_come_before_the_content(self):
		out = _read(BPMN_EDITOR, _source(BPMN_EDITOR))
		keys = list(out)
		self.assertLess(keys.index("total_lines"), keys.index("content"))
		self.assertLess(keys.index("line_range"), keys.index("content"))
		self.assertLess(keys.index("hint"), keys.index("content"))

	def test_a_short_file_still_comes_back_whole(self):
		content = "line\n" * 50
		out = _read("spiff/src/small.js", content)
		self.assertEqual(out["content"], content)
		self.assertNotIn("hint", out)

	def test_an_explicit_window_is_unchanged(self):
		content = _source(BPMN_EDITOR)
		out = _read(BPMN_EDITOR, content, offset=1000, limit=10)
		self.assertEqual(out["line_range"], f"1000-1009 of {len(content.split(chr(10)))}")
		self.assertNotIn("hint", out)


class TestTheFrontendToolsPointAtWindows(FrappeTestCase):
	def test_each_search_hit_carries_an_offset_and_limit(self):
		out = _exec(fix.SEARCH_FRONTEND, {"pattern": "defineProps", "apps": ["one_bpmn"], "exts": [".vue"]})
		self.assertTrue(out["hits"])
		for hit in out["hits"]:
			self.assertEqual(hit["offset"], max(1, hit["line"] - 20))
			self.assertEqual(hit["limit"], 60)

	def test_the_catalogue_is_small_and_points_at_the_tailwind_resource(self):
		out = _exec(fix.COMPONENT_CATALOGUE, {})
		self.assertLess(len(json.dumps(out)), 3000)
		self.assertIn(
			"load_skill_resource('frontend-house-style', 'tailwind-config')", out["tailwind_config"]
		)
		self.assertTrue(out["frappe_ui"])

	def test_the_tailwind_config_is_a_resource_of_the_skill(self):
		value = frappe.db.get_value(
			"AI Skill Resource",
			{"parent": fix.SKILL, "resource_name": fix.TAILWIND_RESOURCE},
			"resource_value",
		)
		self.assertEqual(value, _source("spiff/tailwind.config.cjs"))


class TestThePatchEdits(FrappeTestCase):
	def test_running_it_again_changes_nothing(self):
		before = {
			n: frappe.db.get_value("Server Script", n, "script")
			for n in (fix.READ_FILE, fix.SEARCH_FRONTEND, fix.COMPONENT_CATALOGUE)
		}
		fix.execute()
		for name, script in before.items():
			self.assertEqual(frappe.db.get_value("Server Script", name, "script"), script)
