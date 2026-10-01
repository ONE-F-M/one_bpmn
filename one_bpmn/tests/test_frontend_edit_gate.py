# Copyright (c) 2026, one-fm and contributors
"""The Frontend Agent may not change a file before loading frontend-house-style
(for .vue and .js) and reading that file (for edit_file)."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops

VUE = "one_bpmn/spiff/src/views/Home.vue"
FRONTEND = frappe._dict(name="inst-1", process_model="Frontend Agent")


def _rows(*calls):
	return [frappe._dict(request_payload=frappe.as_json({"action": a, "args": {"path": p}})) for a, p in calls]


class TestFrontendEditError(FrappeTestCase):
	def _gate(self, action="edit_file", path=VUE, instance=FRONTEND, skill=True, read=True, over_budget=False):
		with patch.object(ops, "_skill_loaded", return_value=skill), patch.object(
			ops, "_has_read", return_value=read
		), patch.object(ops, "read_budget_exceeded", return_value="spent" if over_budget else None):
			return ops.frontend_edit_error(instance, action, path)

	def test_vue_edit_without_the_skill_is_refused(self):
		self.assertIn("load_skill frontend-house-style", self._gate(skill=False))

	def test_write_file_of_a_js_file_without_the_skill_is_refused(self):
		self.assertIn("load_skill", self._gate(action="write_file", path="frappe_agile/public/js/todo.js", skill=False))

	def test_edit_of_an_unread_file_is_refused(self):
		self.assertIn("read_file on " + VUE, self._gate(read=False))

	def test_write_file_needs_no_prior_read(self):
		self.assertIsNone(self._gate(action="write_file", read=False))

	def test_python_file_needs_no_skill(self):
		self.assertIsNone(self._gate(path="one_bpmn/api/insights_api.py", skill=False))

	def test_past_the_read_budget_an_unread_edit_is_allowed(self):
		self.assertIsNone(self._gate(read=False, over_budget=True))

	def test_other_agents_and_read_actions_are_untouched(self):
		self.assertIsNone(self._gate(instance=frappe._dict(name="i", process_model="Dev Agent"), skill=False, read=False))
		self.assertIsNone(self._gate(action="read_file", skill=False, read=False))
		self.assertIsNone(self._gate(instance=None, skill=False, read=False))


class TestHasRead(FrappeTestCase):
	def _has_read(self, path, *calls):
		with patch.object(frappe, "get_all", return_value=_rows(*calls)):
			return ops._has_read(FRONTEND, path)

	def test_a_read_of_the_same_file_under_either_path_form_counts(self):
		self.assertTrue(self._has_read(VUE, ("read_file", "spiff/src/views/Home.vue")))
		self.assertTrue(self._has_read("spiff/src/views/Home.vue", ("read_file", VUE)))

	def test_a_file_this_run_wrote_counts_as_read(self):
		self.assertTrue(self._has_read(VUE, ("write_file", VUE)))

	def test_a_different_file_or_a_listing_does_not_count(self):
		self.assertFalse(self._has_read(VUE, ("read_file", "spiff/src/views/Runs.vue"), ("list_files", VUE)))


class TestSandboxDispatchRefuses(FrappeTestCase):
	def test_a_refused_edit_never_reaches_the_sandbox(self):
		with patch.object(ops, "_skill_loaded", return_value=True), patch.object(
			ops, "_has_read", return_value=False
		), patch.object(ops, "read_budget_exceeded", return_value=None), patch("requests.post") as post:
			result = ops.sandbox_dispatch(
				"edit_file", "one_bpmn", "staging", "Reword the heading.",
				{"path": VUE, "old_string": "Processes", "new_string": "Your Processes"}, instance=FRONTEND,
			)
		self.assertFalse(result["ok"])
		self.assertIn("read_file on " + VUE, result["error"])
		post.assert_not_called()
