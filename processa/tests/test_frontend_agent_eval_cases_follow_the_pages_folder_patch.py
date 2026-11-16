# Copyright (c) 2026, one-fm and contributors
"""Eval cases and their fixtures name the Processa pages by their new paths, and nothing else changes."""

from __future__ import annotations

import os

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0 import frontend_agent_eval_cases_follow_the_pages_folder as patch

OLD = "spiff/src/views/Insights.vue"
NEW = "spiff/src/pages/Insights.vue"
MOBILE = "Add a screen at src/views/payroll/PayslipHistory.vue showing overtime."


class TestFrontendAgentEvalCasesFollowThePagesFolderPatch(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _task(self, payload: str, result: str) -> str:
		return frappe.get_doc(
			{"doctype": "A2A Task", "direction": "Internal", "request_payload": payload, "result": result}
		).insert().name

	def _case(self, title: str, prompt: str, task: str | None = None) -> str:
		context = frappe.as_json({"context_docname": task}) if task else None
		return frappe.get_doc(
			{"doctype": "AI Eval Case", "title": title, "input_user_prompt": prompt, "input_context": context}
		).insert().name

	def test_the_prompt_and_its_fixture_name_the_new_path_and_the_run_history_is_kept(self):
		task = self._task(f'{{"instruction": "Fix {OLD}"}}', f"edited {OLD}")
		case = self._case("Stale path case", f"Fix the header in {OLD} please.", task)

		patch.execute()

		self.assertEqual(
			frappe.db.get_value("AI Eval Case", case, "input_user_prompt"), f"Fix the header in {NEW} please."
		)
		self.assertEqual(
			frappe.db.get_value("A2A Task", task, "request_payload"), f'{{"instruction": "Fix {NEW}"}}'
		)
		self.assertEqual(frappe.db.get_value("A2A Task", task, "result"), f"edited {OLD}")

	def test_a_mobile_app_case_and_an_unrelated_task_are_left_alone(self):
		task = self._task(f'{{"instruction": "{MOBILE}"}}', "")
		other = self._task(f'{{"instruction": "Fix {OLD}"}}', "")
		case = self._case("Mobile case", MOBILE, task)

		patch.execute()

		self.assertEqual(frappe.db.get_value("AI Eval Case", case, "input_user_prompt"), MOBILE)
		self.assertIn(MOBILE, frappe.db.get_value("A2A Task", task, "request_payload"))
		self.assertIn(OLD, frappe.db.get_value("A2A Task", other, "request_payload"))

	def test_a_second_run_changes_nothing(self):
		case = self._case("Run twice case", f"Fix {OLD}")
		patch.execute()
		patch.execute()
		self.assertEqual(frappe.db.get_value("AI Eval Case", case, "input_user_prompt"), f"Fix {NEW}")

	def test_every_renamed_page_exists_in_the_spa(self):
		for _old, new in patch.PAGE_RENAMES:
			self.assertTrue(os.path.exists(frappe.get_app_path("processa", "..", new)), new)
