"""The github connector's post_pr_comment: the comment layout, the allowed owners, edit-not-duplicate, and no review calls."""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.processa_connectors.operations import github as gh
from processa.patches.v1_0 import seed_github_connector as seed

PR = "https://github.com/ONE-F-M/one_bpmn/pull/1493"
VERDICT = [
	{"criterion": "AC1 | Given a | Then b", "result": "Pass", "evidence": "Passes on the PR head and fails on the base.", "video_url": "https://v.example/ac1.webm"},
	{"criterion": "AC2 | Given c | Then d", "result": "Fail", "evidence": "expected 1 | got 2"},
	{"criterion": "AC3 | Given e | Then f", "result": "Could not test", "reason": "No spec ran for this criterion."},
]


class TestRenderComment(FrappeTestCase):
	def test_layout_is_the_summary_line_routing_a_table_a_video_line_per_criterion_and_the_reasons(self):
		body = gh.render_comment("Checked on staging.", "Sonnet: small, low-risk change", VERDICT, "ta-1")
		lines = body.splitlines()
		self.assertEqual(lines[0], "Acceptance test: 1 of 3 criteria passed")
		self.assertIn("Routing: Sonnet: small, low-risk change", body)
		self.assertIn("| Criterion | Result | Evidence |", body)
		self.assertIn("| AC2 | Fail | expected 1 \\| got 2 |".replace("AC2", "AC2 \\| Given c \\| Then d"), body)
		self.assertEqual(lines[lines.index("AC1:") + 1], "https://v.example/ac1.webm")  # the URL is alone on its line
		self.assertIn("- AC3: No spec ran for this criterion.", body)
		self.assertTrue(lines[-1].startswith("<!-- testing-agent run:ta-1"))

	def test_nothing_in_the_comment_links_a_trace_and_a_long_comment_is_shortened(self):
		self.assertNotIn("trace", gh.render_comment("", "", VERDICT).lower())
		long = [{"criterion": f"AC{i}", "result": "Pass", "evidence": "x" * 290} for i in range(400)]
		self.assertLessEqual(len(gh.render_comment("", "", long)), gh.MAX_BODY)


class TestPostPrComment(FrappeTestCase):
	def _post(self, params=None, existing=None):
		sent = []

		def call(method, url, token, payload=None):
			sent.append((method, url.replace(gh.API, ""), payload))
			if method == "GET":
				return existing or []
			return {"id": 7, "html_url": "https://github.com/ONE-F-M/one_bpmn/pull/1493#issuecomment-7"}

		with patch.object(gh, "_token", return_value="t"), patch.object(gh, "_call", side_effect=call):
			return gh.post_pr_comment({"pr_url": PR, "verdict": VERDICT, "run_id": "ta-1", **(params or {})}, {}), sent

	def test_it_posts_one_issue_comment_and_returns_its_link(self):
		out, sent = self._post()
		self.assertEqual(out["comment_url"].endswith("issuecomment-7"), True)
		self.assertEqual([(m, u) for m, u, _ in sent if m != "GET"], [("POST", "/repos/ONE-F-M/one_bpmn/issues/1493/comments")])
		self.assertFalse(out["updated"])

	def test_a_rerun_of_the_same_run_edits_its_comment_instead_of_adding_a_second(self):
		out, sent = self._post(existing=[{"id": 99, "body": "x\n<!-- testing-agent run:ta-1 -->"}])
		self.assertEqual([(m, u) for m, u, _ in sent if m != "GET"], [("PATCH", "/repos/ONE-F-M/one_bpmn/issues/comments/99")])
		self.assertTrue(out["updated"])

	def test_the_verdict_may_arrive_as_json_text_and_a_bad_request_is_refused_before_any_call(self):
		_out, sent = self._post({"verdict": json.dumps(VERDICT)})
		self.assertTrue(sent)
		for bad in ({"pr_url": "https://github.com/other-org/x/pull/1"}, {"pr_url": "https://evil.example/ONE-F-M/x/pull/1"},
		            {"pr_url": "https://github.com/ONE-F-M/x/issues/1"}, {"verdict": "not json"}, {"verdict": []}):
			with patch.object(gh, "_token", return_value="t"), patch.object(gh, "_call") as call, self.assertRaises(gh.GitHubCommentError):
				gh.post_pr_comment({"pr_url": PR, "verdict": VERDICT, **bad}, {})
			call.assert_not_called()

	def test_it_never_reaches_a_review_endpoint(self):
		source = inspect.getsource(gh)
		for word in ("/reviews", "pulls/", "APPROVE", "REQUEST_CHANGES", "dismissals"):
			self.assertNotIn(word, source)


class TestToken(FrappeTestCase):
	def _token(self, connector, secret, settings):
		doc = SimpleNamespace(get_password=lambda field, raise_exception=False: secret)
		cached = SimpleNamespace(get_password=lambda field, raise_exception=False: settings)
		with patch("frappe.db.get_value", return_value=connector), patch("frappe.get_doc", return_value=doc), patch("frappe.get_cached_doc", return_value=cached):
			return gh._token()

	def test_the_connectors_token_is_used_first_and_the_settings_token_is_the_fallback(self):
		on = frappe._dict(enabled=1, auth_type="Bearer Token")
		self.assertEqual(self._token(on, " connector-secret ", "settings-secret"), "connector-secret")
		self.assertEqual(self._token(on, "", "settings-secret"), "settings-secret")
		self.assertEqual(self._token(frappe._dict(enabled=0, auth_type="Bearer Token"), "connector-secret", "settings-secret"), "settings-secret")
		self.assertEqual(self._token(frappe._dict(enabled=1, auth_type="None"), "connector-secret", "settings-secret"), "settings-secret")
		self.assertEqual(self._token(None, "connector-secret", "settings-secret"), "settings-secret")

	def test_with_no_token_anywhere_it_says_where_to_set_one(self):
		with self.assertRaises(gh.GitHubCommentError) as caught:
			self._token(frappe._dict(enabled=1, auth_type="Bearer Token"), "", "")
		self.assertIn("Auth Secret on the github connector", str(caught.exception))


class TestSeed(FrappeTestCase):
	def test_the_connector_has_one_python_handler_operation_with_a_handler_that_exists(self):
		op = seed.GITHUB_CONNECTOR["operations"][0]
		self.assertEqual((op["value"], op["executionType"]), ("post_pr_comment", "Python Handler"))
		self.assertTrue(callable(__import__("frappe").get_attr(op["handlerPath"])))
