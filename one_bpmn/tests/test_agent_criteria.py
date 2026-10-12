# Copyright (c) 2026, one-fm and contributors
"""Acceptance criteria are read from the delegation, held against the plan and the diff, and shown on the PR."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import agent_criteria as criteria
from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops
from one_bpmn.one_bpmn.patches.v1_0 import sandbox_tool_submit_evidence as evidence_tool

INSTRUCTION = """Build the thing.

AC1: A new field exists on the form.
- AC2. The field is validated.
**AC3** - The change has a test.
AC1: a duplicate that must be ignored.
Some other line.
"""
INSTANCE = SimpleNamespace(name="inst-crit", context_doctype="A2A Task", context_docname="A2A-1", process_model="Dev Agent")
WORK_ITEM = "WI-CRIT-1"


def _row(action, args, work_item=WORK_ITEM):
	doc = frappe.get_doc({
		"doctype": "Agent Sandbox Run", "state": "completed", "target_app": "one_bpmn", "action": action,
		"work_item": work_item, "caller_instance": INSTANCE.name,
		"request_payload": frappe.as_json({"action": action, "args": args}),
	})
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)
	return doc


def _with_instruction(text=INSTRUCTION):
	return patch.object(ops, "_a2a_instruction", return_value=text)


class TestReadingTheCriteria(FrappeTestCase):
	def test_numbered_criteria_are_read_in_order_without_duplicates(self):
		with _with_instruction():
			found = criteria.criteria_for(INSTANCE)
		self.assertEqual([c["id"] for c in found], ["AC1", "AC2", "AC3"])
		self.assertEqual(found[0]["text"], "A new field exists on the form.")

	def test_an_instruction_without_criteria_gives_none(self):
		with _with_instruction("Just do it."):
			self.assertEqual(criteria.criteria_for(INSTANCE), [])

	def test_a_run_that_is_not_a_delegation_has_none(self):
		self.assertEqual(criteria.criteria_for(SimpleNamespace(name="x", context_doctype="Work Item")), [])
		self.assertEqual(criteria.criteria_for(None), [])


class TestThePlanMustCoverEveryCriterion(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_no_criteria_means_no_gap(self):
		with _with_instruction("Just do it."):
			self.assertIsNone(criteria.plan_gap_error(INSTANCE))

	def test_no_plan_at_all_names_every_criterion(self):
		with _with_instruction():
			error = criteria.plan_gap_error(INSTANCE)
		self.assertIn("AC1, AC2, AC3", error)
		self.assertIn("submit_plan", error)

	def test_a_plan_that_skips_a_criterion_names_only_that_one(self):
		_row(ops._PLAN_ACTION, {"plan": "Change form.py for AC1. Add test for AC3."})
		with _with_instruction():
			error = criteria.plan_gap_error(INSTANCE)
		self.assertIn("does not address AC2", error)
		self.assertNotIn("AC1,", error)

	def test_a_plan_that_covers_all_passes(self):
		_row(ops._PLAN_ACTION, {"plan": "AC1 form.py; AC2 validate; AC3 test_form.py"})
		with _with_instruction():
			self.assertIsNone(criteria.plan_gap_error(INSTANCE))

	def test_a_longer_id_does_not_count_for_a_shorter_one(self):
		_row(ops._PLAN_ACTION, {"plan": "AC10 AC20 AC30"})
		with _with_instruction():
			self.assertIn("AC1, AC2, AC3", criteria.plan_gap_error(INSTANCE))

	def test_the_latest_plan_is_the_one_that_counts(self):
		_row(ops._PLAN_ACTION, {"plan": "only AC1"})
		_row(ops._PLAN_ACTION, {"plan": "AC1 AC2 AC3 all covered"})
		with _with_instruction():
			self.assertIsNone(criteria.plan_gap_error(INSTANCE))


class TestEditsAreHeldUntilThePlanCovers(FrappeTestCase):
	def _dispatch(self, action):
		with patch.object(ops, "dispatch_error", return_value=None), patch.object(
			ops, "frontend_edit_error", return_value=None
		), patch.object(criteria, "plan_gap_error", return_value="Your plan does not address AC2.") as gap:
			return ops.sandbox_dispatch(action, "one_bpmn", "staging", "d", {"path": "a.py"}, instance=INSTANCE), gap

	def test_every_changing_action_is_refused_with_the_gap(self):
		for action in ("edit_file", "write_file", "apply_edits", "delete_file"):
			out, _ = self._dispatch(action)
			self.assertEqual(out, {"ok": False, "error": "Your plan does not address AC2."}, action)

	def test_reading_is_never_held(self):
		with patch.object(ops, "dispatch_error", return_value=None), patch.object(
			criteria, "plan_gap_error", return_value="gap"
		) as gap, patch.object(ops, "_edited_paths", return_value=[]):
			ops.sandbox_dispatch("read_file", "one_bpmn", "staging", "d", {"path": "a.py"}, instance=None)
		gap.assert_not_called()


class TestThePullRequestWaitsForEvidence(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_no_criteria_means_no_wait(self):
		with _with_instruction("Just do it."):
			self.assertIsNone(criteria.evidence_gap_error(INSTANCE))

	def test_criteria_without_evidence_hold_the_pull_request(self):
		with _with_instruction():
			self.assertIn("submit_evidence", criteria.evidence_gap_error(INSTANCE))

	def test_evidence_with_problems_still_holds_it(self):
		_row(criteria.EVIDENCE_ACTION, {"criteria": [], "evidence": [], "problems": ["AC2 has no row."]})
		with _with_instruction():
			self.assertIn("submit_evidence", criteria.evidence_gap_error(INSTANCE))

	def test_accepted_evidence_lets_it_through_even_with_unmet_criteria(self):
		_row(criteria.EVIDENCE_ACTION, {"criteria": [], "evidence": [{"id": "AC1", "status": "not_done"}], "problems": []})
		with _with_instruction():
			self.assertIsNone(criteria.evidence_gap_error(INSTANCE))

	def test_open_pull_request_is_refused_until_then_and_no_run_is_created(self):
		before = frappe.db.count("Agent Sandbox Run")
		with patch.object(ops, "dispatch_error", return_value=None), patch.object(
			criteria, "evidence_gap_error", return_value="Call submit_evidence first."
		), self.assertRaises(ops.AgentSandboxError):
			ops.dispatch_action(
				{"target_app": "one_bpmn", "git_branch": "staging", "work_item_description": "d"},
				{"instance": INSTANCE, "task": SimpleNamespace(id="t", data={}, task_spec=SimpleNamespace(bpmn_id="x", name="x")), "operation": "open_pull_request"},
			)
		self.assertEqual(frappe.db.count("Agent Sandbox Run"), before)


class TestAGateAppliesOnlyWhereTheStepExists(FrappeTestCase):
	"""A gate that asks for a plan or evidence the agent has no tool to give would block it for good."""

	MODEL = "_Test Gate Tools"
	INSTANCE = SimpleNamespace(name="i-gate", context_doctype="A2A Task", context_docname="A2A-1", process_model=MODEL)

	def setUp(self):
		super().setUp()
		self._forget()

	def tearDown(self):
		self._forget()
		frappe.db.rollback()
		super().tearDown()

	def _forget(self):
		for script in ("Submit Plan", "Submit Evidence"):
			frappe.cache.delete_value(f"agent_has_tool:{self.MODEL}:{script}")

	def _map(self, xml):
		"""Serve this XML as the agent's map and leave every other lookup alone."""
		real = frappe.db.get_value

		def get_value(*args, **kwargs):
			if args[:2] == ("BPMN Process Model", self.MODEL):
				return xml
			return real(*args, **kwargs)

		return patch.object(frappe.db, "get_value", side_effect=get_value)

	@staticmethod
	def _tool(script):
		return f'<d><scriptTask id="t" serverScript="{script}"/></d>'

	def test_an_agent_with_no_plan_tool_is_not_held_to_the_plan_gate(self):
		with self._map(self._tool("Sandbox Tool: Edit File")), _with_instruction():
			self.assertIsNone(criteria.plan_gap_error(self.INSTANCE))

	def test_an_agent_with_a_plan_tool_is_held_to_it(self):
		with self._map(self._tool("Sandbox Tool: Submit Plan")), _with_instruction():
			self.assertIn("submit_plan", criteria.plan_gap_error(self.INSTANCE))

	def test_a_bug_agents_own_plan_tool_name_counts(self):
		with self._map(self._tool("Bug Agent: Sandbox Tool: Submit Plan")):
			self.assertTrue(criteria.has_tool(self.INSTANCE, "Submit Plan"))

	def test_an_agent_with_no_evidence_tool_may_open_its_pull_request(self):
		with self._map("<d></d>"), _with_instruction():
			self.assertIsNone(criteria.evidence_gap_error(self.INSTANCE))

	def test_an_agent_with_the_evidence_tool_must_use_it(self):
		with self._map(self._tool("Sandbox Tool: Submit Evidence")), _with_instruction():
			self.assertIn("submit_evidence", criteria.evidence_gap_error(self.INSTANCE))

	def test_a_map_that_cannot_be_found_keeps_the_gate_on(self):
		with self._map(None), _with_instruction():
			self.assertIn("submit_plan", criteria.plan_gap_error(self.INSTANCE))

	def test_the_answer_is_remembered(self):
		with self._map("<d></d>"):
			criteria.has_tool(self.INSTANCE, "Submit Plan")
		with patch.object(frappe.db, "get_value", side_effect=AssertionError("looked it up again")):
			self.assertFalse(criteria.has_tool(self.INSTANCE, "Submit Plan"))


