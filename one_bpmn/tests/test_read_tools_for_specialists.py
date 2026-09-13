# Copyright (c) 2026, one-fm and contributors
"""read_work_item and read_pull_request: the specialist reads the record itself,
as its own identity, and a missing permission is refused by name."""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import identity
from one_bpmn.one_bpmn.patches.v1_0 import grant_specialists_work_item_read as roles_patch
from one_bpmn.tests.test_agent_identity import _work_item, make_agent_configuration


def _run(script_name, *, context_doctype, context_docname, args=None, instance=None):
	"""Execute the tool body the way the engine does, so the real script is tested."""
	body = frappe.db.get_value("Server Script", script_name, "script")
	result = {}
	local_vars = {
		"frappe": frappe,
		"context_doctype": context_doctype,
		"context_docname": context_docname,
		"result": result,
		"task_data": dict(args or {}),
		"shape_config": {},
		"bpmn_id": "test",
		"instance": instance or frappe._dict(),
		"doc": frappe.get_doc(context_doctype, context_docname) if context_docname else None,
	}
	exec(body, {"frappe": frappe, "__builtins__": __builtins__}, local_vars)
	return result


def _a2a_task(agent_configuration, work_item=None, pull_request=None):
	payload = {"instruction": "Fix it."}
	if work_item:
		payload["work_item"] = work_item
	if pull_request:
		payload["pull_request"] = pull_request
	task = frappe.get_doc({
		"doctype": "A2A Task", "direction": "Internal", "state": "working",
		"agent_configuration": agent_configuration, "principal": "Administrator",
		"request_payload": json.dumps(payload),
	})
	task.flags.ignore_links = True
	# Inserting an A2A Task starts the specialist's map, which under the test
	# runner runs inline — a real model, real sandbox pushes. The fixture is a
	# record to read, not a delegation to run.
	with patch("one_bpmn.one_bpmn.trigger.on_doc_event"):
		task.insert(ignore_permissions=True)
	return task.name


class TestReadWorkItem(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("AI Agent Configuration", "Frontend Agent"):
			self.skipTest("Frontend Agent is not on this site")
		roles_patch.execute()
		self.item = _work_item()

	def test_a_specialist_with_the_role_reads_its_own_work_item_from_the_payload(self):
		task = _a2a_task("Frontend Agent", work_item=self.item)
		out = _run("Work Item Tool: Read Work Item", context_doctype="A2A Task", context_docname=task)
		self.assertNotIn("error", out, out.get("error"))
		self.assertEqual(out["work_item"], self.item)
		for key in ("title", "description", "state", "reporter", "pull_request", "comments"):
			self.assertIn(key, out)

	def test_an_agent_without_read_permission_is_refused_by_name(self):
		cfg = make_agent_configuration()  # no agent_roles
		identity.ensure_agent_user(cfg)
		task = _a2a_task(cfg.name, work_item=self.item)
		out = _run("Work Item Tool: Read Work Item", context_doctype="A2A Task", context_docname=task)
		self.assertIn("error", out)
		self.assertIn(cfg.name, out["error"])
		self.assertIn("no roles at all", out["error"])
		self.assertIn("do not retry", out["error"])

	def test_an_explicit_work_item_argument_wins_and_a_missing_one_is_reported(self):
		task = _a2a_task("Frontend Agent")
		out = _run("Work Item Tool: Read Work Item", context_doctype="A2A Task", context_docname=task, args={"work_item": self.item})
		self.assertEqual(out.get("work_item"), self.item)
		out = _run("Work Item Tool: Read Work Item", context_doctype="A2A Task", context_docname=task)
		self.assertIn("No work item to read", out["error"])
		out = _run("Work Item Tool: Read Work Item", context_doctype="A2A Task", context_docname=task, args={"work_item": "WI-000000"})
		self.assertIn("No Work Item named", out["error"])

	def test_on_a_work_item_context_it_reads_that_work_item(self):
		out = _run("Work Item Tool: Read Work Item", context_doctype="Work Item", context_docname=self.item,
		           instance=frappe._dict(process_model="Orchestrator Agent"))
		self.assertEqual(out.get("work_item"), self.item)


class TestReadPullRequest(FrappeTestCase):
	def setUp(self):
		self.item = _work_item()

	def test_a_non_github_url_is_refused_before_any_request(self):
		with patch("frappe.integrations.utils.make_get_request") as get:
			out = _run("GitHub Tool: Read Pull Request", context_doctype="Work Item", context_docname=self.item, args={"pr_url": "https://example.com/x"})
		self.assertIn("not a GitHub pull request URL", out["error"])
		get.assert_not_called()

	def test_no_url_anywhere_is_reported(self):
		out = _run("GitHub Tool: Read Pull Request", context_doctype="Work Item", context_docname=self.item)
		self.assertIn("No pull request to read", out["error"])

	def test_the_five_calls_are_folded_into_one_answer_with_changes_requested_first(self):
		def fake_get(url, headers=None, **kw):
			if url.endswith("/pulls/9"):
				return {"title": "Fix titles", "body": "Work Item: WI-1", "state": "open", "merged": False,
				        "head": {"ref": "WI-1"}, "base": {"ref": "staging"}, "user": {"login": "bot"}}
			if url.endswith("/files?per_page=100"):
				return [{"filename": "a.py", "status": "modified", "additions": 2, "deletions": 2, "patch": "@@ -1 +1 @@\n-x\n+y"}]
			if "/pulls/9/reviews" in url:
				return [{"user": {"login": "rev"}, "state": "CHANGES_REQUESTED", "body": "Keep the docstring scope."},
				        {"user": {"login": "rev"}, "state": "COMMENTED", "body": ""}]
			if "/pulls/9/comments" in url:
				return [{"path": "a.py", "line": 3, "user": {"login": "rev"}, "body": "rename this"}]
			if "/issues/9/comments" in url:
				return [{"user": {"login": "someone"}, "body": "thanks"}]
			raise AssertionError(url)
		with patch("frappe.integrations.utils.make_get_request", side_effect=fake_get):
			out = _run("GitHub Tool: Read Pull Request", context_doctype="Work Item", context_docname=self.item,
			           args={"pr_url": "https://github.com/ONE-F-M/one_bpmn/pull/9"})
		self.assertNotIn("error", out, out.get("error"))
		self.assertEqual(out["number"], 9)
		self.assertEqual(out["files"][0]["path"], "a.py")
		self.assertEqual([r["state"] for r in out["reviews"]], ["CHANGES_REQUESTED"])  # empty COMMENTED dropped
		self.assertEqual(out["changes_requested"][0]["body"], "Keep the docstring scope.")
		self.assertEqual(out["review_comments"][0]["body"], "rename this")
		self.assertIn("1 review(s) asked for changes", out["summary"])

	def test_the_url_defaults_to_the_delegations_pull_request(self):
		if not frappe.db.exists("AI Agent Configuration", "Frontend Agent"):
			self.skipTest("Frontend Agent is not on this site")
		task = _a2a_task("Frontend Agent", work_item=self.item, pull_request="https://github.com/o/r/pull/3")
		with patch("frappe.integrations.utils.make_get_request", side_effect=Exception("offline")):
			out = _run("GitHub Tool: Read Pull Request", context_doctype="A2A Task", context_docname=task)
		self.assertIn("https://github.com/o/r/pull/3", out["error"])
