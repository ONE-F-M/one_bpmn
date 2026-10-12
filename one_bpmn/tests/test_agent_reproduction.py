# Copyright (c) 2026, one-fm and contributors
"""The not-reproducible outcome, the reproduction record on the pull request, and the bug agents patch."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import agent_criteria as criteria
from one_bpmn.one_bpmn.connectors import agent_reproduction as repro
from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops
from one_bpmn.one_bpmn.patches.v1_0 import bug_agents_report_not_reproducible_and_keep_discipline as patch_module

INSTANCE = SimpleNamespace(name="inst-bug", context_doctype="A2A Task", context_docname="A2A-9", process_model="Bug Programmer")
FAILING = {"failing_tests": ["test_it (one_fm.tests.test_company.TestCompany.test_it)"], "stderr_tail": "Traceback\nAssertionError: 1 != 2"}


def _run(action, state="completed", work_item="WI-BUG-1", result=None, commit=None, args=None, instance=INSTANCE.name):
	doc = frappe.get_doc({
		"doctype": "Agent Sandbox Run", "state": state, "target_app": "one_fm", "action": action, "work_item": work_item,
		"caller_instance": instance, "commit_sha": commit,
		"request_payload": frappe.as_json({"action": action, "args": args or {}}),
		"result": json.dumps(result) if result is not None else None,
	})
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)
	return doc


class ReproCase(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()


class TestNotReproducible(ReproCase):
	def _record(self, tried="Wrote a test, it passes.", needed="The steps the user took."):
		with patch.object(ops, "work_item_id_for", return_value="WI-BUG-1"):
			return repro.record_not_reproducible("one_fm", "staging", "d", tried, needed, instance=INSTANCE)

	def test_the_outcome_is_recorded_and_the_agent_is_told_to_stop(self):
		out = self._record()
		self.assertEqual((out["ok"], out["outcome"]), (True, "not_reproducible"))
		self.assertIn("NOT REPRODUCIBLE", out["message"])
		row = frappe.get_all("Agent Sandbox Run", filters={"action": repro.NOT_REPRODUCIBLE_ACTION, "work_item": "WI-BUG-1"}, fields=["failure_class", "state"])[0]
		self.assertEqual((row.state, row.failure_class), ("completed", "not-reproducible"))

	def test_a_run_that_reported_it_can_make_no_further_change(self):
		self._record()
		self.assertIn("not reproducible", repro.not_reproducible_error(INSTANCE))

	def test_a_run_that_did_not_report_it_is_not_held(self):
		self.assertIsNone(repro.not_reproducible_error(INSTANCE))
		self.assertIsNone(repro.not_reproducible_error(None))

	def test_the_flagged_agent_is_refused_every_change_after_reporting(self):
		self._record()
		with patch.object(ops, "requires_reproduction", return_value=True):
			error = ops._discipline_error(INSTANCE, "write_file", {"path": "one_fm/tests/test_x.py"})
		self.assertIn("not reproducible", error)

	def test_the_item_gets_a_comment_with_what_was_tried_and_what_is_needed(self):
		source = frappe.db.get_value("Work Item", {}, "name")
		if not source:
			self.skipTest("the site has no Work Item to copy")
		item = frappe.copy_doc(frappe.get_doc("Work Item", source))
		item.title = f"_Test not reproducible {frappe.generate_hash(length=8)}"
		item.orchestrator = 0
		item.assignee_user = None
		item.pr_link = None
		item.insert(ignore_permissions=True)
		with patch.object(ops, "work_item_id_for", return_value=item.name):
			repro.record_not_reproducible("one_fm", "staging", "d", "Wrote <b>a</b> test.", "The steps.", instance=INSTANCE)
		text = frappe.get_all("Comment", filters={"reference_doctype": "Work Item", "reference_name": item.name}, pluck="content")[0]
		self.assertIn("Could not reproduce", text)
		self.assertIn("The steps.", text)
		self.assertIn("&lt;b&gt;", text)


class TestTheReproductionRecord(ReproCase):
	def test_no_failing_test_gives_no_section(self):
		_run("run_tests", state="completed")
		self.assertEqual(repro.reproduction_section("WI-BUG-1"), "")

	def test_a_failing_then_passing_run_gives_the_test_the_output_and_both_commits(self):
		_run("run_tests", state="failed", result=FAILING, commit="a" * 40)
		_run("run_tests", state="completed", commit="b" * 40)
		section = repro.reproduction_section("WI-BUG-1")
		self.assertIn("Test: `test_it (one_fm.tests.test_company.TestCompany.test_it)`", section)
		self.assertIn("Failed before the fix (commit aaaaaaaaaa):", section)
		self.assertIn("AssertionError: 1 != 2", section)
		self.assertIn("Passes after the fix (commit bbbbbbbbbb).", section)

	def test_a_failure_with_no_passing_run_after_it_says_so(self):
		_run("run_tests", state="failed", result=FAILING)
		self.assertIn("No passing run after the fix is recorded.", repro.reproduction_section("WI-BUG-1"))

	def test_the_output_is_cut_to_its_end(self):
		_run("run_tests", state="failed", result={**FAILING, "stderr_tail": "x" * 5000 + "THE END"})
		section = repro.reproduction_section("WI-BUG-1")
		self.assertIn("THE END", section)
		self.assertLess(len(section), 2200)

	def test_another_work_items_runs_are_not_used(self):
		_run("run_tests", state="failed", result=FAILING, work_item="WI-OTHER")
		self.assertEqual(repro.reproduction_section("WI-BUG-1"), "")

	def test_a_passing_run_before_any_failure_is_not_taken_as_the_fix(self):
		_run("run_tests", state="completed", commit="c" * 40)
		_run("run_tests", state="failed", result=FAILING, commit="a" * 40)
		self.assertIn("No passing run after the fix is recorded.", repro.reproduction_section("WI-BUG-1"))


class TestItGoesOnThePullRequest(ReproCase):
	def _publish(self, body="Summary"):
		with patch.object(criteria, "_github") as github, patch("frappe.model.document.Document.add_comment"):
			out = criteria.publish_criteria("WI-BUG-1", "o/r", {"number": 5, "body": body, "draft": True}, "tok")
		return out, github

	def test_the_section_is_added_in_one_update(self):
		_run("run_tests", state="failed", result=FAILING, commit="a" * 40)
		_run("run_tests", state="completed", commit="b" * 40)
		out, github = self._publish()
		github.assert_called_once()
		body = github.call_args.args[3]["body"]
		self.assertTrue(body.startswith("Summary"))
		self.assertIn("## Reproduction", body)
		self.assertEqual(out, {})

	def test_publishing_again_replaces_the_section_and_changes_nothing_when_the_same(self):
		_run("run_tests", state="failed", result=FAILING)
		_out, github = self._publish()
		body = github.call_args.args[3]["body"]
		_out, again = self._publish(body)
		self.assertEqual(body.count("## Reproduction"), 1)
		again.assert_not_called()

	def test_a_work_item_with_neither_criteria_nor_a_reproduction_is_left_alone(self):
		out, github = self._publish()
		self.assertEqual(out, {})
		github.assert_not_called()


class TestTheBugAgentsPatch(ReproCase):
	def setUp(self):
		super().setUp()
		self.present = [a for a in patch_module.AGENTS if frappe.db.exists("AI Agent Configuration", a)]

	def test_the_tool_script_exists_without_a_public_endpoint_and_is_restored_when_edited(self):
		patch_module.execute()
		row = frappe.db.get_value("Server Script", patch_module.TOOL, ["script_type", "api_method"], as_dict=True)
		self.assertEqual(row.script_type, "API")
		self.assertFalse(row.api_method)
		frappe.db.set_value("Server Script", patch_module.TOOL, "script", "result['x']=1")
		patch_module.execute()
		self.assertEqual(frappe.db.get_value("Server Script", patch_module.TOOL, "script"), patch_module.SCRIPT)

	def test_the_flag_the_rules_and_the_cap_land_once(self):
		if not self.present:
			self.skipTest("no bug agent is on this site")
		for name in self.present:
			frappe.db.set_value("AI Agent Configuration", name, {"system_prompt": "Do it.", "max_tool_calls": 15, "max_retries": 1, "require_reproduction": 0}, update_modified=False)
		patch_module.execute()
		patch_module.execute()
		for name in self.present:
			config = frappe.db.get_value("AI Agent Configuration", name, ["system_prompt", "max_tool_calls", "require_reproduction"], as_dict=True)
			self.assertTrue(config.system_prompt.startswith("Do it."), name)
			self.assertEqual(config.system_prompt.count(patch_module.marker()), 1, name)
			self.assertEqual(config.max_tool_calls, patch_module.MAX_TOOL_CALLS, name)
			self.assertEqual(frappe.db.get_value("AI Agent Configuration", name, "max_retries"), patch_module.MODEL_RETRIES, name)
			self.assertEqual(bool(config.require_reproduction), name in patch_module.HELD, name)

	def test_each_agent_is_only_told_about_tools_its_map_has(self):
		self.assertNotIn("apply_edits", patch_module.RULES["Bug Planner"])
		self.assertNotIn("report_not_reproducible", patch_module.RULES["Bug Planner"])
		self.assertNotIn("apply_edits", patch_module.RULES["Bug Reviewer"])
		self.assertNotIn("report_not_reproducible", patch_module.RULES["Bug Reviewer"])
		self.assertIn("report_not_reproducible", patch_module.RULES["Bug Programmer"])
		self.assertIn("apply_edits", patch_module.RULES["Bug Programmer"])

	def test_the_planner_is_never_held_to_reproduction_and_the_reviewer_is(self):
		self.assertNotIn("Bug Planner", patch_module.HELD)
		self.assertIn("Bug Reviewer", patch_module.HELD)

	def test_the_script_hands_the_story_to_record_not_reproducible(self):
		patch_module.execute()
		script = frappe.db.get_value("Server Script", patch_module.TOOL, "script")
		record = MagicMock(return_value={"ok": True})
		result = {}
		with patch.object(repro, "record_not_reproducible", record):
			exec(script, {"frappe": frappe, "result": result, "instance": INSTANCE, "bpmn_id": "x", "__builtins__": __builtins__,
				"task_data": {"target_app": "one_fm", "git_branch": "staging", "work_item_description": "d", "tried": "Ran it.", "needed": "Steps."}})
		self.assertEqual(result, {"ok": True})
		self.assertEqual(record.call_args.args[3:5], ("Ran it.", "Steps."))
		refused = {}
		with patch.object(repro, "record_not_reproducible", record):
			exec(script, {"frappe": frappe, "result": refused, "instance": INSTANCE, "bpmn_id": "x", "__builtins__": __builtins__,
				"task_data": {"target_app": "one_fm", "git_branch": "staging", "work_item_description": "d", "tried": "  "}})
		self.assertIn("tried is required", refused["error"])


class TestTheReviewerSeesTheProgrammersWork(ReproCase):
	def test_a_pull_request_check_looks_at_every_agents_calls_for_the_work_item(self):
		_run("edit_file", args={"path": "one_fm/company.py"}, instance="inst-programmer")
		_run("run_tests", instance="inst-programmer")
		reviewer = SimpleNamespace(name="inst-reviewer", context_doctype="A2A Task", context_docname="A2A-10", process_model="Bug Reviewer")
		with patch.object(ops, "work_item_id_for", return_value="WI-BUG-1"):
			self.assertIsNone(ops.fix_unverified_error(reviewer))

	def test_without_a_work_item_only_its_own_calls_are_looked_at(self):
		_run("edit_file", args={"path": "one_fm/company.py"}, instance="inst-programmer", work_item="")
		_run("run_tests", instance="inst-programmer", work_item="")
		lone = SimpleNamespace(name="inst-lone", process_model="Bug Reviewer")
		self.assertIn("Make the fix first", ops.fix_unverified_error(lone))


class TestTheCommitIsRecorded(ReproCase):
	def test_a_test_result_stores_the_commit_it_ran_against(self):
		run = _run("run_tests", state="running")
		with patch("one_bpmn.api.agent_callback._create_sandbox_ai_agent_run", return_value=None), patch(
			"one_bpmn.api.agent_callback._enqueue_resume"
		):
			from one_bpmn.api import agent_callback as cb

			cb._settle(run, {"status": "tests_failed", "failing_tests": ["t"], "commit": "f" * 40, "correlation_id": run.name})
		self.assertEqual(frappe.db.get_value("Agent Sandbox Run", run.name, "commit_sha"), "f" * 40)
