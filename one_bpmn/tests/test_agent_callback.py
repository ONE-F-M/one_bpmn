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
		self.assertIn("the clone failed", answer)
