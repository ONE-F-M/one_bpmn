# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The agent_sandbox connector's operations: sandbox_dispatch (the fast,
synchronous file-op primitive) and run_tests/open_pull_request (the two
parked, minutes-scale operations).

Mirrors test_a2a_local.py's TestLocalDelegationParking shape for the parked
operations: a fake task/instance (SimpleNamespace), the external call mocked
out, and assertions on what got parked and what row tracks it. Neither
operation forwards a model credential or a tool list — all the reasoning
happens once, in Processa's own AI Agent Task; the sandbox only ever
receives the concrete action and its arguments.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops

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


def _any_process_model() -> str:
	existing = frappe.db.get_value("BPMN Process Model", {"name": ["is", "set"]}, "name")
	if existing:
		return existing
	process = frappe.get_doc({
		"doctype": "Process", "process_name": f"_sbx-{frappe.generate_hash(length=6)}",
	}).insert(ignore_permissions=True)
	return frappe.get_doc({
		"doctype": "BPMN Process Model",
		"title": f"_sbx-model-{frappe.generate_hash(length=6)}",
		"process_id": f"_sbx-{frappe.generate_hash(length=6)}",
		"version": 1,
		"process_name": process.name,
		"bpmn_xml": "<bpmn:definitions/>",
	}).insert(ignore_permissions=True).name


class AgentSandboxCase(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# caller_instance is a real Link field (-> BPMN Process Instance) and
		# _dispatch_single_action's own run.insert() never sets ignore_links —
		# production always passes a genuine, already-saved instance, so the
		# test fixture needs one too rather than a bare SimpleNamespace stand-in.
		# Any process model resolves the Link; this suite never runs a diagram.
		# Deliberately NOT the "Dev Agent" map — maps ship by export/import, so
		# naming one makes the whole suite pass or fail on whether somebody has
		# imported it. Every test here errored in setUp on a bench that had not.
		self._test_instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_model": _any_process_model(),
		}).insert(ignore_permissions=True)

	def ctx(self, operation=None):
		task = SimpleNamespace(
			id="00000000-0000-0000-0000-000000000da1",
			data={},
			task_spec=SimpleNamespace(bpmn_id="ServiceTask_DevAgent", name="ServiceTask_DevAgent"),
		)
		instance = SimpleNamespace(name=self._test_instance.name, initiated_by="Administrator")
		c = {"instance": instance, "task": task}
		if operation is not None:
			c["operation"] = operation
		return c

	def tearDown(self):
		for name in frappe.get_all(
			"Agent Sandbox Run", filters={"target_app": "one_bpmn"}, pluck="name"
		):
			frappe.delete_doc("Agent Sandbox Run", name, force=True, ignore_permissions=True, ignore_missing=True)
		frappe.delete_doc(
			"BPMN Process Instance", self._test_instance.name,
			force=True, ignore_permissions=True, ignore_missing=True,
		)
		super().tearDown()


class TestCallbackUrl(FrappeTestCase):
	"""_callback_url forces https regardless of what get_url() constructs.

	Confirmed live: a real production dispatch was rejected with a 422 by
	the sandbox's own _validate_payload (dev_agent_server.py), which hard-
	requires callback_url to be https — get_url() had produced an http://
	URL because this runs inside a background job (no live request for it
	to read a scheme from), and the site's host_name wasn't set to correct
	that fallback. The site itself was genuinely served over https
	externally the whole time; only Frappe's own internal guess was wrong."""

	def test_forces_https_when_get_url_returns_http(self):
		with patch.object(
			ops.frappe.utils, "get_url",
			return_value="http://example.com/api/method/one_bpmn.api.agent_callback.report_result",
		):
			self.assertEqual(
				ops._callback_url(),
				"https://example.com/api/method/one_bpmn.api.agent_callback.report_result",
			)

	def test_leaves_https_untouched(self):
		with patch.object(
			ops.frappe.utils, "get_url",
			return_value="https://example.com/api/method/one_bpmn.api.agent_callback.report_result",
		):
			self.assertEqual(
				ops._callback_url(),
				"https://example.com/api/method/one_bpmn.api.agent_callback.report_result",
			)