class TestEvidenceProblems(FrappeTestCase):
	CRITERIA = [{"id": "AC1", "text": "a"}, {"id": "AC2", "text": "b"}]
	FILES = ["one_bpmn/forms/todo.py", "one_bpmn/tests/test_todo.py"]

	def _problems(self, rows, files=FILES):
		return criteria.evidence_problems(self.CRITERIA, rows, files)

	def test_a_complete_table_citing_changed_files_has_no_problems(self):
		rows = [{"id": "AC1", "status": "done", "evidence": "todo.py line 4"}, {"id": "AC2", "status": "partial", "evidence": ""}]
		self.assertEqual(self._problems(rows), [])

	def test_a_missing_criterion_is_named(self):
		self.assertEqual(self._problems([{"id": "AC1", "status": "not_done"}]), ["AC2 has no row."])

	def test_an_unknown_status_is_refused(self):
		self.assertIn("status must be one of", self._problems([{"id": "AC1", "status": "finished"}, {"id": "AC2", "status": "done", "evidence": "todo.py"}])[0])

	def test_done_without_evidence_is_refused(self):
		rows = [{"id": "AC1", "status": "done", "evidence": "  "}, {"id": "AC2", "status": "not_done"}]
		self.assertEqual(self._problems(rows), ["AC1: done needs evidence, a changed file or a test name."])

	def test_done_citing_nothing_on_the_branch_is_refused(self):
		rows = [{"id": "AC1", "status": "done", "evidence": "elsewhere.py"}, {"id": "AC2", "status": "not_done"}]
		self.assertIn("names no file changed on this branch", self._problems(rows)[0])

	def test_a_test_name_counts_as_evidence(self):
		rows = [{"id": "AC1", "status": "done", "evidence": "test_todo.test_it passes"}, {"id": "AC2", "status": "not_done"}]
		self.assertEqual(self._problems(rows), [])

	def test_when_the_diff_is_unknown_a_written_evidence_is_accepted(self):
		rows = [{"id": "AC1", "status": "done", "evidence": "elsewhere.py"}, {"id": "AC2", "status": "not_done"}]
		self.assertEqual(self._problems(rows, files=None), [])


