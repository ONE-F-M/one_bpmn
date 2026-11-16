"""The "GitHub App JSON" auth type: the connector signs in as the GitHub App, and never as anyone else."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from frappe.tests import IntegrationTestCase, UnitTestCase

from processa.patches.v1_0 import seed_github_connector as seed
from processa.processa_connectors.operations import github as gh
from processa.processa_connectors.operations import http


class _Cache:
	def __init__(self):
		self.values, self.ttl = {}, {}

	def get_value(self, key, expires=False):
		return self.values.get(key)

	def set_value(self, key, value, expires_in_sec=None):
		self.values[key], self.ttl[key] = value, expires_in_sec

	def delete_value(self, key):
		self.values.pop(key, None)


def _key():
	private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
	pem = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
	return pem, private.public_key()


SPEC = SimpleNamespace(
	connector_id="github", base_url="https://api.github.com", credential_source="On this connector", auth_settings_doctype=None,
	auth_secret_field=None, auth_type="GitHub App JSON",
)


class TestGitHubAppAuth(UnitTestCase):
	def setUp(self):
		self.pem, self.public = _key()
		self.cache = _Cache()
		self.posts = []

	def _answer(self, status=201, body=None):
		response = MagicMock(status_code=status, text=json.dumps(body or {}))
		response.json.return_value = body if body is not None else {"token": "ghs_installation"}

		def post(url, headers=None, timeout=None):
			self.posts.append((url, headers))
			return response

		return post

	def _secret(self, **over):
		return json.dumps({"app_id": 12345, "installation_id": 678, "private_key": self.pem, **over})

	def _auth(self, secret=None, answer=None):
		headers = {}
		with patch.object(http, "_read_secret", return_value=secret if secret is not None else self._secret()), \
				patch.object(http.frappe, "cache", return_value=self.cache), patch("requests.post", side_effect=answer or self._answer()):
			http._apply_auth(SPEC, headers, {})
		return headers

	def test_it_signs_an_rs256_jwt_and_trades_it_for_an_installation_token_that_the_call_then_uses(self):
		before = int(time.time())
		headers = self._auth()
		url, sent = self.posts[0]
		self.assertEqual(url, "https://api.github.com/app/installations/678/access_tokens")
		claims = jwt.decode(sent["Authorization"].split(" ", 1)[1], self.public, algorithms=["RS256"], options={"verify_aud": False})
		self.assertEqual(claims["iss"], "12345")
		self.assertAlmostEqual(claims["iat"], before - 60, delta=3)
		self.assertLessEqual(claims["exp"], int(time.time()) + 600)
		self.assertEqual(jwt.get_unverified_header(sent["Authorization"].split(" ", 1)[1])["alg"], "RS256")
		self.assertEqual(headers["Authorization"], "Bearer ghs_installation")

	def test_a_key_pasted_on_one_line_with_backslash_n_still_signs(self):
		one_line = self.pem.replace("\n", "\\n")
		self.assertNotIn("\n", one_line)
		headers = self._auth(secret=json.dumps({"app_id": "1", "installation_id": "2", "private_key": one_line}))
		self.assertEqual(headers["Authorization"], "Bearer ghs_installation")

	def test_a_token_minted_a_moment_ago_is_reused_and_the_cache_lasts_55_minutes(self):
		self._auth()
		self._auth()
		self.assertEqual(len(self.posts), 1)
		self.assertEqual(list(self.cache.ttl.values()), [55 * 60])

	def test_every_call_carries_githubs_headers_unless_the_operation_sets_its_own(self):
		headers = self._auth()
		self.assertEqual(headers["User-Agent"], "processa-testing-agent/1.0")
		self.assertEqual(headers["Accept"], "application/vnd.github+json")
		self.assertEqual(headers["X-GitHub-Api-Version"], "2026-03-10")
		mine = {"Accept": "text/plain"}
		with patch.object(http, "_read_secret", return_value=self._secret()), patch.object(http.frappe, "cache", return_value=self.cache):
			http._apply_auth(SPEC, mine, {})
		self.assertEqual(mine["Accept"], "text/plain")

	def test_a_missing_or_bad_credential_fails_naming_the_connector_and_calls_nothing(self):
		cases = {
			"no secret at all": "",
			"not JSON": "this is not json",
			"missing a field": json.dumps({"app_id": 1, "installation_id": 2}),
			"installation id is not a number": self._secret(installation_id="../orgs"),
			"a private key that is not a key": self._secret(private_key="-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----\n"),
		}
		for label, secret in cases.items():
			self.posts.clear()
			with patch.object(http, "_read_secret", return_value=secret), patch.object(http.frappe, "cache", return_value=_Cache()), \
					patch("requests.post", side_effect=self._answer()), patch.object(http.frappe, "get_cached_doc") as settings:
				with self.assertRaises(http.ConnectorHTTPError, msg=label) as caught:
					http._apply_auth(SPEC, {}, {})
			self.assertIn("connector github", str(caught.exception), label)
			self.assertEqual(self.posts, [], label)
			settings.assert_not_called()  # never the github_token PAT in Processa Settings

	def test_a_key_github_refuses_fails_naming_the_connector(self):
		with self.assertRaises(http.ConnectorHTTPError) as caught:
			self._auth(answer=self._answer(status=401, body={"message": "A JSON web token could not be decoded"}))
		self.assertIn("connector github", str(caught.exception))
		self.assertIn("401", str(caught.exception))
		self.assertEqual(self.cache.values, {})


class TestPostPrCommentSignsInAsTheApp(IntegrationTestCase):
	def test_with_the_app_auth_type_the_comment_uses_the_apps_token(self):
		with patch.object(gh.frappe.db, "get_value", return_value=frappe._dict(enabled=1, auth_type="GitHub App JSON")), \
				patch("processa.processa_connectors.manifest.get_execution_spec", return_value=SPEC), \
				patch.object(gh.http_ops, "_github_app_token", return_value="ghs_app") as app:
			self.assertEqual(gh._token(), "ghs_app")
		app.assert_called_once_with(SPEC)

	def test_with_the_app_auth_type_a_failing_key_fails_and_never_reads_the_personal_token(self):
		with patch.object(gh.frappe.db, "get_value", return_value=frappe._dict(enabled=1, auth_type="GitHub App JSON")), \
				patch("processa.processa_connectors.manifest.get_execution_spec", return_value=SPEC), \
				patch.object(gh.http_ops, "_github_app_token", side_effect=http.ConnectorHTTPError("no key at connector github")), \
				patch.object(gh.frappe, "get_cached_doc") as settings:
			with self.assertRaises(gh.GitHubCommentError) as caught:
				gh._token()
		self.assertIn("connector github", str(caught.exception))
		settings.assert_not_called()


class TestGitHubConnectorRecords(UnitTestCase):
	def test_the_auth_type_is_an_option_everywhere_it_has_to_be(self):
		import os

		root = os.path.dirname(os.path.dirname(__file__))
		doctype = open(os.path.join(root, "doctype", "bpmn_connector", "bpmn_connector.json")).read()
		self.assertIn("GitHub App JSON", json.loads(doctype)["fields"][[f["fieldname"] for f in json.loads(doctype)["fields"]].index("auth_type")]["options"])
		controller = open(os.path.join(root, "doctype", "bpmn_connector", "bpmn_connector.py")).read()
		self.assertIn('"Service Account JSON", "GitHub App JSON"]', controller)
		self.assertIn('"Basic", "GitHub App JSON")', controller)
		prompt = open(os.path.join(os.path.dirname(root), "patches", "v1_0", "seed_connector_agent_config.py")).read()
		self.assertIn("GitHub App JSON", prompt)

	def test_the_github_connector_signs_in_as_the_app_and_has_the_four_operations(self):
		manifest = seed.GITHUB_CONNECTOR
		self.assertEqual(manifest["execution"]["auth"]["type"], "GitHub App JSON")
		self.assertEqual(manifest["execution"]["baseUrl"], "https://api.github.com")
		self.assertEqual([o["value"] for o in manifest["operations"]], ["post_pr_comment", "get_pull_request", "list_pr_files", "request_reviewers"])

	def test_the_http_operations_use_the_documented_paths(self):
		by = {o["value"]: o["http"] for o in seed.HTTP_OPERATIONS}
		self.assertEqual((by["get_pull_request"]["method"], by["get_pull_request"]["url"]), ("GET", "repos/{{ params.owner }}/{{ params.repo }}/pulls/{{ params.number }}"))
		self.assertEqual((by["list_pr_files"]["method"], by["list_pr_files"]["url"].endswith("/pulls/{{ params.number }}/files")), ("GET", True))
		self.assertEqual((by["request_reviewers"]["method"], by["request_reviewers"]["url"].endswith("/pulls/{{ params.number }}/requested_reviewers")), ("POST", True))
		self.assertIn("tojson", by["request_reviewers"]["body"])