class TestSlowActionDispatch(AgentSandboxCase):
	"""run_tests and open_pull_request — the two sandbox tools slow enough
	(they may re-run the real test suite) to need a park/track shape. Both
	are named Connector Operations sharing one handler, dispatch_action,
	which reads which operation it was configured as off ctx["operation"]
	(set by dispatch_connector) rather than being told apart by function
	identity. Neither forwards a tool list or a model credential; the
	sandbox itself never calls an LLM for either of them."""

	def _dispatch(self, operation, response_status=202, **param_overrides):
		mock_settings = SimpleNamespace(
			agent_sandbox_url="https://sandbox.example.run.app",
			get_password=lambda *a, **k: "fake-github-token",
		)
		mock_response = MagicMock(status_code=response_status)
		mock_response.raise_for_status = MagicMock()
		params = {
			"target_app": "one_bpmn", "git_branch": "staging", "work_item_description": "Fix the thing.",
			**param_overrides,
		}
		with patch.object(frappe, "get_cached_doc", side_effect=_scoped_get_cached_doc(mock_settings)), patch.object(
			ops, "_mint_identity_token", return_value="fake-token"
		), patch("requests.post", return_value=mock_response) as mock_post:
			ctx = self.ctx(operation=operation)
			result = ops.dispatch_action(params, ctx)
		return result, ctx, mock_post

	def test_run_tests_parks_and_tracks(self):
		result, ctx, mock_post = self._dispatch("run_tests")
		self.assertIsNone(result)
		marker = ctx["task"].data[ops.AGENT_SANDBOX_WAITING_KEY]
		row = frappe.get_doc("Agent Sandbox Run", marker["run"])
		self.assertEqual(row.state, "running")
		_args, kwargs = mock_post.call_args
		self.assertEqual(kwargs["json"]["action"], "run_tests")
		self.assertEqual(kwargs["json"]["target_app"], "one_bpmn")
		self.assertNotIn("agent_config", kwargs["json"])
		self.assertNotIn("tools", kwargs["json"])

	def test_open_pull_request_parks_and_forwards_summary_as_an_arg(self):
		result, ctx, mock_post = self._dispatch("open_pull_request", summary="Added the docstring.")
		self.assertIsNone(result)
		marker = ctx["task"].data[ops.AGENT_SANDBOX_WAITING_KEY]
		self.assertIn("run", marker)
		_args, kwargs = mock_post.call_args
		self.assertEqual(kwargs["json"]["action"], "open_pull_request")
		self.assertEqual(kwargs["json"]["args"], {"summary": "Added the docstring."})

	def test_missing_operation_is_refused(self):
		"""dispatch_action must not silently no-op or crash oddly when it was
		somehow invoked outside a configured connector operation."""
		with self.assertRaises(ops.AgentSandboxError):
			ops.dispatch_action(
				{"target_app": "one_bpmn", "git_branch": "staging", "work_item_description": "x"},
				self.ctx(),
			)

	def test_missing_target_app_is_refused_before_anything_is_created(self):
		before = frappe.db.count("Agent Sandbox Run", {"target_app": "one_bpmn"})
		with self.assertRaises(ops.AgentSandboxError):
			ops.dispatch_action(
				{"target_app": "", "git_branch": "staging", "work_item_description": "x"},
				self.ctx(operation="run_tests"),
			)
		self.assertEqual(frappe.db.count("Agent Sandbox Run", {"target_app": "one_bpmn"}), before)

	def test_a_rejected_dispatch_marks_the_row_failed_and_raises(self):
		mock_settings = SimpleNamespace(
			agent_sandbox_url="https://sandbox.example.run.app",
			get_password=lambda *a, **k: "fake-github-token",
		)
		with patch.object(frappe, "get_cached_doc", side_effect=_scoped_get_cached_doc(mock_settings)), patch.object(
			ops, "_mint_identity_token", return_value="fake-token"
		), patch("requests.post", side_effect=ConnectionError("no route to host")):
			with self.assertRaises(ops.AgentSandboxError):
				ops.dispatch_action(
					{"target_app": "one_bpmn", "git_branch": "staging", "work_item_description": "x"},
					self.ctx(operation="run_tests"),
				)
		row = frappe.get_doc(
			"Agent Sandbox Run", frappe.get_all("Agent Sandbox Run", filters={"target_app": "one_bpmn"}, pluck="name")[-1]
		)
		self.assertEqual(row.state, "failed")


