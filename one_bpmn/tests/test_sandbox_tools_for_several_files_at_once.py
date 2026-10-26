# Copyright (c) 2026, one-fm and contributors
"""read_files, grep_files and apply_edits reach the sandbox with the right action, and the budget and gates see them."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops
from one_bpmn.one_bpmn.patches.v1_0 import sandbox_tools_for_several_files_at_once as patch_module

BRIEF = {
	"target_app": "one_bpmn", "git_branch": "staging", "work_item_description": "Fix it.",
}


def _run_script(name: str, task_data: dict, dispatch=None, budget_error=None) -> dict:
	"""Run the stored script as the engine does: plain exec, real frappe, the two ops entry points replaced."""
	script = frappe.db.get_value("Server Script", name, "script")
	dispatch = dispatch or MagicMock(return_value={"ok": True, "response": {"done": True}})
	result = {}
	with patch.object(ops, "sandbox_dispatch", dispatch), patch.object(
		ops, "read_budget_exceeded", return_value=budget_error
	):
		exec(  # noqa: S102 - the engine runs trusted Server Scripts the same way
			script,
			{
				"frappe": frappe, "task_data": {**BRIEF, **task_data}, "result": result, "instance": None,
				"context_docname": "A2A-1", "bpmn_id": "Activity_x", "__builtins__": __builtins__,
			},
		)
	return result, dispatch


class TestTheScripts(FrappeTestCase):
	def setUp(self):
		patch_module.execute()

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_each_script_exists_and_is_not_a_public_endpoint(self):
		for name in patch_module.SCRIPTS:
			row = frappe.db.get_value("Server Script", name, ["script_type", "api_method", "disabled"], as_dict=True)
			self.assertEqual(row.script_type, "API", name)
			self.assertFalse(row.api_method, name)
			self.assertFalse(row.disabled, name)

	def test_running_the_patch_twice_changes_nothing(self):
		before = {n: frappe.db.get_value("Server Script", n, "script") for n in patch_module.SCRIPTS}
		patch_module.execute()
		self.assertEqual(before, {n: frappe.db.get_value("Server Script", n, "script") for n in patch_module.SCRIPTS})

	def test_the_patch_restores_an_edited_script(self):
		name = "Sandbox Tool: Read Files"
		frappe.db.set_value("Server Script", name, "script", "result['x'] = 1")
		patch_module.execute()
		self.assertEqual(frappe.db.get_value("Server Script", name, "script"), patch_module.SCRIPTS[name])

	def test_read_files_sends_the_paths(self):
		result, dispatch = _run_script("Sandbox Tool: Read Files", {"paths": ["a.py", "b.py"]})
		self.assertEqual(dispatch.call_args.args[0], "read_files")
		self.assertEqual(dispatch.call_args.args[4], {"paths": ["a.py", "b.py"]})
		self.assertEqual(result, {"done": True})

	def test_read_files_refuses_a_missing_or_empty_list_without_calling_the_sandbox(self):
		for bad in (None, [], "a.py"):
			result, dispatch = _run_script("Sandbox Tool: Read Files", {"paths": bad})
			self.assertIn("paths is required", result["error"])
			dispatch.assert_not_called()

	def test_a_spent_read_budget_stops_read_files_and_grep_files(self):
		for name, data in (("Sandbox Tool: Read Files", {"paths": ["a"]}), ("Sandbox Tool: Grep Files", {"pattern": "x"})):
			result, dispatch = _run_script(name, data, budget_error="stop reading")
			self.assertEqual(result["error"], "stop reading")
			dispatch.assert_not_called()

	def test_grep_files_sends_pattern_prefix_and_literal(self):
		_result, dispatch = _run_script(
			"Sandbox Tool: Grep Files", {"pattern": "needle", "path_prefix": "src", "literal": True}
		)
		self.assertEqual(dispatch.call_args.args[0], "grep_files")
		self.assertEqual(dispatch.call_args.args[4], {"pattern": "needle", "path_prefix": "src", "literal": True})

	def test_grep_files_needs_a_pattern(self):
		result, dispatch = _run_script("Sandbox Tool: Grep Files", {"pattern": "  "})
		self.assertIn("pattern is required", result["error"])
		dispatch.assert_not_called()

	def test_apply_edits_sends_the_edits_and_is_not_held_by_the_read_budget(self):
		edits = [{"path": "a.py", "old_string": "x", "new_string": "y"}]
		result, dispatch = _run_script("Sandbox Tool: Apply Edits", {"edits": edits}, budget_error="stop reading")
		self.assertEqual(dispatch.call_args.args[0], "apply_edits")
		self.assertEqual(dispatch.call_args.args[4], {"edits": edits})
		self.assertEqual(result, {"done": True})

	def test_apply_edits_refuses_an_empty_list(self):
		result, dispatch = _run_script("Sandbox Tool: Apply Edits", {"edits": []})
		self.assertIn("edits is required", result["error"])
		dispatch.assert_not_called()

	def test_a_missing_brief_is_refused_by_all_three(self):
		for name, data in (
			("Sandbox Tool: Read Files", {"paths": ["a"]}),
			("Sandbox Tool: Grep Files", {"pattern": "x"}),
			("Sandbox Tool: Apply Edits", {"edits": [{"path": "a", "old_string": "b", "new_string": "c"}]}),
		):
			result, dispatch = _run_script(name, {**data, "git_branch": ""})
			self.assertIn("all required", result["error"], name)
			dispatch.assert_not_called()

	def test_a_sandbox_failure_is_reported_as_the_error(self):
		failing = MagicMock(return_value={"ok": False, "error": "no route"})
		result, _ = _run_script("Sandbox Tool: Read Files", {"paths": ["a"]}, dispatch=failing)
		self.assertEqual(result, {"error": "no route"})


class TestTheReadBudgetAndGatesSeeTheNewActions(FrappeTestCase):
	def test_the_new_reads_count_toward_the_read_budget_and_apply_edits_resets_it(self):
		self.assertIn("read_files", ops._READ_ACTIONS)
		self.assertIn("grep_files", ops._READ_ACTIONS)
		self.assertIn("apply_edits", ops._PROGRESS_ACTIONS)

	def test_a_file_read_through_read_files_counts_as_read(self):
		rows = [frappe._dict(request_payload=frappe.as_json({"action": "read_files", "args": {"paths": ["a/b.py", "c.py"]}}))]
		with patch.object(frappe, "get_all", return_value=rows):
			self.assertTrue(ops._has_read(frappe._dict(name="i"), "c.py"))
			self.assertFalse(ops._has_read(frappe._dict(name="i"), "other.py"))

	def test_edited_paths_cover_every_edit_and_ignore_junk(self):
		edits = [{"path": "a.py"}, "junk", {"path": "b.py"}, {}]
		self.assertEqual(ops._edited_paths("apply_edits", {"edits": edits}), ["a.py", "b.py", ""])
		self.assertEqual(ops._edited_paths("apply_edits", {"edits": "nope"}), [])
		self.assertEqual(ops._edited_paths("edit_file", {"path": "x.py"}), ["x.py"])

	def test_the_frontend_gate_runs_on_each_file_of_apply_edits(self):
		instance = frappe._dict(name="i", process_model="Frontend Agent")
		edits = [
			{"path": "api/x.py", "old_string": "a", "new_string": "b"},
			{"path": "spiff/src/Home.vue", "old_string": "a", "new_string": "b"},
		]
		with patch.object(ops, "_skill_loaded", return_value=False), patch.object(
			ops, "_has_read", return_value=True
		), patch.object(ops, "_past_read_budget", return_value=False):
			out = ops.sandbox_dispatch("apply_edits", "one_bpmn", "staging", "d", {"edits": edits}, instance=instance)
		self.assertFalse(out["ok"])
		self.assertIn("load_skill frontend-house-style", out["error"])
