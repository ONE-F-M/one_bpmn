# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The dev_agent_sandbox connector's dispatch operation.

Mirrors test_a2a_local.py's TestLocalDelegationParking shape: a fake
task/instance (SimpleNamespace), the external call mocked out, and
assertions on what got parked and what row tracks it. _resolve_agent_config
and _mint_identity_token are mocked directly rather than depending on a real
"Dev Agent" AI Agent Configuration or real GCP credentials existing in the
test environment — this suite is about the connector's own dispatch/parking
contract, not the agent seed or Google auth.

agent_config's shape here (system_prompt/model/api_key) and the separate
github_token resolved from Processa Settings both reflect dispatch()'s
current contract — the sandbox is the coding agent and opens the PR itself,
so both a model credential and a GitHub token now travel in every dispatch.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import dev_agent_sandbox_ops as ops

# Captured before any test patches frappe.get_cached_doc, so the scoped
# side_effect below can still delegate real (non-"Processa Settings") calls
# to the genuine implementation — patching it with a bare return_value=...
# instead intercepts every doctype, including Frappe's own internal
# System Settings lookups deep in Meta/get_system_timezone, and breaks in
# ways that have nothing to do with what these tests are actually checking.
_real_get_cached_doc = frappe.get_cached_doc


def _scoped_get_cached_doc(mock_settings):
	def _fake(doctype, *args, **kwargs):
		if doctype == "Processa Settings":
			return mock_settings
		return _real_get_cached_doc(doctype, *args, **kwargs)

	return _fake


class DevAgentSandboxCase(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# caller_instance is a real Link field (-> BPMN Process Instance) and
		# dispatch()'s own run.insert() never sets ignore_links — production
		# always passes a genuine, already-saved instance, so the test fixture
		# needs one too rather than a bare SimpleNamespace stand-in.
		self._test_instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_model": "Dev Agent",
		}).insert(ignore_permissions=True)

	def ctx(self):
		task = SimpleNamespace(
			id="00000000-0000-0000-0000-000000000da1",
			data={},
			task_spec=SimpleNamespace(bpmn_id="ServiceTask_DevAgent", name="ServiceTask_DevAgent"),
		)
		instance = SimpleNamespace(name=self._test_instance.name, initiated_by="Administrator")
		return {"instance": instance, "task": task}

	def params(self, **kwargs):
		merged = {
			"target_app": "one_bpmn",
			"git_branch": "staging",
			"work_item_description": "Fix the thing.",
		}
		merged.update(kwargs)
		return merged

	def tearDown(self):
		for name in frappe.get_all(
			"Dev Agent Sandbox Run", filters={"target_app": "one_bpmn"}, pluck="name"
		):
			frappe.delete_doc("Dev Agent Sandbox Run", name, force=True, ignore_permissions=True, ignore_missing=True)
		frappe.delete_doc(
			"BPMN Process Instance", self._test_instance.name,
			force=True, ignore_permissions=True, ignore_missing=True,
		)
		super().tearDown()


class TestDispatchValidation(DevAgentSandboxCase):
	def test_missing_target_app_is_refused_before_anything_is_created(self):
		with self.assertRaises(ops.DevAgentSandboxError):
			ops.dispatch(self.params(target_app=""), self.ctx())
		self.assertEqual(
			frappe.db.count("Dev Agent Sandbox Run", {"target_app": "one_bpmn"}), 0,
			"a rejected dispatch must not leave a row behind",
		)

	def test_missing_sandbox_url_is_refused(self):
		mock_settings = SimpleNamespace(dev_agent_sandbox_url="", get_password=lambda *a, **k: "")
		with patch.object(frappe, "get_cached_doc", side_effect=_scoped_get_cached_doc(mock_settings)):
			with self.assertRaises(ops.DevAgentSandboxError):
				ops.dispatch(self.params(), self.ctx())

	def test_missing_github_token_is_refused_and_marks_the_row_failed(self):
		"""Checked after agent_config resolves but before the sandbox is ever
		called — a dispatch that can't deliver a PR must not run at all."""
		mock_settings = SimpleNamespace(
			dev_agent_sandbox_url="https://sandbox.example.run.app",
			get_password=lambda *a, **k: "",
		)
		with patch.object(frappe, "get_cached_doc", side_effect=_scoped_get_cached_doc(mock_settings)), patch.object(
			ops, "_resolve_agent_config",
			return_value={"system_prompt": "test", "model": "claude-haiku-4-5-20251001", "api_key": "fake-key"},
		):
			with self.assertRaises(ops.DevAgentSandboxError):
				ops.dispatch(self.params(), self.ctx())

		row = frappe.get_doc(
			"Dev Agent Sandbox Run", frappe.get_all("Dev Agent Sandbox Run", pluck="name")[0]
		)
		self.assertEqual(row.state, "failed")


