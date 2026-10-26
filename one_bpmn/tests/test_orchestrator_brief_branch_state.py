# Copyright (c) 2026, one-fm and contributors
"""The Orchestrator is told what an earlier attempt left on the Work Item's branch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import agent_criteria as criteria
from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops
from one_bpmn.one_bpmn.patches.v1_0 import orchestrator_brief_shows_the_branch_left_by_an_earlier_attempt as patch_module

COMPARE = {
	"ahead_by": 3,
	"commits": [{"commit": {"message": f"edit {n}\n\nbody"}} for n in range(1, 8)],
	"files": [{"filename": f"one_bpmn/f{n}.py"} for n in range(1, 26)],
}
BASE = (
	'wi = frappe.get_doc("Work Item", context_docname)\n'
	'brief = "The brief"\n'
	'header = "Header\\n"\n'
	'result["work_item_brief"] = header + brief\n'
)


class TestBranchSummary(FrappeTestCase):
	def _summary(self, compared):
		with patch.object(criteria, "_compare", return_value=compared):
			return criteria.branch_summary("WI-1", "one_bpmn", "staging")

	def test_commits_ahead_give_the_count_the_latest_commits_and_the_files(self):
		text = self._summary(COMPARE)
		self.assertIn("Branch WI-1 already has 3 commit(s)", text)
		self.assertIn("Continue from them and do not start over.", text)
		self.assertIn("- edit 7", text)
		self.assertNotIn("- edit 2\n", text + "\n")
		self.assertIn("- one_bpmn/f20.py", text)
		self.assertNotIn("one_bpmn/f21.py", text)

	def test_a_branch_with_nothing_ahead_or_none_on_github_gives_nothing(self):
		self.assertEqual(self._summary({"ahead_by": 0}), "")
		self.assertEqual(self._summary(None), "")

	def test_github_not_configured_gives_nothing(self):
		with patch.object(ops, "github_access", return_value=None):
			self.assertEqual(criteria.branch_summary("WI-1", "one_bpmn", "staging"), "")

	def test_the_branch_files_come_from_the_same_comparison(self):
		with patch.object(criteria, "_compare", return_value=COMPARE):
			self.assertEqual(len(criteria._branch_files("one_bpmn", "staging", "WI-1")), 25)
		with patch.object(criteria, "_compare", return_value=None):
			self.assertIsNone(criteria._branch_files("one_bpmn", "staging", "WI-1"))


class TestTheBriefPatch(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("Server Script", patch_module.SCRIPT):
			self.skipTest("the Orchestrator brief script is not on this site")
		frappe.db.set_value("Server Script", patch_module.SCRIPT, "script", BASE, update_modified=False)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _brief(self, note):
		script = frappe.db.get_value("Server Script", patch_module.SCRIPT, "script")
		result = {}
		item = SimpleNamespace(name="WI-1", target_app="one_bpmn", git_branch="staging")
		fake = SimpleNamespace(get_doc=lambda *a, **k: item)
		with patch.object(criteria, "branch_summary", return_value=note):
			exec(script, {"frappe": fake, "context_docname": "WI-1", "result": result, "__builtins__": __builtins__})
		return result["work_item_brief"]

	def test_the_note_is_added_to_the_brief(self):
		patch_module.execute()
		self.assertEqual(self._brief("Branch WI-1 has 2 commits."), "Header\nThe brief\n\nBranch WI-1 has 2 commits.")

	def test_no_note_leaves_the_brief_as_it_was(self):
		patch_module.execute()
		self.assertEqual(self._brief(""), "Header\nThe brief")

	def test_the_script_is_patched_once(self):
		patch_module.execute()
		patch_module.execute()
		script = frappe.db.get_value("Server Script", patch_module.SCRIPT, "script")
		self.assertEqual(script.count(patch_module.MARKER), 1)

	def test_a_script_without_the_anchor_is_left_alone(self):
		frappe.db.set_value("Server Script", patch_module.SCRIPT, "script", "result['x'] = 1", update_modified=False)
		patch_module.execute()
		self.assertEqual(frappe.db.get_value("Server Script", patch_module.SCRIPT, "script"), "result['x'] = 1")

	def test_it_lands_after_the_earlier_report_block_when_both_patches_ran(self):
		from one_bpmn.one_bpmn.patches.v1_0 import orchestrator_passes_criteria_and_earlier_report as earlier

		earlier.execute()
		patch_module.execute()
		script = frappe.db.get_value("Server Script", patch_module.SCRIPT, "script")
		self.assertLess(script.index(earlier.MARKER), script.index(patch_module.MARKER))
		self.assertLess(script.index(patch_module.MARKER), script.index(patch_module.ANCHOR))
