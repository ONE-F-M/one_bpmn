# Copyright (c) 2026, one-fm and contributors
"""The Logix modify case accepts the department filter however the writer spells it."""

import json
import re

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import logix_diff_case_accepts_the_department_filter as p
from one_bpmn.one_bpmn.patches.v1_0 import seed_logix_baseline_suite as seed

OLD_CHECK = json.dumps({"tool": "finalize", "path": "diff", "matcher": "regex", "expected": '(?m)^\\+.*"Operations'})
COMMENT = "+# Fetch all active employees from the Operations department and count them."
EXACT = '+    filters={"department": "Operations", "status": "Active"},'
LIKE = '+    filters={"department": ["like", "%Operations%"], "status": "Active"},'
UNCHANGED = '     filters={"department": "IT", "status": "Active"},'
OTHER_CASE = "An ambiguous request gets a question with options"


def _pattern() -> re.Pattern:
	spec = next(c for c in seed.CASES if c["title"] == p.MODIFY_CASE)
	check = next(
		json.loads(a["value"])
		for a in spec["assertions"]
		if a["assertion_type"] == "tool_artifact" and p._is_diff_regex(a["value"])
	)
	return re.compile(check["expected"])


class TestTheDiffCheck(FrappeTestCase):
	def test_an_exact_filter_and_a_like_filter_both_pass(self):
		for line in (EXACT, LIKE):
			self.assertTrue(_pattern().search("\n".join(["-" + UNCHANGED[1:], line])), line)

	def test_a_diff_that_only_rewords_the_comment_does_not_pass(self):
		self.assertIsNone(_pattern().search("\n".join(["-# Fetch IT employees.", COMMENT, UNCHANGED])))

	def test_a_diff_that_leaves_the_department_alone_does_not_pass(self):
		self.assertIsNone(_pattern().search("\n".join([UNCHANGED, '+    fields=["name"]'])))


class TestThePatch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("AI Agent Configuration", {"agent_id": seed.AGENT_ID}):
			model = frappe.get_doc(
				{"doctype": "BPMN Process Model", "title": "zz-logix-stub-map", "process_id": "zz_logix_stub", "version": 1}
			)
			model.flags.skip_editability_check = True
			model.flags.skip_script_security_check = True
			model.insert(ignore_permissions=True)
			frappe.get_doc(
				{
					"doctype": "AI Agent Configuration",
					"agent_name": "ZZ Logix Stub",
					"agent_id": seed.AGENT_ID,
					"agent_type": "Background",
					"agent_framework": "Direct API",
					"process_model": model.name,
				}
			).insert(ignore_permissions=True)
		seed.execute()

	def _case(self, title: str):
		suite = frappe.db.get_value("AI Eval Suite", {"title": seed.SUITE_TITLE})
		return frappe.get_doc("AI Eval Case", {"suite": suite, "title": title})

	def _diff_row(self, case):
		return next(r for r in case.assertions if r.assertion_type == "tool_artifact" and p._is_diff_regex(r.value))

	def test_it_refreshes_only_the_diff_check_of_the_modify_case(self):
		case = self._case(p.MODIFY_CASE)
		self._diff_row(case).value = OLD_CHECK
		case.save(ignore_permissions=True)
		before = [(r.assertion_type, r.value) for r in self._case(OTHER_CASE).assertions]

		p.execute()

		refreshed = self._case(p.MODIFY_CASE)
		self.assertEqual(json.loads(self._diff_row(refreshed).value)["expected"], '(?m)^\\+.*"department".*Operations')
		self.assertEqual([(r.assertion_type, r.value) for r in self._case(OTHER_CASE).assertions], before)
		others = [r for r in refreshed.assertions if r.assertion_type == "tool_artifact" and not p._is_diff_regex(r.value)]
		self.assertEqual(len(others), 3)

	def test_running_it_again_changes_nothing(self):
		p.execute()
		name = self._case(p.MODIFY_CASE).name
		first = frappe.db.get_value("AI Eval Case", name, "modified")
		p.execute()

		self.assertEqual(frappe.db.get_value("AI Eval Case", name, "modified"), first)
