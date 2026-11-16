# Copyright (c) 2026, one-fm and contributors
"""upload_videos on the Processa side: the operation record, where the machine user's token comes from, and how a result settles."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from processa.api import agent_callback as callback
from processa.agents_sandbox.sandbox import ops
from processa.patches.v1_0 import add_agent_sandbox_upload_videos_operation as videos_patch
from processa.agents_sandbox.tests.test_agent_sandbox_ops import AgentSandboxCase, _scoped_get_cached_doc

OPERATION = "BPMN Connector Operation"
TOKEN = "ghp_" + "y" * 36  # built at run time: not a real credential, and no credential-shaped literal in the file
CALLER = "caller-" + "z" * 20


class TestOperationRecord(IntegrationTestCase):
	def setUp(self):
		if not frappe.db.exists("BPMN Connector", "agent_sandbox"):
			self.skipTest("no agent_sandbox connector on this site")
		if name := frappe.db.get_value(OPERATION, {"connector": "agent_sandbox", "operation_id": "upload_videos"}, "name"):
			frappe.delete_doc(OPERATION, name, force=True, ignore_permissions=True)

	def test_it_is_created_once_as_a_slow_dispatch_operation_and_takes_no_token(self):
		videos_patch.execute()
		videos_patch.execute()
		rows = frappe.get_all(OPERATION, filters={"connector": "agent_sandbox", "operation_id": "upload_videos"}, pluck="name")
		self.assertEqual(len(rows), 1)
		doc = frappe.get_doc(OPERATION, rows[0])
		self.assertEqual((doc.execution_type, doc.handler_path, doc.enabled), ("Python Handler", videos_patch.HANDLER, 1))
		fields = [r.field_name for r in doc.fields]
		self.assertEqual(fields, ["target_app", "git_branch", "work_item_description", "run_id", "repository", "pr_number", "comment_body"])
		self.assertNotIn("token", fields)  # the token is read from the connector at dispatch, never a map input


class TestTokenFromTheConnector(AgentSandboxCase):
	PARAMS = {"target_app": "processa", "git_branch": "staging", "work_item_description": "Test it.", "run_id": "run-1",
	          "repository": "ONE-F-M/one_bpmn", "pr_number": "5"}

	def _connector(self, **over):
		if frappe.db.exists("BPMN Connector", ops.UPLOAD_CONNECTOR):
			frappe.delete_doc("BPMN Connector", ops.UPLOAD_CONNECTOR, force=True, ignore_permissions=True)
		values = {"doctype": "BPMN Connector", "connector_id": ops.UPLOAD_CONNECTOR, "label": "GitHub video upload", "enabled": 1,
		          "base_url": "https://api.github.com", "auth_type": "Bearer Token", "auth_secret": TOKEN, **over}
		frappe.get_doc(values).insert(ignore_permissions=True)

	def _dispatch(self, **over):
		settings = SimpleNamespace(agent_sandbox_url="https://sandbox.example.run.app", get_password=lambda *a, **k: "fake-github-token")
		response = MagicMock(status_code=202)
		response.raise_for_status = MagicMock()
		with patch.object(frappe, "get_cached_doc", side_effect=_scoped_get_cached_doc(settings)), \
				patch.object(ops, "mint_identity_token", return_value="t"), patch("requests.post", return_value=response) as post:
			ctx = self.ctx(operation="upload_videos")
			result = ops.dispatch_action({**self.PARAMS, **over}, ctx)
		return result, ctx, post

	def test_the_connectors_token_goes_to_the_sandbox_replaces_a_caller_value_and_is_never_stored(self):
		self._connector()
		_result, ctx, post = self._dispatch(token=CALLER)
		sent = post.call_args.kwargs["json"]["args"]
		self.assertEqual(sent["token"], TOKEN)
		self.assertEqual({k: v for k, v in sent.items() if k != "token"}, {"run_id": "run-1", "repository": "ONE-F-M/one_bpmn", "pr_number": "5"})
		row = frappe.get_doc("Agent Sandbox Run", ctx["task"].data[ops.AGENT_SANDBOX_WAITING_KEY]["run"])
		self.assertNotIn(TOKEN, row.request_payload)
		self.assertNotIn(CALLER, row.request_payload)
		self.assertEqual(frappe.parse_json(row.request_payload)["args"]["token"], "REDACTED")

	def test_a_missing_disabled_wrong_type_or_empty_connector_is_refused_before_any_run_is_created(self):
		before = frappe.db.count("Agent Sandbox Run")
		if frappe.db.exists("BPMN Connector", ops.UPLOAD_CONNECTOR):
			frappe.delete_doc("BPMN Connector", ops.UPLOAD_CONNECTOR, force=True, ignore_permissions=True)
		with self.assertRaisesRegex(ops.AgentSandboxError, "github_video_upload"):
			self._dispatch()
		for over in ({"enabled": 0}, {"auth_type": "Basic"}, {"auth_secret": ""}):
			self._connector(**over)
			with self.assertRaises(ops.AgentSandboxError, msg=over):
				self._dispatch()
		self.assertEqual(frappe.db.count("Agent Sandbox Run"), before)

	def test_the_run_repository_and_pull_request_are_required(self):
		self._connector()
		for missing in ("run_id", "repository", "pr_number"):
			with self.assertRaisesRegex(ops.AgentSandboxError, missing):
				self._dispatch(**{missing: ""})

	def test_an_upload_run_is_never_retried_from_the_stored_payload(self):
		with patch.object(ops.supervisor, "next_step", return_value={"action": "retry"}):
			self.assertFalse(ops.retry_eligible(SimpleNamespace(action="upload_videos", failure_class="env")))


class TestSettlingUploads(UnitTestCase):
	def _run(self, state="completed", result=None, error=""):
		return SimpleNamespace(state=state, retry_of=None, error_message=error, request_payload='{"action": "upload_videos"}', result=json.dumps(result or {}))

	def test_a_finished_upload_completes_and_anything_else_fails(self):
		self.assertEqual(callback._settled_fields("upload_videos", "videos_uploaded", "", {}), {"state": "completed"})
		failed = callback._settled_fields("upload_videos", "failed", "", {"error": "1 of 2 videos did not upload"})
		self.assertEqual((failed["state"], failed["error_message"]), ("failed", "1 of 2 videos did not upload"))

	def test_the_agent_reads_one_link_per_criterion_or_what_failed_for_which(self):
		done = self._run(result={"status": "videos_uploaded", "path": "upload_endpoint", "uploads": [{"criterion": "AC1", "url": "https://github.com/user-attachments/assets/1"}]})
		text = callback._sandbox_run_answer(done)
		self.assertIn("AC1 | https://github.com/user-attachments/assets/1", text)
		failed = self._run("failed", {"step": "upload", "uploads": [{"criterion": "AC1", "url": "https://github.com/user-attachments/assets/1"}],
		                              "errors": [{"criterion": "AC2", "error": "video is 101 MB, over the 100 MB limit"}]}, "1 of 2 videos did not upload")
		text = callback._sandbox_run_answer(failed)
		self.assertIn("failed at step upload", text)
		self.assertIn("AC2 | video is 101 MB", text)
		self.assertIn("AC1 | https://github.com/user-attachments/assets/1", text)

	def test_the_agent_is_told_when_the_fallback_path_posted_the_comment(self):
		text = callback._sandbox_run_answer(self._run(result={"path": "gh_pr_comment", "comment_url": "https://github.com/ONE-F-M/one_bpmn/pull/5#issuecomment-9"}))
		self.assertIn("refused the token", text)
		self.assertIn("issuecomment-9", text)
