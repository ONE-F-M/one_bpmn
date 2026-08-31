# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The agent_sandbox connector's dispatch operation.

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
		# dispatch()'s own run.insert() never sets ignore_links — production
		# always passes a genuine, already-saved instance, so the test fixture
		# needs one too rather than a bare SimpleNamespace stand-in.
		# Any process model resolves the Link; this suite never runs a diagram.
		# Deliberately NOT the "Dev Agent" map — maps ship by export/import, so
		# naming one makes the whole suite pass or fail on whether somebody has
		# imported it. Every test here errored in setUp on a bench that had not.
		self._test_instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_model": _any_process_model(),
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
			"Agent Sandbox Run", filters={"target_app": "one_bpmn"}, pluck="name"
		):
			frappe.delete_doc("Agent Sandbox Run", name, force=True, ignore_permissions=True, ignore_missing=True)
		frappe.delete_doc(
			"BPMN Process Instance", self._test_instance.name,
			force=True, ignore_permissions=True, ignore_missing=True,
		)
		super().tearDown()


class TestDispatchValidation(AgentSandboxCase):
	def test_missing_target_app_is_refused_before_anything_is_created(self):
		with self.assertRaises(ops.AgentSandboxError):
			ops.dispatch(self.params(target_app=""), self.ctx())
		self.assertEqual(
			frappe.db.count("Agent Sandbox Run", {"target_app": "one_bpmn"}), 0,
			"a rejected dispatch must not leave a row behind",
		)

	def test_missing_sandbox_url_is_refused(self):
		mock_settings = SimpleNamespace(agent_sandbox_url="", get_password=lambda *a, **k: "")
		with patch.object(frappe, "get_cached_doc", side_effect=_scoped_get_cached_doc(mock_settings)):
			with self.assertRaises(ops.AgentSandboxError):
				ops.dispatch(self.params(), self.ctx())

	def test_missing_github_token_is_refused_and_marks_the_row_failed(self):
		"""Checked after agent_config resolves but before the sandbox is ever
		called — a dispatch that can't deliver a PR must not run at all."""
		mock_settings = SimpleNamespace(
			agent_sandbox_url="https://sandbox.example.run.app",
			get_password=lambda *a, **k: "",
		)
		with patch.object(frappe, "get_cached_doc", side_effect=_scoped_get_cached_doc(mock_settings)), patch.object(
			ops, "_resolve_agent_config",
			return_value={"system_prompt": "test", "model": "claude-haiku-4-5-20251001", "api_key": "fake-key"},
		):
			with self.assertRaises(ops.AgentSandboxError):
				ops.dispatch(self.params(), self.ctx())

		row = frappe.get_doc(
			"Agent Sandbox Run", frappe.get_all("Agent Sandbox Run", pluck="name")[0]
		)
		self.assertEqual(row.state, "failed")


class TestResolveAgentConfig(FrappeTestCase):
	"""_resolve_agent_config is mocked everywhere else in this file — these
	tests exercise the real implementation against real AI Model / AI Agent
	Configuration records instead. That gap is exactly what let a real bug
	ship undetected: the function used to read `provider.enabled` and
	`provider.get_password("api_key", ...)` off AI Provider, but AI Provider
	only ever holds a name (it's just the dialect tag) — the enable flag and
	credential actually live on AI Model. No test ever called the real
	function, so the AttributeError it raised on every dispatch went
	uncaught until a real end-to-end run hit it."""

	def setUp(self):
		super().setUp()
		self._agent_configs = []
		self._models = []

	def tearDown(self):
		for name in self._agent_configs:
			frappe.delete_doc(
				"AI Agent Configuration", name, force=True, ignore_permissions=True, ignore_missing=True
			)
		for name in self._models:
			frappe.delete_doc("AI Model", name, force=True, ignore_permissions=True, ignore_missing=True)
		super().tearDown()

	def _make_model(self, name, *, enable_model=1, api_key="sk-test-key", model_api_name=""):
		doc = frappe.get_doc({
			"doctype": "AI Model",
			"model_name": name,
			"enable_model": enable_model,
			"api_key": api_key,
			"model_api_name": model_api_name,
		}).insert(ignore_permissions=True)
		self._models.append(doc.name)
		return doc

	def _make_agent_config(self, name, *, ai_model, system_prompt="You are a test agent."):
		# Inserting an AI Agent Configuration fires "AI Agent Creation Process",
		# an active map whose prompt-writing AI step OVERWRITES system_prompt with
		# a real LLM call. on_doc_event skips on in_migrate but not on in_test, so
		# without this the fixture's prompt comes back as model output, the
		# assertion fails, and every run of this suite costs money and half a
		# minute. Suppressed the same way patches and imports already are.
		frappe.flags.in_migrate = True
		try:
			doc = frappe.get_doc({
				"doctype": "AI Agent Configuration",
				"agent_name": name,
				"agent_id": name.lower().replace(" ", "-"),
				"agent_framework": "Direct API",
				"ai_model": ai_model,
				"system_prompt": system_prompt,
			}).insert(ignore_permissions=True)
		finally:
			frappe.flags.in_migrate = False
		self._agent_configs.append(doc.name)
		return doc

	def test_resolves_a_real_enabled_model_with_a_key(self):
		model = self._make_model(
			"Test Sandbox Model - Enabled", api_key="sk-real-looking-test-key", model_api_name="claude-test-model"
		)
		self._make_agent_config("Test Dev Agent - Happy Path", ai_model=model.name, system_prompt="Be helpful.")

		with patch.object(ops, "_AGENT_CONFIG_NAME", "Test Dev Agent - Happy Path"):
			config = ops._resolve_agent_config()

		self.assertEqual(config["system_prompt"], "Be helpful.")
		self.assertEqual(config["model"], "claude-test-model")
		self.assertEqual(config["api_key"], "sk-real-looking-test-key")

	def test_falls_back_to_model_name_when_model_api_name_is_blank(self):
		model = self._make_model("Test Sandbox Model - No API Name", api_key="sk-key")
		self._make_agent_config("Test Dev Agent - No API Name", ai_model=model.name)

		with patch.object(ops, "_AGENT_CONFIG_NAME", "Test Dev Agent - No API Name"):
			config = ops._resolve_agent_config()

		self.assertEqual(config["model"], model.name)

	def test_no_ai_model_configured_raises(self):
		self._make_agent_config("Test Dev Agent - No Model", ai_model="")

		with patch.object(ops, "_AGENT_CONFIG_NAME", "Test Dev Agent - No Model"):
			with self.assertRaises(ops.AgentSandboxError):
				ops._resolve_agent_config()

	def test_disabled_model_raises(self):
		model = self._make_model("Test Sandbox Model - Disabled", enable_model=0, api_key="sk-key")
		self._make_agent_config("Test Dev Agent - Disabled Model", ai_model=model.name)

		with patch.object(ops, "_AGENT_CONFIG_NAME", "Test Dev Agent - Disabled Model"):
			with self.assertRaises(ops.AgentSandboxError):
				ops._resolve_agent_config()

	def test_model_with_no_api_key_raises(self):
		model = self._make_model("Test Sandbox Model - No Key", api_key="")
		self._make_agent_config("Test Dev Agent - No Key", ai_model=model.name)

		with patch.object(ops, "_AGENT_CONFIG_NAME", "Test Dev Agent - No Key"):
			with self.assertRaises(ops.AgentSandboxError):
				ops._resolve_agent_config()


