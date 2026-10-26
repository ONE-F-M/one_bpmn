# Copyright (c) 2026, one-fm and contributors
"""The Orchestrator is told to number criteria, and its brief carries its last report."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.safe_exec import safe_exec

from one_bpmn.one_bpmn.patches.v1_0 import orchestrator_passes_criteria_and_earlier_report as patch

BASE_SCRIPT = (
	'wi = frappe.get_doc("Work Item", context_docname)\n'
	'brief = "The brief"\n'
	'header = "Header\\n"\n'
	'result["work_item_brief"] = header + brief\n'
)


def _work_item():
	"""A real Work Item copied from the site, because sprint is mandatory."""
	source = frappe.db.get_value("Work Item", {}, "name")
	doc = frappe.copy_doc(frappe.get_doc("Work Item", source))
	doc.title = f"_Test earlier report {frappe.generate_hash(length=8)}"
	doc.orchestrator = 0
	doc.assignee_user = None
	doc.pr_link = None
	doc.insert(ignore_permissions=True)
	return doc.name


def _comment(work_item: str, content: str):
	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": "Work Item",
			"reference_name": work_item,
			"content": content,
		}
	).insert(ignore_permissions=True)


def _brief(work_item: str) -> str:
	script = frappe.db.get_value("Server Script", patch.SCRIPT, "script")
	scope = {"context_docname": work_item, "result": {}}
	safe_exec(script, None, scope)
	return scope["result"]["work_item_brief"]


class TestCriteriaPrompt(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("AI Agent Configuration", patch.AGENT):
			self.skipTest(f"{patch.AGENT} is not on this site")

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _prompt(self):
		return frappe.db.get_value("AI Agent Configuration", patch.AGENT, "system_prompt") or ""

	def test_the_rules_land_once_and_keep_the_prompt_before_them(self):
		head = self._prompt().split(patch.marker())[0].rstrip() or "Do the job."
		frappe.db.set_value("AI Agent Configuration", patch.AGENT, "system_prompt", head, update_modified=False)

		patch.execute()
		patch.execute()

		prompt = self._prompt()
		self.assertEqual(prompt.count(patch.marker()), 1)
		self.assertTrue(prompt.startswith(head))
		self.assertIn("AC1, AC2", prompt)
		self.assertIn("NOT REPRODUCIBLE", prompt)

	def test_a_reworded_rule_replaces_the_block(self):
		stale = patch.marker() + "\n- an old rule nobody wants any more\n"
		frappe.db.set_value(
			"AI Agent Configuration", patch.AGENT, "system_prompt", "Do the job.\n\n" + stale, update_modified=False
		)

		patch.execute()

		self.assertNotIn("an old rule nobody wants", self._prompt())
		self.assertTrue(self._prompt().startswith("Do the job."))


class TestEarlierReportInTheBrief(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("Server Script", patch.SCRIPT):
			self.skipTest("the Orchestrator brief script is not on this site")
		if not frappe.db.get_value("Work Item", {}, "name"):
			self.skipTest("the site has no Work Item to copy")
		frappe.db.set_value("Server Script", patch.SCRIPT, "script", BASE_SCRIPT, update_modified=False)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_the_brief_carries_the_last_report_left_on_the_work_item(self):
		work_item = _work_item()
		_comment(work_item, "<b>Orchestrator</b><br>The Dev Agent stopped at the migrate step.")

		patch.execute()

		brief = _brief(work_item)
		self.assertIn("Earlier report from the orchestrator", brief)
		self.assertIn("stopped at the migrate step", brief)
		self.assertNotIn("<b>", brief)

	def test_the_newest_report_wins(self):
		work_item = _work_item()
		_comment(work_item, "<b>Orchestrator</b><br>First attempt failed on tests.")
		frappe.db.set_value("Comment", {"reference_name": work_item}, "creation", "2026-01-01 00:00:00.000000")
		_comment(work_item, "<b>Orchestrator</b><br>Second attempt opened no pull request.")

		patch.execute()

		brief = _brief(work_item)
		self.assertIn("Second attempt opened no pull request", brief)
		self.assertNotIn("First attempt failed", brief)

	def test_a_work_item_without_a_report_keeps_its_brief(self):
		work_item = _work_item()

		patch.execute()

		self.assertEqual(_brief(work_item), "Header\nThe brief")

	def test_the_script_is_patched_once(self):
		patch.execute()
		patch.execute()

		script = frappe.db.get_value("Server Script", patch.SCRIPT, "script")
		self.assertEqual(script.count(patch.MARKER), 1)
