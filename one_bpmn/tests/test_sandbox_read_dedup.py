# Copyright (c) 2026, one-fm and contributors
"""read_file hands back a pointer, not a second copy, when a file has not changed.

Whole files come back from the sandbox (it has no ranged read) and every result
is re-sent on every later turn of the run, so a duplicate read is paid for many
times over. The elision lives in the Server Script, which is what the agents
actually run, so that is what these tests execute."""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

SCRIPT = "Sandbox Tool: Read File"
PATH = "spiff/src/components/BpmnEditor.vue"
BIG = "<template>\n" + ("x" * 4000) + "\n</template>\n"


def _run(args, dispatch_result, instance_name="i-test"):
	"""Execute the tool body the way the engine does, with the sandbox stubbed.

	The stub writes no Agent Sandbox Run row, so tests that need "a read this run
	already did" create one with _earlier_read."""
	body = frappe.db.get_value("Server Script", SCRIPT, "script")
	result = {}
	local_vars = {
		"frappe": frappe,
		"result": result,
		"task_data": dict(args),
		"context_docname": None,
		"bpmn_id": "read_file",
		"instance": frappe._dict(name=instance_name),
	}
	with patch(
		"one_bpmn.one_bpmn.connectors.agent_sandbox_ops.sandbox_dispatch",
		return_value=dispatch_result,
	):
		exec(body, {"frappe": frappe, "__builtins__": __builtins__}, local_vars)
	return result


def _earlier_read(instance_name, path, content, state="completed"):
	"""The Agent Sandbox Run row a previous read_file in this run left behind."""
	row = frappe.get_doc({
		"doctype": "Agent Sandbox Run",
		"state": state,
		"target_app": "one_bpmn",
		"git_branch": "staging",
		"bpmn_id": "read_file",
		"caller_instance": instance_name,
		"request_payload": json.dumps({"action": "read_file", "args": {"path": path}}),
		"result": json.dumps({"found": True, "content": content}),
	})
	row.flags.ignore_links = True
	row.insert(ignore_permissions=True)
	return row.name


class TestRepeatReadIsElided(FrappeTestCase):
	def setUp(self):
		self.args = {
			"target_app": "one_bpmn",
			"git_branch": "staging",
			"work_item_description": "Fix the read-only panel.",
			"path": PATH,
		}

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _dispatch(self, content):
		return {"ok": True, "response": {"found": True, "content": content}}

	def test_a_first_read_returns_the_whole_file(self):
		out = _run(self.args, self._dispatch(BIG))
		self.assertEqual(out["content"], BIG)
		self.assertNotIn("unchanged_since_earlier_read", out)

	def test_a_second_identical_read_returns_a_pointer_to_the_first(self):
		_earlier_read("i-test", PATH, BIG)
		out = _run(self.args, self._dispatch(BIG))
		self.assertTrue(out["unchanged_since_earlier_read"])
		self.assertIn("Unchanged since you read it earlier", out["content"])
		self.assertIn(str(len(BIG)), out["content"], "the agent is told how big the file it already has is")
		self.assertLess(len(out["content"]), 400, "the pointer must not itself be a payload")

	def test_a_file_that_changed_comes_back_in_full(self):
		_earlier_read("i-test", PATH, BIG)
		edited = BIG.replace("<template>", "<template>\n<!-- edited -->")
		out = _run(self.args, self._dispatch(edited))
		self.assertEqual(out["content"], edited)
		self.assertNotIn("unchanged_since_earlier_read", out)

	def test_another_runs_read_of_the_same_path_is_not_mine(self):
		_earlier_read("i-someone-else", PATH, BIG)
		out = _run(self.args, self._dispatch(BIG))
		self.assertEqual(out["content"], BIG)

	def test_a_read_of_a_different_path_does_not_match(self):
		_earlier_read("i-test", "spiff/src/views/Editor.vue", BIG)
		out = _run(self.args, self._dispatch(BIG))
		self.assertEqual(out["content"], BIG)

	def test_this_calls_own_row_is_not_mistaken_for_an_earlier_read(self):
		"""sandbox_dispatch writes a row for this call too. Matching against it
		would elide the very first read of a file and hand the agent a pointer to
		a read it never did, so only rows written before the call count."""
		def dispatch_writing_its_own_row(*args, **kwargs):
			_earlier_read("i-test", PATH, BIG)  # what sandbox_dispatch does itself
			return {"ok": True, "response": {"found": True, "content": BIG}}

		body = frappe.db.get_value("Server Script", SCRIPT, "script")
		result = {}
		with patch(
			"one_bpmn.one_bpmn.connectors.agent_sandbox_ops.sandbox_dispatch",
			side_effect=dispatch_writing_its_own_row,
		):
			exec(body, {"frappe": frappe, "__builtins__": __builtins__}, {
				"frappe": frappe, "result": result, "task_data": dict(self.args),
				"context_docname": None, "bpmn_id": "read_file",
				"instance": frappe._dict(name="i-test"),
			})
		self.assertEqual(result["content"], BIG, "the row this call created must never match")

	def test_a_failed_dispatch_still_reports_its_error(self):
		out = _run(self.args, {"ok": False, "error": "the sandbox rejected the call"})
		self.assertEqual(out["error"], "the sandbox rejected the call")
		self.assertNotIn("content", out)