class TestDispatchParking(AgentSandboxCase):
	def _dispatch(self, response_status=202):
		mock_settings = SimpleNamespace(
			agent_sandbox_url="https://sandbox.example.run.app",
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
		marker = ctx["task"].data[ops.AGENT_SANDBOX_WAITING_KEY]
		self.assertIn("run", marker)

	def test_the_tracking_row_is_created_and_marked_running(self):
		_result, ctx, _ = self._dispatch()
		marker = ctx["task"].data[ops.AGENT_SANDBOX_WAITING_KEY]
		row = frappe.get_doc("Agent Sandbox Run", marker["run"])
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
			agent_sandbox_url="https://sandbox.example.run.app",
			get_password=lambda *a, **k: "fake-github-token",
		)
		with patch.object(frappe, "get_cached_doc", side_effect=_scoped_get_cached_doc(mock_settings)), patch.object(
			ops, "_resolve_agent_config",
			return_value={"system_prompt": "", "model": "claude-haiku-4-5-20251001", "api_key": "fake-key"},
		), patch.object(ops, "_mint_identity_token", return_value="fake-token"), patch(
			"requests.post", side_effect=ConnectionError("no route to host"),
		):
			with self.assertRaises(ops.AgentSandboxError):
				ops.dispatch(self.params(), self.ctx())

		row = frappe.get_doc(
			"Agent Sandbox Run", frappe.get_all("Agent Sandbox Run", pluck="name")[0]
		)
		self.assertEqual(row.state, "failed")


class TestResolutionFailureIsRecorded(AgentSandboxCase):
	"""Upstream's TestResolveAgentConfig covers the resolver itself. This covers
	the HANDLER around it, which is a different failure and the one that made the
	original bug silent."""

	def setUp(self):
		super().setUp()
		self._models = []
		self._original_model = frappe.db.get_value("AI Agent Configuration", "Dev Agent", "ai_model")

	def tearDown(self):
		frappe.db.set_value("AI Agent Configuration", "Dev Agent", "ai_model",
		                    self._original_model, update_modified=False)
		for m in self._models:
			frappe.db.delete("AI Model", {"name": m})
			frappe.db.sql("DELETE FROM `__Auth` WHERE doctype='AI Model' AND name=%s", (m,))
		frappe.db.commit()
		frappe.clear_cache()
		super().tearDown()

	def test_a_resolution_failure_never_strands_the_tracking_row(self):
		"""The row is inserted before resolution runs, so anything escaping the
		handler leaves it at "submitted" with nothing ever resuming the parked
		task. That is exactly what the AttributeError did, and why the handler
		catches everything rather than only AgentSandboxError."""
		name = f"_sbx-nokey-{frappe.generate_hash(length=6)}"
		frappe.get_doc({
			"doctype": "AI Model", "model_name": name,
			"provider": frappe.db.get_value("AI Provider", {}, "name"),
			"enable_model": 1,
		}).insert(ignore_permissions=True)
		self._models.append(name)
		frappe.db.set_value("AI Agent Configuration", "Dev Agent", "ai_model", name,
		                    update_modified=False)
		frappe.db.commit()
		frappe.clear_cache()

		settings = SimpleNamespace(
			agent_sandbox_url="https://sandbox.example",
			get_password=lambda f, raise_exception=True: "gh-token",
		)
		with patch.object(ops.frappe, "get_cached_doc", _scoped_get_cached_doc(settings)):
			with self.assertRaises(ops.AgentSandboxError):
				ops.dispatch(self.params(), self.ctx())

		rows = frappe.get_all("Agent Sandbox Run", filters={"target_app": "one_bpmn"},
		                      fields=["name", "state", "error_message"],
		                      order_by="creation desc", limit=1)
		self.assertTrue(rows)
		self.assertEqual(rows[0].state, "failed")
		self.assertTrue(rows[0].error_message)