class TestSandboxDispatch(FrappeTestCase):
	"""sandbox_dispatch — the bare HTTP primitive the 4 Sandbox Tool Server
	Scripts call directly (see one_bpmn/one_bpmn/frontend/primitives.py's
	own docstring for why it's this thin: a Server Script cannot import
	requests itself — security/script_validator.py's FORBIDDEN_MODULES —
	so this exists only to place the one call; all tool policy (which
	arguments are required, how to word an error) lives in the Server
	Script itself, not here). Never raises, by design."""

	def _call(self, response_status=200, response_json=None, post_side_effect=None, **overrides):
		mock_settings = SimpleNamespace(
			agent_sandbox_url=overrides.pop("agent_sandbox_url", "https://sandbox.example.run.app"),
			get_password=overrides.pop("get_password", lambda *a, **k: "fake-github-token"),
		)
		mock_response = MagicMock(status_code=response_status)
		mock_response.raise_for_status = MagicMock()
		mock_response.json = MagicMock(return_value=response_json or {"found": True, "content": "hi"})

		post_kwargs = {"side_effect": post_side_effect} if post_side_effect else {"return_value": mock_response}
		with patch.object(frappe, "get_cached_doc", side_effect=_scoped_get_cached_doc(mock_settings)), patch.object(
			ops, "_mint_identity_token", overrides.pop("mint_identity_token", MagicMock(return_value="fake-token"))
		), patch("requests.post", **post_kwargs) as mock_post:
			result = ops.sandbox_dispatch("read_file", "one_bpmn", "staging", "Fix the thing.", {"path": "a.py"})
		return result, mock_post

	def test_successful_call_wraps_the_sandboxs_response(self):
		result, mock_post = self._call(response_json={"found": True, "content": "hello"})
		self.assertEqual(result, {"ok": True, "response": {"found": True, "content": "hello"}})
		_args, kwargs = mock_post.call_args
		self.assertEqual(kwargs["json"]["action"], "read_file")
		self.assertEqual(kwargs["json"]["args"], {"path": "a.py"})
		self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake-token")

	def test_missing_sandbox_url_never_raises(self):
		result, mock_post = self._call(agent_sandbox_url="")
		self.assertEqual(result, {"ok": False, "error": "Processa Settings has no Sandbox URL configured."})
		mock_post.assert_not_called()

	def test_missing_github_token_never_raises(self):
		result, mock_post = self._call(get_password=lambda *a, **k: "")
		self.assertFalse(result["ok"])
		self.assertIn("GitHub token", result["error"])
		mock_post.assert_not_called()

	def test_auth_failure_never_raises(self):
		result, mock_post = self._call(mint_identity_token=MagicMock(side_effect=RuntimeError("bad key")))
		self.assertFalse(result["ok"])
		self.assertIn("authenticate", result["error"])
		mock_post.assert_not_called()

	def test_network_failure_never_raises(self):
		result, _mock_post = self._call(post_side_effect=ConnectionError("no route to host"))
		self.assertFalse(result["ok"])
		self.assertIn("no route to host", result["error"])