class TestDispatchParking(DevAgentSandboxCase):
	def _dispatch(self, response_status=202):
		mock_settings = SimpleNamespace(
			dev_agent_sandbox_url="https://sandbox.example.run.app",
			get_password=lambda *a, **k: "fake-github-token",
		)
		mock_response = MagicMock(status_code=response_status)
		mock_response.raise_for_status = MagicMock()

		with patch.object(frappe, "get_cached_doc", side_effect=_scoped_get_cached_doc(mock_settings)), patch.object(
			ops, "_resolve_agent_config",
			return_value={"system_prompt": "test", "model": "claude-haiku-4-5-20251001", "api_key": "fake-key"},
		), patch.object(ops, "_mint_identity_token", return_value="fake-token"), patch(
			"requests.post", return_value=mock_response
		) as mock_post:
			ctx = self.ctx()
			result = ops.dispatch(self.params(), ctx)
		return result, ctx, mock_post

	def test_a_dispatch_always_parks_never_answers_inline(self):
		"""A sandbox run takes minutes — there is no fast path that answers
		inside the call the way a quick HTTP connector might."""
		result, ctx, _ = self._dispatch()
		self.assertIsNone(result)
		marker = ctx["task"].data[ops.DEV_AGENT_SANDBOX_WAITING_KEY]
		self.assertIn("run", marker)

	def test_the_tracking_row_is_created_and_marked_running(self):
		_result, ctx, _ = self._dispatch()
		marker = ctx["task"].data[ops.DEV_AGENT_SANDBOX_WAITING_KEY]
		row = frappe.get_doc("Dev Agent Sandbox Run", marker["run"])
		self.assertEqual(row.state, "running")
		self.assertEqual(row.target_app, "one_bpmn")
		self.assertEqual(row.caller_wf_task_id, str(ctx["task"].id))

	def test_the_sandbox_is_called_with_a_bearer_token_not_a_static_secret(self):
		_result, _ctx, mock_post = self._dispatch()
		_args, kwargs = mock_post.call_args
		self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake-token")

	def test_the_payload_carries_agent_config_and_a_separate_github_token(self):
		"""The sandbox is the coding agent now — it needs a model, a live
		API key, and (separately) a GitHub token to open the PR itself.
		None of this is baked into the sandbox's own deployment."""
		_result, _ctx, mock_post = self._dispatch()
		_args, kwargs = mock_post.call_args
		payload = kwargs["json"]
		self.assertEqual(payload["agent_config"]["model"], "claude-haiku-4-5-20251001")
		self.assertEqual(payload["agent_config"]["api_key"], "fake-key")
		self.assertEqual(payload["github_token"], "fake-github-token")

	def test_a_rejected_dispatch_marks_the_row_failed_and_raises(self):
		mock_settings = SimpleNamespace(
			dev_agent_sandbox_url="https://sandbox.example.run.app",
			get_password=lambda *a, **k: "fake-github-token",
		)
		with patch.object(frappe, "get_cached_doc", side_effect=_scoped_get_cached_doc(mock_settings)), patch.object(
			ops, "_resolve_agent_config",
			return_value={"system_prompt": "", "model": "claude-haiku-4-5-20251001", "api_key": "fake-key"},
		), patch.object(ops, "_mint_identity_token", return_value="fake-token"), patch(
			"requests.post", side_effect=ConnectionError("no route to host"),
		):
			with self.assertRaises(ops.DevAgentSandboxError):
				ops.dispatch(self.params(), self.ctx())

		row = frappe.get_doc(
			"Dev Agent Sandbox Run", frappe.get_all("Dev Agent Sandbox Run", pluck="name")[0]
		)
		self.assertEqual(row.state, "failed")
