# Copyright (c) 2026, one-fm and contributors
"""One Agent Sandbox Trace per agent run lists every call that run made, and follows the calls as they settle."""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


def _run(caller="trace-inst-1", action="read_file", state="completed", args=None, **fields):
	doc = frappe.get_doc(
		{
			"doctype": "Agent Sandbox Run", "state": state, "target_app": "one_fm", "git_branch": "staging",
			"caller_instance": caller, "request_payload": json.dumps({"action": action, "args": args or {}, "work_item_id": "WI-T-1", "agent_name": "Dev Agent"}),
			**fields,
		}
	)
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)
	return doc


def _trace(caller="trace-inst-1"):
	name = frappe.db.get_value("Agent Sandbox Trace", {"caller_instance": caller})
	return frappe.get_doc("Agent Sandbox Trace", name) if name else None


class TestAgentSandboxTrace(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_the_calls_of_one_agent_run_share_one_trace_in_order(self):
		_run(action="list_files")
		_run(action="read_file", args={"path": "one_fm/hooks.py"})
		trace = _trace()
		self.assertEqual(frappe.db.count("Agent Sandbox Trace", {"caller_instance": "trace-inst-1"}), 1)
		self.assertEqual([(line.sequence, line.action) for line in trace.calls], [(1, "list_files"), (2, "read_file")])
		self.assertEqual(trace.call_count, 2)

	def test_a_call_line_says_what_the_call_was_about(self):
		_run(action="grep_files", args={"pattern": "ToDo|allocated_to"})
		_run(action="read_files", args={"paths": ["a.py", "b.py"]})
		self.assertEqual([line.summary for line in _trace().calls], ["ToDo|allocated_to", "a.py, b.py"])

	def test_a_settlement_written_with_db_set_reaches_the_trace(self):
		run = _run(action="run_tests", state="running")
		self.assertEqual(_trace().state, "running")
		run.db_set({"state": "completed", "http_ms": 40, "test_ms": 900, "commit_sha": "abc123"}, update_modified=False)
		trace = _trace()
		self.assertEqual((trace.state, trace.test_ms, trace.http_ms, trace.last_commit_sha), ("finished", 900, 40, "abc123"))
		self.assertEqual(trace.calls[0].state, "completed")
		self.assertEqual(frappe.db.count("Agent Sandbox Trace Call", {"parent": trace.name}), 1)

	def test_the_totals_count_edits_tests_and_failures(self):
		_run(action="edit_file", args={"path": "a.py"})
		_run(action="apply_edits", args={"edits": []})
		_run(action="edit_file", state="failed", error_message="old_string not found")
		_run(action="run_tests", state="failed", error_message="1 test failed")
		trace = _trace()
		self.assertEqual((trace.edit_count, trace.test_runs, trace.failed_calls), (2, 1, 2))
		self.assertEqual(trace.last_error, "1 test failed")

	def test_a_run_with_a_call_still_open_keeps_the_trace_running(self):
		_run(action="list_files")
		_run(action="run_tests", state="submitted")
		self.assertEqual(_trace().state, "running")
		self.assertIsNone(_trace().ended_at)

	def test_the_pull_request_url_is_carried_to_the_trace(self):
		_run(action="open_pull_request", pr_url="https://github.com/ONE-F-M/one_fm/pull/1")
		self.assertEqual(_trace().pr_url, "https://github.com/ONE-F-M/one_fm/pull/1")

	def test_the_trace_takes_the_agent_and_work_item_from_its_calls(self):
		_run()
		trace = _trace()
		self.assertEqual((trace.agent_name, trace.work_item, trace.target_app), ("Dev Agent", "WI-T-1", "one_fm"))

	def test_two_agent_runs_get_two_traces(self):
		_run(caller="trace-inst-1")
		_run(caller="trace-inst-2")
		self.assertIsNotNone(_trace("trace-inst-1"))
		self.assertIsNotNone(_trace("trace-inst-2"))
		self.assertNotEqual(_trace("trace-inst-1").name, _trace("trace-inst-2").name)

	def test_a_run_with_no_caller_instance_gets_its_own_trace(self):
		run = _run(caller=None)
		name = frappe.db.get_value("Agent Sandbox Trace Call", {"run": run.name}, "parent")
		self.assertIsNotNone(name)
		run.db_set("state", "failed", update_modified=False)
		self.assertEqual(frappe.db.count("Agent Sandbox Trace Call", {"parent": name}), 1)

	def test_nothing_is_written_before_the_trace_tables_exist(self):
		from one_bpmn.one_bpmn.connectors import agent_sandbox_trace as module

		with patch.object(module, "_tables_exist", return_value=False):
			_run(caller="trace-inst-3")
		self.assertIsNone(_trace("trace-inst-3"))

	def test_back_to_back_edits_of_one_file_are_counted(self):
		for _ in range(3):
			_run(action="edit_file", args={"path": "a.py"})
		self.assertEqual(_trace().repeat_edits, 2)

	def test_an_edit_after_a_test_run_or_of_another_file_is_not_a_repeat(self):
		_run(action="edit_file", args={"path": "a.py"})
		_run(action="run_tests")
		_run(action="edit_file", args={"path": "a.py"})
		_run(action="edit_file", args={"path": "b.py"})
		self.assertEqual(_trace().repeat_edits, 0)
