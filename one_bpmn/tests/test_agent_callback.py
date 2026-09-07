# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The sandbox's inbound callback: the signature gate and the state machine.

This endpoint had no tests at all, which is the wrong half to leave uncovered.
Dispatch failing is visible — somebody is watching a run that never starts. The
callback failing is silent: the run sits at "running" and whoever is waiting
waits forever. It is also the only ``allow_guest`` surface in the feature, so
its signature gate is the entire access control.
"""

import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import agent_callback as cb

SECRET = "callback-secret-not-real"

# Captured before any test patches it, so the scoped fake can still delegate
# every other doctype to the real implementation — a bare return_value breaks
# Frappe's own internal lookups (System Settings, User) deep inside log_error.
_real_get_cached_doc = frappe.get_cached_doc


class CallbackCase(FrappeTestCase):
	def setUp(self):
		self.made = []
		self.instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_model": _a_process_model(),
		}).insert(ignore_permissions=True)

	def tearDown(self):
		for name in self.made:
			frappe.db.delete("Agent Sandbox Run", {"name": name})
		frappe.db.delete("BPMN Process Instance", {"name": self.instance.name})
		frappe.db.sql(
			"DELETE FROM `tabError Log` WHERE method LIKE 'Dev Agent Sandbox: callback rejected%%'"
		)
		frappe.db.commit()

	def _run(self, state="running"):
		doc = frappe.get_doc({
			"doctype": "Agent Sandbox Run",
			"state": state,
			"target_app": "one_bpmn",
			"git_branch": "staging",
			"caller_instance": self.instance.name,
			"caller_wf_task_id": "wf-task-1",
			"work_item_description": "a callback test",
		}).insert(ignore_permissions=True)
		self.made.append(doc.name)
		frappe.db.commit()
		return doc

	def _post(self, body: dict, signature=None, secret=SECRET):
		"""Call the endpoint the way the sandbox does: a raw body and a header."""
		raw = json.dumps(body).encode()
		valid = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
		settings = SimpleNamespace(get_password=lambda f, raise_exception=True: SECRET)

		def scoped(doctype, *a, **k):
			return settings if doctype == "Processa Settings" else _real_get_cached_doc(doctype, *a, **k)

		with patch.object(cb.frappe, "request", SimpleNamespace(get_data=lambda: raw)), \
		     patch.object(cb.frappe, "get_request_header",
		                  lambda h: valid if signature is None else signature), \
		     patch.object(cb.frappe, "get_cached_doc", scoped), \
		     patch.object(cb.frappe, "enqueue", lambda *a, **k: None):
			return cb.report_result()


def _a_process_model() -> str:
	"""Any process model will do — this suite never runs a diagram, it only
	needs the Link on BPMN Process Instance to resolve. Deliberately NOT the
	"Dev Agent" map: maps ship by export/import, so depending on one makes the
	suite pass or fail on whether somebody imported it."""
	existing = frappe.db.get_value("BPMN Process Model", {"name": ["is", "set"]}, "name")
	if existing:
		return existing
	process = frappe.get_doc({
		"doctype": "Process", "process_name": f"_cb-{frappe.generate_hash(length=6)}",
	}).insert(ignore_permissions=True)
	return frappe.get_doc({
		"doctype": "BPMN Process Model",
		"title": f"_cb-model-{frappe.generate_hash(length=6)}",
		"process_id": f"_cb-{frappe.generate_hash(length=6)}",
		"version": 1,
		"process_name": process.name,
		"bpmn_xml": "<bpmn:definitions/>",
	}).insert(ignore_permissions=True).name


class TestSignatureGate(CallbackCase):
	def test_no_signature_is_refused(self):
		run = self._run()
		self.assertEqual(self._post({"correlation_id": run.name}, signature=""), {"accepted": False})
		self.assertEqual(frappe.db.get_value("Agent Sandbox Run", run.name, "state"), "running")

	def test_a_wrong_signature_is_refused(self):
		run = self._run()
		self.assertEqual(
			self._post({"correlation_id": run.name, "status": "tests_passed"}, signature="deadbeef"),
			{"accepted": False},
		)
		self.assertEqual(frappe.db.get_value("Agent Sandbox Run", run.name, "state"), "running")

	def test_a_signature_over_different_bytes_is_refused(self):
		"""The HMAC covers the exact body. Signing anything else must not pass,
		or the signature stops binding the payload to the sender."""
		run = self._run()
		other = hmac.new(SECRET.encode(), b'{"correlation_id":"something-else"}',
		                 hashlib.sha256).hexdigest()
		self.assertEqual(
			self._post({"correlation_id": run.name, "status": "tests_passed"}, signature=other),
			{"accepted": False},
		)

	def test_an_unknown_correlation_id_looks_identical_to_a_bad_signature(self):
		"""Same opaque answer, so the endpoint cannot be used to discover which
		run ids exist."""
		self.assertEqual(self._post({"correlation_id": "no-such-run"}), {"accepted": False})


class TestOutcomes(CallbackCase):
	def test_a_pass_with_a_pr_completes_the_run(self):
		run = self._run()
		self.assertEqual(
			self._post({"correlation_id": run.name, "status": "tests_passed",
			            "pr_url": "https://github.com/o/r/pull/1"}),
			{"accepted": True},
		)
		row = frappe.db.get_value("Agent Sandbox Run", run.name, ["state", "pr_url"], as_dict=True)
		self.assertEqual(row.state, "completed")
		self.assertEqual(row.pr_url, "https://github.com/o/r/pull/1")

	def test_a_pass_without_a_pr_is_a_failure_not_a_success(self):
		"""Tests passing is not the deliverable — the pull request is. A run that
		reports a pass and opened nothing has produced nothing."""
		run = self._run()
		self._post({"correlation_id": run.name, "status": "tests_passed"})
		row = frappe.db.get_value("Agent Sandbox Run", run.name, ["state", "error_message"], as_dict=True)
		self.assertEqual(row.state, "failed")
		self.assertIn("did not open a pull request", row.error_message)

	def test_a_pass_with_no_changes_is_recorded_as_a_failure(self):
		run = self._run()
		self._post({"correlation_id": run.name, "status": "tests_passed_no_changes"})
		row = frappe.db.get_value("Agent Sandbox Run", run.name, ["state", "error_message"], as_dict=True)
		self.assertEqual(row.state, "failed")
		self.assertIn("no changes", row.error_message)

	def test_a_failure_carries_the_sandbox_reason_through(self):
		run = self._run()
		self._post({"correlation_id": run.name, "status": "tests_failed",
		            "error": "3 tests failed in test_thing.py"})
		row = frappe.db.get_value("Agent Sandbox Run", run.name, ["state", "error_message"], as_dict=True)
		self.assertEqual(row.state, "failed")
		self.assertIn("test_thing.py", row.error_message)

	def test_a_failing_run_can_still_carry_a_pull_request(self):
		"""dev_agent_server.py now opens a PR regardless of test outcome — a
		failing change is delivered for review rather than discarded, since
		the failure may be environment noise unrelated to the change itself.
		The run's own state must still say "failed", though: a PR existing
		must never be read as the test having actually passed."""
		run = self._run()
		self._post({"correlation_id": run.name, "status": "tests_failed",
		            "error": "3 tests failed in test_thing.py",
		            "pr_url": "https://github.com/o/r/pull/13",
		            "files": {"one_bpmn/utils.py": "content"}})
		row = frappe.db.get_value(
			"Agent Sandbox Run", run.name, ["state", "pr_url", "error_message", "files"], as_dict=True
		)
		self.assertEqual(row.state, "failed")
		self.assertEqual(row.pr_url, "https://github.com/o/r/pull/13")
		self.assertIn("test_thing.py", row.error_message)
		self.assertIn("one_bpmn/utils.py", row.files)

	def test_a_replay_cannot_rewrite_a_settled_run(self):
		"""A retrying sandbox must not be able to overwrite the recorded outcome
		— nor resume a caller a second time."""
		run = self._run()
		self._post({"correlation_id": run.name, "status": "tests_passed",
		            "pr_url": "https://github.com/o/r/pull/1"})
		self.assertEqual(
			self._post({"correlation_id": run.name, "status": "tests_failed", "error": "later noise"}),
			{"accepted": True},
		)
		row = frappe.db.get_value("Agent Sandbox Run", run.name, ["state", "pr_url"], as_dict=True)
		self.assertEqual(row.state, "completed")
		self.assertEqual(row.pr_url, "https://github.com/o/r/pull/1")


class TestWhatTheAgentIsTold(CallbackCase):
	def test_a_completed_run_reports_its_pull_request(self):
		run = self._run(state="completed")
		frappe.db.set_value("Agent Sandbox Run", run.name, "pr_url",
		                    "https://github.com/o/r/pull/7", update_modified=False)
		run.reload()
		self.assertIn("pull/7", cb._sandbox_run_answer(run))

	def test_a_failure_is_reported_in_words_not_hidden(self):
		"""The agent asked for this work; a silent failure would have it report
		success it never got."""
		run = self._run(state="failed")
		frappe.db.set_value("Agent Sandbox Run", run.name, "error_message", "the clone failed",
		                    update_modified=False)
		run.reload()
		answer = cb._sandbox_run_answer(run)
		self.assertIn("did not complete", answer)

	def test_a_failure_with_a_pull_request_still_mentions_it(self):
		"""A failing run can carry a pr_url now — the caller must be told
		about it even though state isn't "completed", or it would never
		learn the PR exists just because the test outcome was a failure."""
		run = self._run(state="failed")
		frappe.db.set_value(
			"Agent Sandbox Run", run.name,
			{"error_message": "3 tests failed", "pr_url": "https://github.com/o/r/pull/21"},
			update_modified=False,
		)
		run.reload()
		answer = cb._sandbox_run_answer(run)
		self.assertIn("did not complete", answer)
		self.assertIn("3 tests failed", answer)
		self.assertIn("pull/21", answer)


class TestSandboxAiAgentRun(CallbackCase):
	"""The coding loop runs entirely outside Frappe — this callback is the
	only place its cost/tokens/tool calls can ever be recorded. Confirms
	the AI Agent Run gets created with the right numbers, and that a
	payload with no usage (a loop that crashed before its first model
	call) is a clean no-op rather than a malformed record."""

	def setUp(self):
		super().setUp()
		self._models = []

	def tearDown(self):
		for name in self._models:
			frappe.delete_doc("AI Model", name, force=True, ignore_permissions=True, ignore_missing=True)
		super().tearDown()

	def _make_model(self, name, *, input_cost=3.0, output_cost=15.0):
		doc = frappe.get_doc({
			"doctype": "AI Model",
			"model_name": name,
			"enable_model": 1,
			"input_cost": input_cost,
			"output_cost": output_cost,
		}).insert(ignore_permissions=True)
		self._models.append(doc.name)
		return doc.name

	def test_no_usage_in_the_payload_creates_no_run_and_no_link(self):
		"""run_job()'s own bare-error callback (the coding loop crashed before
		its first model call) carries no agent_usage key at all."""
		run = self._run()
		self._post({"correlation_id": run.name, "status": "failed", "error": "coding loop failed: boom"})
		self.assertIsNone(frappe.db.get_value("Agent Sandbox Run", run.name, "ai_agent_run"))

	def test_usage_in_the_payload_creates_a_linked_ai_agent_run(self):
		model = self._make_model(f"_sbx-model-{frappe.generate_hash(length=6)}")
		run = self._run()
		self._post({
			"correlation_id": run.name,
			"status": "tests_passed",
			"pr_url": "https://github.com/o/r/pull/9",
			"agent_report": "Added the docstring.",
			"agent_model": model,
			"agent_trace": [
				{
					"role": "assistant", "content": "",
					"tool_calls": [
						{"name": "read_file", "arguments": {"path": "a.py"}, "result": {"content": "..."}, "status": "Success"},
						{"name": "write_file", "arguments": {"path": "a.py", "content": "..."}, "result": {"written": True}, "status": "Success"},
					],
					"prompt_tokens": 1200, "completion_tokens": 600,
					"cache_read_tokens": 500, "cache_write_tokens": 100, "latency_ms": 900,
				},
				{
					"role": "assistant", "content": "",
					"tool_calls": [
						{"name": "run_tests", "arguments": {}, "result": {"passed": True}, "status": "Success"},
					],
					"prompt_tokens": 800, "completion_tokens": 400,
					"cache_read_tokens": 0, "cache_write_tokens": 0, "latency_ms": 1100,
				},
				{
					"role": "assistant", "content": "Added the docstring.", "tool_calls": [],
					"prompt_tokens": 0, "completion_tokens": 0,
					"cache_read_tokens": 0, "cache_write_tokens": 0, "latency_ms": 200,
				},
			],
			"agent_started_at": 1000.0,
			"agent_ended_at": 1010.5,
			"agent_usage": {
				"input_tokens": 2000,
				"output_tokens": 1000,
				"cache_read_input_tokens": 500,
				"cache_creation_input_tokens": 100,
			},
		})

		agent_run_name = frappe.db.get_value("Agent Sandbox Run", run.name, "ai_agent_run")
		self.assertTrue(agent_run_name)

		agent_run = frappe.get_doc("AI Agent Run", agent_run_name)
		self.assertEqual(agent_run.model, model)
		self.assertEqual(agent_run.status, "Success")
		self.assertEqual(agent_run.goal_completion, "Achieved")
		self.assertEqual(agent_run.total_prompt_tokens, 2000)
		self.assertEqual(agent_run.total_completion_tokens, 1000)
		self.assertEqual(agent_run.total_cache_read_tokens, 500)
		self.assertEqual(agent_run.total_cache_write_tokens, 100)
		self.assertEqual(agent_run.total_tokens, 3600)
		self.assertEqual(agent_run.duration_ms, 10500)
		self.assertEqual(agent_run.final_output, "Added the docstring.")
		# The flat field is now a cheap derived summary — the real detail is
		# in the Step/Tool Call rows asserted below.
		self.assertEqual(
			frappe.parse_json(agent_run.tool_calls), ["read_file", "write_file", "run_tests"]
		)

		steps = frappe.get_all(
			"AI Agent Step", filters={"run": agent_run_name}, fields=["name", "step_index", "role"],
			order_by="step_index asc",
		)
		self.assertEqual(len(steps), 3)
		self.assertEqual([s.step_index for s in steps], [0, 1, 2])

		first_step_calls = frappe.get_all(
			"AI Agent Tool Call", filters={"parent": steps[0].name}, fields=["tool_name", "status"],
			order_by="idx asc",
		)
		self.assertEqual([c.tool_name for c in first_step_calls], ["read_file", "write_file"])
		self.assertTrue(all(c.status == "Success" for c in first_step_calls))

		final_step = frappe.get_doc("AI Agent Step", steps[2].name)
		self.assertEqual(final_step.content, "Added the docstring.")
		self.assertEqual(len(final_step.tool_calls), 0)

		# $3/1M input, $15/1M output: 2000 * 3/1e6 + 1000 * 15/1e6 = 0.006 + 0.015.
		# Cache costs are deliberately not asserted precisely here — pricing.py
		# derives non-zero cache rates from the input rate by default when the
		# model has no explicit cache pricing, and that derivation is its own
		# concern, not this function's.
		self.assertAlmostEqual(agent_run.total_input_cost, 0.006, places=6)
		self.assertAlmostEqual(agent_run.total_output_cost, 0.015, places=6)
		self.assertGreaterEqual(
			agent_run.estimated_cost, agent_run.total_input_cost + agent_run.total_output_cost
		)

	def test_a_tool_error_is_recorded_as_error_not_reclassified(self):
		"""Confirms _record_sandbox_trace trusts the trace's own status
		rather than re-deriving it the way record_selector_turns does — that
		function's _tool_call_status() only recognizes Processa's own error
		string conventions, not the sandbox's {"error": ...} dict shape, and
		would silently call this "Success" if it were reused here instead."""
		model = self._make_model(f"_sbx-model-{frappe.generate_hash(length=6)}")
		run = self._run()
		self._post({
			"correlation_id": run.name,
			"status": "tests_failed",
			"agent_report": "Could not finish.",
			"agent_model": model,
			"agent_trace": [
				{
					"role": "assistant", "content": "", "tool_calls": [
						{"name": "read_file", "arguments": {"path": "missing.py"},
						 "result": {"error": "path escapes the app directory"}, "status": "Error"},
					],
					"prompt_tokens": 100, "completion_tokens": 50,
					"cache_read_tokens": 0, "cache_write_tokens": 0, "latency_ms": 300,
				},
			],
			"agent_started_at": 1000.0,
			"agent_ended_at": 1001.0,
			"agent_usage": {"input_tokens": 100, "output_tokens": 50,
			                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
		})
		agent_run_name = frappe.db.get_value("Agent Sandbox Run", run.name, "ai_agent_run")
		steps = frappe.get_all("AI Agent Step", filters={"run": agent_run_name}, fields=["name"])
		self.assertEqual(len(steps), 1)
		calls = frappe.get_all(
			"AI Agent Tool Call", filters={"parent": steps[0].name}, fields=["tool_name", "status"],
		)
		self.assertEqual(calls[0].status, "Error")

	def test_a_failed_test_run_records_goal_not_achieved(self):
		model = self._make_model(f"_sbx-model-{frappe.generate_hash(length=6)}")
		run = self._run()
		self._post({
			"correlation_id": run.name,
			"status": "tests_failed",
			"agent_report": "Tests failed.",
			"agent_model": model,
			"agent_trace": [],
			"agent_started_at": 1000.0,
			"agent_ended_at": 1001.0,
			"agent_usage": {"input_tokens": 100, "output_tokens": 50,
			                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
		})
		agent_run_name = frappe.db.get_value("Agent Sandbox Run", run.name, "ai_agent_run")
		agent_run = frappe.get_doc("AI Agent Run", agent_run_name)
		self.assertEqual(agent_run.status, "Success")  # the loop itself didn't crash
		self.assertEqual(agent_run.goal_completion, "Not Achieved")