class TestRecordingEvidence(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _record(self, rows, files=("one_bpmn/a.py",)):
		with _with_instruction(), patch.object(ops, "work_item_id_for", return_value=WORK_ITEM), patch.object(
			criteria, "_branch_files", return_value=list(files)
		):
			return criteria.record_evidence("one_bpmn", "staging", "d", rows, instance=INSTANCE)

	def test_a_good_table_is_recorded_and_the_unmet_are_named(self):
		out = self._record([
			{"id": "AC1", "status": "done", "evidence": "a.py"},
			{"id": "AC2", "status": "partial", "evidence": "a.py"},
			{"id": "AC3", "status": "not_done", "evidence": ""},
		])
		self.assertTrue(out["ok"])
		self.assertEqual(out["unmet"], ["AC2", "AC3"])
		self.assertEqual(frappe.db.count("Agent Sandbox Run", {"action": criteria.EVIDENCE_ACTION, "work_item": WORK_ITEM}), 1)

	def test_a_bad_table_is_recorded_and_sent_back_with_the_problems(self):
		out = self._record([{"id": "AC1", "status": "done", "evidence": "zzz"}])
		self.assertFalse(out["ok"])
		self.assertIn("AC2 has no row.", out["problems"])

	def test_no_criteria_records_nothing(self):
		with _with_instruction("Just do it."):
			out = criteria.record_evidence("one_bpmn", "staging", "d", [], instance=INSTANCE)
		self.assertTrue(out["ok"])
		self.assertEqual(frappe.db.count("Agent Sandbox Run", {"action": criteria.EVIDENCE_ACTION, "work_item": WORK_ITEM}), 0)

	def test_a_table_that_is_not_a_list_is_a_bad_table(self):
		out = self._record("everything is done")
		self.assertFalse(out["ok"])


class TestTheCriteriaReport(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	CRITERIA = [{"id": "AC1", "text": "Field | exists"}, {"id": "AC2", "text": "Validated"}]

	def test_a_work_item_with_no_criteria_has_no_report(self):
		self.assertEqual(criteria.criteria_report(WORK_ITEM), {"has_criteria": False, "unmet": [], "markdown": ""})

	def test_the_latest_evidence_fills_the_table_and_names_the_unmet(self):
		_row(criteria.EVIDENCE_ACTION, {"criteria": self.CRITERIA, "evidence": [{"id": "AC1", "status": "partial", "evidence": "a.py"}]})
		_row(criteria.EVIDENCE_ACTION, {"criteria": self.CRITERIA, "evidence": [
			{"id": "AC1", "status": "done", "evidence": "a.py"}, {"id": "AC2", "status": "not_done", "evidence": ""},
		]})
		report = criteria.criteria_report(WORK_ITEM)
		self.assertEqual(report["unmet"], ["AC2"])
		self.assertIn("| AC1: Field / exists | done | a.py |", report["markdown"])
		self.assertIn("| AC2: Validated | not_done |  |", report["markdown"])

	def test_with_only_a_plan_every_criterion_is_not_reported(self):
		_row(ops._PLAN_ACTION, {"plan": "p", "criteria": self.CRITERIA})
		report = criteria.criteria_report(WORK_ITEM)
		self.assertEqual(report["unmet"], ["AC1", "AC2"])
		self.assertIn("not reported", report["markdown"])


class TestPublishingToThePullRequest(FrappeTestCase):
	CRITERIA = [{"id": "AC1", "text": "one"}, {"id": "AC2", "text": "two"}]

	def setUp(self):
		source = frappe.db.get_value("Work Item", {}, "name")
		if not source:
			self.skipTest("the site has no Work Item to copy")
		item = frappe.copy_doc(frappe.get_doc("Work Item", source))
		item.title = f"_Test criteria {frappe.generate_hash(length=8)}"
		item.orchestrator = 0
		item.assignee_user = None
		item.pr_link = None
		item.insert(ignore_permissions=True)
		self.work_item = item.name

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _evidence(self, statuses):
		_row(criteria.EVIDENCE_ACTION, {"criteria": self.CRITERIA, "evidence": [
			{"id": f"AC{i + 1}", "status": s, "evidence": "a.py"} for i, s in enumerate(statuses)
		]}, work_item=self.work_item)

	def _publish(self, pr):
		with patch.object(criteria, "_github") as github, patch("frappe.model.document.Document.add_comment") as comment:
			out = criteria.publish_criteria(self.work_item, "o/r", pr, "tok")
		return out, github, comment

	def test_nothing_is_published_for_a_work_item_with_no_criteria(self):
		out, github, _ = self._publish({"number": 7, "body": "b"})
		self.assertEqual(out, {})
		github.assert_not_called()

	def test_all_done_adds_the_table_and_leaves_the_pr_as_it_is(self):
		self._evidence(["done", "done"])
		out, github, comment = self._publish({"number": 7, "body": "Summary", "draft": False, "node_id": "N"})
		self.assertEqual(out, {"criteria_unmet": []})
		github.assert_called_once()
		method, path, _tok, payload = github.call_args.args
		self.assertEqual((method, path), ("PATCH", "/repos/o/r/pulls/7"))
		self.assertTrue(payload["body"].startswith("Summary"))
		self.assertIn("## Acceptance criteria", payload["body"])
		comment.assert_not_called()

	def test_unmet_criteria_are_named_and_a_ready_pr_becomes_a_draft(self):
		self._evidence(["done", "not_done"])
		out, github, comment = self._publish({"number": 7, "body": "S", "draft": False, "node_id": "N"})
		self.assertEqual(out, {"criteria_unmet": ["AC2"]})
		calls = [c.args[:2] for c in github.call_args_list]
		self.assertEqual(calls, [("PATCH", "/repos/o/r/pulls/7"), ("POST", "/graphql")])
		self.assertIn("Unmet: AC2", github.call_args_list[0].args[3]["body"])
		self.assertEqual(github.call_args_list[1].args[3]["variables"], {"id": "N"})
		comment.assert_called_once()

	def test_a_pr_that_is_already_a_draft_is_not_converted_again(self):
		self._evidence(["not_done", "done"])
		_out, github, _ = self._publish({"number": 7, "body": "S", "draft": True, "node_id": "N"})
		self.assertEqual([c.args[1] for c in github.call_args_list], ["/repos/o/r/pulls/7"])

	def test_publishing_again_replaces_the_section_and_does_nothing_when_unchanged(self):
		self._evidence(["done", "not_done"])
		first, github, _ = self._publish({"number": 7, "body": "S", "draft": True})
		body = github.call_args_list[0].args[3]["body"]
		second, again, comment = self._publish({"number": 7, "body": body, "draft": True})
		self.assertEqual(body.count("## Acceptance criteria"), 1)
		again.assert_not_called()
		comment.assert_not_called()

	def test_a_stale_section_is_replaced_not_duplicated(self):
		self._evidence(["done", "done"])
		old = "S\n\n## Acceptance criteria\n\nold table\n\n## Other\n\nkept"
		_out, github, _ = self._publish({"number": 7, "body": old, "draft": False})
		body = github.call_args_list[0].args[3]["body"]
		self.assertEqual(body.count("## Acceptance criteria"), 1)
		self.assertNotIn("old table", body)
		self.assertIn("## Other\n\nkept", body)


class TestTheSubmitEvidenceScript(FrappeTestCase):
	def setUp(self):
		evidence_tool.execute()

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _run(self, task_data):
		script = frappe.db.get_value("Server Script", evidence_tool.NAME, "script")
		result = {}
		record = MagicMock(return_value={"ok": True})
		with patch.object(criteria, "record_evidence", record):
			exec(script, {
				"frappe": frappe, "result": result, "instance": INSTANCE, "bpmn_id": "x", "__builtins__": __builtins__,
				"task_data": {"target_app": "one_bpmn", "git_branch": "staging", "work_item_description": "d", **task_data},
			})
		return result, record

	def test_the_script_exists_and_is_not_a_public_endpoint(self):
		row = frappe.db.get_value("Server Script", evidence_tool.NAME, ["script_type", "api_method"], as_dict=True)
		self.assertEqual(row.script_type, "API")
		self.assertFalse(row.api_method)

	def test_the_table_is_handed_to_record_evidence(self):
		rows = [{"id": "AC1", "status": "done", "evidence": "a.py"}]
		result, record = self._run({"evidence": rows})
		self.assertEqual(result, {"ok": True})
		self.assertEqual(record.call_args.args[3], rows)

	def test_a_missing_table_is_refused_without_recording(self):
		for bad in (None, [], "done"):
			result, record = self._run({"evidence": bad})
			self.assertIn("evidence is required", result["error"])
			record.assert_not_called()

	def test_a_missing_brief_is_refused(self):
		result, record = self._run({"evidence": [{"id": "AC1"}], "git_branch": ""})
		self.assertIn("all required", result["error"])
		record.assert_not_called()
