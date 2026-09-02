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

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops

# The shape _resolve_sandbox_tool_shapes (api/compilation.py) embeds onto a
# connector's task_cfg at compile time — one entry per shape in the
# sandbox_tool_defs ad-hoc sub-process. Used as ctx()'s default task_cfg so
# every test in this file exercises dispatch() the way a real, correctly
# wired dispatch_to_sandbox shape would reach it, without each test having
# to build this fixture itself.
_DEFAULT_SANDBOX_TOOL_SHAPES = json.dumps([
	{"bpmn_id": "read_file", "description": "Read a file.",
	 "parameters": {"path": {"type": "string"}}, "required": ["path"]},
	{"bpmn_id": "write_file", "description": "Write a file.",
	 "parameters": {"path": {"type": "string"}, "content": {"type": "string"}},
	 "required": ["path", "content"]},
])

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

	def ctx(self, sandbox_tool_shapes=_DEFAULT_SANDBOX_TOOL_SHAPES):
		task = SimpleNamespace(
			id="00000000-0000-0000-0000-000000000da1",
			data={},
			task_spec=SimpleNamespace(bpmn_id="ServiceTask_DevAgent", name="ServiceTask_DevAgent"),
		)
		instance = SimpleNamespace(name=self._test_instance.name, initiated_by="Administrator")
		task_cfg = {"sandboxToolShapes": sandbox_tool_shapes} if sandbox_tool_shapes else {}
		return {"instance": instance, "task": task, "task_cfg": task_cfg}

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


class TestSandboxToolForwarding(AgentSandboxCase):
	"""Tool DEFINITIONS live in the BPMN map (sandbox_tool_defs, referenced via
	sandboxToolsAdhoc) and travel fresh in every dispatch payload; the sandbox
	still does all the EXECUTING itself, same as before this existed."""

	def test_missing_sandbox_tool_shapes_is_refused_before_anything_is_created(self):
		# Delta, not an absolute count — this bench's real database already
		# carries rows from actual past dispatches with this target_app.
		before = frappe.db.count("Agent Sandbox Run", {"target_app": "one_bpmn"})
		with self.assertRaises(ops.AgentSandboxError):
			ops.dispatch(self.params(), self.ctx(sandbox_tool_shapes=None))
		self.assertEqual(
			frappe.db.count("Agent Sandbox Run", {"target_app": "one_bpmn"}), before,
			"a rejected dispatch must not leave a row behind",
		)

	def test_sandbox_tool_shapes_transformed_to_anthropic_format_in_payload(self):
		mock_settings = SimpleNamespace(
			agent_sandbox_url="https://sandbox.example.run.app",
			get_password=lambda *a, **k: "fake-github-token",
		)
		mock_response = MagicMock(status_code=202)
		mock_response.raise_for_status = MagicMock()

		with patch.object(frappe, "get_cached_doc", side_effect=_scoped_get_cached_doc(mock_settings)), patch.object(
			ops, "_resolve_agent_config",
			return_value={"system_prompt": "test", "model": "claude-haiku-4-5-20251001", "api_key": "fake-key"},
		), patch.object(ops, "_mint_identity_token", return_value="fake-token"), patch(
			"requests.post", return_value=mock_response
		) as mock_post:
			ops.dispatch(self.params(), self.ctx())

		_args, kwargs = mock_post.call_args
		tools = kwargs["json"]["tools"]
		by_name = {t["name"]: t for t in tools}
		self.assertEqual(set(by_name), {"read_file", "write_file"})
		self.assertEqual(by_name["read_file"]["description"], "Read a file.")
		self.assertEqual(
			by_name["read_file"]["input_schema"],
			{"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
		)

	def test_shape_with_no_parameters_or_required_gets_empty_defaults(self):
		shapes = json.dumps([{"bpmn_id": "list_files", "description": "List files."}])
		mock_settings = SimpleNamespace(
			agent_sandbox_url="https://sandbox.example.run.app",
			get_password=lambda *a, **k: "fake-github-token",
		)
		mock_response = MagicMock(status_code=202)
		mock_response.raise_for_status = MagicMock()

		with patch.object(frappe, "get_cached_doc", side_effect=_scoped_get_cached_doc(mock_settings)), patch.object(
			ops, "_resolve_agent_config",
			return_value={"system_prompt": "test", "model": "claude-haiku-4-5-20251001", "api_key": "fake-key"},
		), patch.object(ops, "_mint_identity_token", return_value="fake-token"), patch(
			"requests.post", return_value=mock_response
		) as mock_post:
			ops.dispatch(self.params(), self.ctx(sandbox_tool_shapes=shapes))

		_args, kwargs = mock_post.call_args
		tool = kwargs["json"]["tools"][0]
		self.assertEqual(tool["input_schema"], {"type": "object", "properties": {}, "required": []})


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

	def _make_agent_config(self, name, *, ai_model, system_prompt="You are a test agent.",
	                       process_model=None):
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
				"process_model": process_model,
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


class TestDispatchingAgentResolution(FrappeTestCase):
	"""The sandbox must run as the agent that dispatched, not always the Dev Agent.

	``_resolve_agent_config`` took no argument and read a module constant, so a
	Frontend Agent dispatch handed the sandbox the Dev Agent's prompt and model.
	Observed on DAS-154626: caller instance was the Frontend Agent map, payload
	said "You are the Dev Agent".
	"""

	def setUp(self):
		super().setUp()
		self._configs = []

	def tearDown(self):
		for n in self._configs:
			frappe.delete_doc("AI Agent Configuration", n, force=True,
			                  ignore_permissions=True, ignore_missing=True)
		super().tearDown()

	def _config_on(self, name, process_model):
		frappe.flags.in_migrate = True
		try:
			doc = frappe.get_doc({
				"doctype": "AI Agent Configuration",
				"agent_name": name,
				"agent_id": name.lower().replace(" ", "-"),
				"agent_framework": "Direct API",
				"process_model": process_model,
			}).insert(ignore_permissions=True)
		finally:
			frappe.flags.in_migrate = False
		self._configs.append(doc.name)
		return doc.name

	class _Instance:
		def __init__(self, process_model):
			self.process_model = process_model

	def test_resolves_the_config_whose_map_dispatched(self):
		pm = _any_process_model()
		name = self._config_on(f"_sbx caller {frappe.generate_hash(length=5)}", pm)
		self.assertEqual(ops._agent_config_name(self._Instance(pm)), name)

	def test_falls_back_to_the_dev_agent_when_the_map_has_no_config(self):
		self.assertEqual(
			ops._agent_config_name(self._Instance("_sbx-no-such-map")),
			ops._AGENT_CONFIG_NAME,
		)

	def test_falls_back_when_there_is_no_instance(self):
		self.assertEqual(ops._agent_config_name(None), ops._AGENT_CONFIG_NAME)

	def test_resolve_reads_the_constant_at_call_time(self):
		"""The default must not bind _AGENT_CONFIG_NAME at import.

		Binding it in the signature silently breaks every test that patches the
		constant, and would pin the fallback to whatever it was at import.
		"""
		import inspect
		self.assertIsNone(
			inspect.signature(ops._resolve_agent_config).parameters["config_name"].default
		)
