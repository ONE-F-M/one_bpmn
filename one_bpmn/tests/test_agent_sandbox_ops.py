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


class TestAgentConfigResolution(AgentSandboxCase):
	"""The real credential path — NOT mocked.

	Every other test in this file patches _resolve_agent_config, which is why a
	fully green suite sat alongside a dispatch that could not run at all: the
	connection moved off AI Provider and onto AI Model, and reading
	provider.enabled raised AttributeError. These exercise the real function.
	"""

	def _model(self, *, provider="Anthropic", enabled=1, key="sk-test-not-real", api_name=None):
		if not frappe.db.exists("AI Provider", provider):
			frappe.get_doc({"doctype": "AI Provider", "provider": provider}).insert(
				ignore_permissions=True
			)
		name = f"_sbx-model-{frappe.generate_hash(length=6)}"
		frappe.get_doc({
			"doctype": "AI Model", "model_name": name, "provider": provider,
			"enable_model": enabled, "model_api_name": api_name,
		}).insert(ignore_permissions=True)
		if key:
			from frappe.utils.password import set_encrypted_password

			set_encrypted_password("AI Model", name, key, "api_key")
		self._models.append(name)
		frappe.db.commit()
		return name

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

	def _point_dev_agent_at(self, model):
		frappe.db.set_value("AI Agent Configuration", "Dev Agent", "ai_model", model,
		                    update_modified=False)
		frappe.db.commit()
		frappe.clear_cache()

	def test_the_key_is_read_off_the_model_not_the_provider(self):
		self._point_dev_agent_at(self._model(key="sk-on-the-model"))
		self.assertEqual(ops._resolve_agent_config()["api_key"], "sk-on-the-model")

	def test_model_api_name_is_what_goes_on_the_wire(self):
		model = self._model(api_name="claude-wire-name")
		self._point_dev_agent_at(model)
		self.assertEqual(ops._resolve_agent_config()["model"], "claude-wire-name")

	def test_without_an_api_name_the_record_name_is_sent(self):
		model = self._model(api_name=None)
		self._point_dev_agent_at(model)
		self.assertEqual(ops._resolve_agent_config()["model"], model)

	def test_a_disabled_model_is_refused(self):
		"""enable_model is the only switch left — a provider cannot be turned off."""
		self._point_dev_agent_at(self._model(enabled=0))
		with self.assertRaises(ops.AgentSandboxError):
			ops._resolve_agent_config()

	def test_a_model_with_no_key_is_refused(self):
		self._point_dev_agent_at(self._model(key=None))
		with self.assertRaises(ops.AgentSandboxError):
			ops._resolve_agent_config()

	def test_a_model_with_no_provider_is_refused(self):
		name = f"_sbx-model-{frappe.generate_hash(length=6)}"
		frappe.get_doc({"doctype": "AI Model", "model_name": name, "enable_model": 1}).insert(
			ignore_permissions=True
		)
		self._models.append(name)
		frappe.db.commit()
		self._point_dev_agent_at(name)
		with self.assertRaises(ops.AgentSandboxError):
			ops._resolve_agent_config()

	def test_a_resolution_failure_never_strands_the_tracking_row(self):
		"""The row is inserted before resolution runs, so anything escaping the
		handler leaves it at "submitted" with nothing ever resuming the parked
		task. That is exactly what the AttributeError did."""
		self._point_dev_agent_at(self._model(key=None))
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
