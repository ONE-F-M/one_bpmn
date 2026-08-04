# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Who may use a connector, and how it authenticates.

Two capabilities that turn the connector DocTypes from a description of what
exists into a description of who may run it and as whom:

  Allowed Roles         restricts a connector to named roles
  Service Account JSON  mints a Google access token from the key on the
                        connector, which is what lets a Google operation be
                        configuration rather than a Python handler holding an
                        SDK client

The gating tests care about one thing above all: hiding a connector in the
modeler is convenience, and the runtime check is the actual control. A test
that only proved the panel filtered would be testing the cosmetic half.
"""

import ast
import inspect
import json
import textwrap
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from one_bpmn.one_bpmn.connectors import http_ops
from one_bpmn.one_bpmn.connectors.api import get_connector_manifests
from one_bpmn.one_bpmn.connectors.manifest import (
	clear_manifest_cache,
	user_may_use_connector,
)

GATED = "google_slides"
ROLE = "_Test Connector Role"


def _instance():
	return SimpleNamespace(context_doctype=None, context_docname=None, name="INST-1")


class ConnectorAccessFixtures:
	"""Not a TestCase — a TestCase base re-runs its tests in every subclass."""

	def setUp(self):
		if not frappe.db.exists("Role", ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1}).insert(
				ignore_permissions=True
			)
		self._restrict(None)

	def tearDown(self):
		self._restrict(None)
		frappe.db.rollback()
		clear_manifest_cache()

	def _as(self, *roles):
		"""Act as an ordinary user with these roles.

		Both halves are needed: Administrator is deliberately exempt from every
		gate, so patching only the role list would still be allowed through.
		"""
		return patch.multiple(
			frappe,
			get_roles=MagicMock(return_value=list(roles)),
			session=frappe._dict(user="gated@example.com"),
		)

	def _restrict(self, role):
		"""Set (or clear) Allowed Roles on the gated connector."""
		doc = frappe.get_doc("BPMN Connector", GATED)
		doc.allowed_roles = []
		if role:
			doc.append("allowed_roles", {"role": role})
		doc.save(ignore_permissions=True)
		clear_manifest_cache()


class TestRoleGating(ConnectorAccessFixtures, unittest.TestCase):
	def test_a_connector_with_no_roles_is_open(self):
		"""The default, and what every existing connector is — the gate must be
		opt-in or this change would lock everyone out of everything."""
		self.assertTrue(user_may_use_connector(GATED, user="Administrator"))
		self.assertIn(GATED, [m["connectorId"] for m in get_connector_manifests()])

	def test_a_restricted_connector_is_refused_without_the_role(self):
		self._restrict(ROLE)
		with self._as("Employee"):
			self.assertFalse(user_may_use_connector(GATED))

	def test_a_restricted_connector_is_allowed_with_the_role(self):
		self._restrict(ROLE)
		with self._as("Employee", ROLE):
			self.assertTrue(user_may_use_connector(GATED))

	def test_administrator_is_never_locked_out(self):
		"""A misconfigured gate must always be undoable."""
		self._restrict(ROLE)
		self.assertTrue(user_may_use_connector(GATED, user="Administrator"))

	def test_the_modeler_does_not_offer_a_restricted_connector(self):
		self._restrict(ROLE)
		with self._as("Employee"):
			offered = [m["connectorId"] for m in get_connector_manifests()]
		self.assertNotIn(GATED, offered)
		# Other connectors are unaffected — the gate is per connector.
		self.assertIn("google_drive", offered)

	def test_other_connectors_stay_visible_to_the_gated_user(self):
		self._restrict(ROLE)
		with self._as("Employee"):
			offered = {m["connectorId"] for m in get_connector_manifests()}
		self.assertTrue({"google_drive", "google_docs", "google_sheets"} <= offered)


class TestGateIsEnforcedAtRuntime(ConnectorAccessFixtures, unittest.TestCase):
	"""The half that actually matters.

	A diagram authored before the restriction — or by someone who had the role
	and has since lost it — must not still run the connector just because the
	panel stopped offering it.
	"""

	def _dispatch(self, fail_on_error=False):
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import dispatch_connector

		task = SimpleNamespace(data={})
		cfg = {
			"connectorId": GATED,
			"operation": "getText",
			"resultVariable": "out",
			"connectorParams": '{"presentation": "P1"}',
		}
		if fail_on_error:
			cfg["failOnError"] = "1"
		dispatch_connector(_instance(), task, cfg, "t1")
		return task

	def test_a_gated_connector_does_not_execute(self):
		self._restrict(ROLE)
		with self._as("Employee"), patch(
			"one_bpmn.one_bpmn.integrations.google_slides.get_text"
		) as called:
			task = self._dispatch()

		called.assert_not_called()
		self.assertNotIn("out", task.data)

	def test_it_raises_when_the_task_is_marked_fail_on_error(self):
		self._restrict(ROLE)
		with self._as("Employee"):
			with self.assertRaises(frappe.ValidationError) as ctx:
				self._dispatch(fail_on_error=True)
		self.assertIn(GATED, str(ctx.exception))

	def test_it_runs_normally_for_a_permitted_user(self):
		self._restrict(ROLE)
		with self._as(ROLE), patch(
			"one_bpmn.one_bpmn.integrations.google_slides.get_text", return_value="hello"
		):
			task = self._dispatch()
		self.assertEqual(task.data["out"], {"text": "hello"})


class TestServiceAccountAuth(unittest.TestCase):
	"""Minting a Google token from the key on the connector."""

	def _spec(self, **overrides):
		base = {
			"connector_id": "google_drive",
			"auth_type": "Service Account JSON",
			"credential_source": "On this connector",
			"auth_scopes": "https://www.googleapis.com/auth/drive",
			"auth_settings_doctype": None,
			"auth_secret_field": None,
		}
		base.update(overrides)
		return frappe._dict(base)

	def tearDown(self):
		http_ops.clear_service_account_token("google_drive")

	def test_the_token_becomes_a_bearer_header(self):
		headers, query = {}, {}
		with patch.object(http_ops, "_service_account_token", return_value="tok-123"):
			http_ops._apply_auth(self._spec(), headers, query)
		self.assertEqual(headers["Authorization"], "Bearer tok-123")
		self.assertEqual(query, {}, "a service account must never land in the query string")

	def test_scopes_are_required(self):
		"""Google refuses a token request with no scope, and the resulting error
		says nothing useful — so this fails early with a message that does."""
		with patch.object(http_ops, "_read_secret", return_value='{"type":"service_account"}'):
			with self.assertRaises(http_ops.ConnectorHTTPError) as ctx:
				http_ops._service_account_token(self._spec(auth_scopes=""))
		self.assertIn("Scopes", str(ctx.exception))

	def test_a_missing_key_names_where_it_should_be(self):
		with patch.object(http_ops, "_read_secret", return_value=None):
			with self.assertRaises(http_ops.ConnectorHTTPError) as ctx:
				http_ops._service_account_token(self._spec())
		self.assertIn("google_drive", str(ctx.exception))

	def test_a_key_that_is_not_json_says_so(self):
		with patch.object(http_ops, "_read_secret", return_value="not json at all"):
			with self.assertRaises(http_ops.ConnectorHTTPError) as ctx:
				http_ops._service_account_token(self._spec())
		self.assertIn("not valid JSON", str(ctx.exception))

	def test_the_token_is_cached_rather_than_reminted_per_call(self):
		"""A token lasts an hour; minting one per operation would add a network
		round-trip and an RSA signature to every connector task."""
		creds = MagicMock(token="tok-cached")
		with patch.object(http_ops, "_read_secret", return_value='{"type":"service_account"}'), patch(
			"google.oauth2.service_account.Credentials.from_service_account_info", return_value=creds
		) as factory:
			first = http_ops._service_account_token(self._spec())
			second = http_ops._service_account_token(self._spec())

		self.assertEqual(first, "tok-cached")
		self.assertEqual(second, "tok-cached")
		factory.assert_called_once()

	def test_saving_the_connector_drops_the_cached_token(self):
		"""A rotated key must not keep working off the old token for an hour."""
		frappe.cache().set_value("bpmn_connector_sa_token:google_drive", "stale")
		frappe.get_doc("BPMN Connector", "google_drive").save(ignore_permissions=True)
		self.assertIsNone(frappe.cache().get_value("bpmn_connector_sa_token:google_drive"))
		frappe.db.rollback()

	def test_each_connector_can_hold_its_own_account(self):
		"""The point of putting the credential on the connector: two connectors
		may talk to two different Google accounts."""
		for connector_id in ("google_drive", "google_docs"):
			doc = frappe.get_doc("BPMN Connector", connector_id)
			self.assertEqual(doc.auth_type, "Service Account JSON")
			self.assertEqual(doc.credential_source, "On this connector")
			self.assertTrue(doc.auth_scopes, "scopes are per connector")


class TestGoogleConnectorsAreConfigured(unittest.TestCase):
	"""What the conversion patch was for."""

	def test_no_google_operation_relies_on_implicit_registry_lookup(self):
		"""Every operation states how it runs — configured HTTP, or a named
		handler. Nothing is found by accident any more."""
		from one_bpmn.one_bpmn.connectors.manifest import get_execution_spec, load_manifests

		for m in load_manifests():
			if not m["connectorId"].startswith("google_"):
				continue
			for op in m["operations"]:
				with self.subTest(connector=m["connectorId"], operation=op["value"]):
					spec = get_execution_spec(m["connectorId"], op["value"])
					self.assertIsNotNone(spec)
					if spec.execution_type == "HTTP Request":
						self.assertTrue(spec.url_template)
					else:
						self.assertTrue(
							spec.handler_path,
							"a Python operation must name its handler, not rely on the registry",
						)

	def test_every_named_handler_is_importable(self):
		from one_bpmn.one_bpmn.connectors.manifest import get_execution_spec, load_manifests

		for m in load_manifests():
			for op in m["operations"]:
				spec = get_execution_spec(m["connectorId"], op["value"])
				if spec and spec.handler_path:
					with self.subTest(handler=spec.handler_path):
						self.assertTrue(callable(frappe.get_attr(spec.handler_path)))

	def test_the_bodies_render_to_valid_json(self):
		"""A malformed body reaches Google as a 400 that names a field, not the
		template — so it is worth catching here."""
		from one_bpmn.one_bpmn.connectors.manifest import field_specs, get_execution_spec, load_manifests

		sample = {"String": "x", "Text": "x", "Dropdown": "x", "Boolean": "1", "Hidden": "x"}
		for m in load_manifests():
			if not m["connectorId"].startswith("google_"):
				continue
			for op in m["operations"]:
				spec = get_execution_spec(m["connectorId"], op["value"])
				if not (spec and spec.execution_type == "HTTP Request" and spec.body_template):
					continue
				params = {
					name: ("[[1,2]]" if name == "values" else sample.get(f.get("type"), "x"))
					for name, f in field_specs(m["connectorId"], op["value"]).items()
				}
				with self.subTest(connector=m["connectorId"], operation=op["value"]):
					rendered = http_ops._render(
						spec.body_template, {"params": frappe._dict(params)}, "body"
					)
					json.loads(rendered)  # raises if the template produced junk


class TestCredentialsLiveOnTheConnector(unittest.TestCase):
	"""A connector's Secret is the only place a Google key is read from.

	These guard the absence of a fallback, which is harder to keep than it
	sounds: a global default is invisible when it works. With one in place every
	connector silently shares one account, so pointing one at a second Google
	project looks configured and changes nothing — and nobody finds out until an
	audit asks which account touched a file.
	"""

	def setUp(self):
		from one_bpmn.one_bpmn.integrations import google_common

		self.gc = google_common

	def test_a_named_connector_uses_its_own_key(self):
		with patch.object(
			self.gc, "_connector_service_account",
			side_effect=lambda cid: '{"client_email": "%s@x"}' % cid if cid else None,
		):
			self.assertEqual(
				self.gc.load_service_account_info("google_docs")["client_email"], "google_docs@x"
			)

	def test_a_caller_with_no_connector_falls_back_to_drive(self):
		"""Script Tasks import the Drive integration directly and know nothing
		about connectors — they must still resolve to a real key."""
		with patch.object(
			self.gc, "_connector_service_account",
			side_effect=lambda cid: '{"client_email": "drive@x"}' if cid == "google_drive" else None,
		):
			self.assertEqual(self.gc.load_service_account_info()["client_email"], "drive@x")

	def test_no_connector_key_is_an_error_not_a_global_default(self):
		"""The point of the whole change. If a fallback ever comes back, this is
		what catches it — nothing else would, because a fallback that works looks
		exactly like a correct configuration."""
		with patch.object(self.gc, "_connector_service_account", return_value=None):
			with self.assertRaises(self.gc.GoogleConfigError) as ctx:
				self.gc.load_service_account_info("google_sheets")

		# The error has to say where to put the key, not just that it is absent.
		self.assertIn("google_sheets", str(ctx.exception))
		self.assertIn("Secret", str(ctx.exception))

	def test_the_loader_reads_no_settings_doctype_at_all(self):
		"""A settings read would resurrect the shared-account problem even if the
		order put the connector first, because it still lets a site run with no
		key on any connector."""
		self.assertFalse(hasattr(self.gc, "_read_setting_secret"))
		self.assertFalse(hasattr(self.gc, "_warn_legacy_credential"))

		# Read the code, not the docstring — the docstring names the old locations
		# on purpose, to say why they are gone.
		tree = ast.parse(textwrap.dedent(inspect.getsource(self.gc.load_service_account_info)))
		body = tree.body[0].body
		if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
			body = body[1:]
		code = "\n".join(ast.unparse(node) for node in body)

		for gone in ("frappe.conf", "gcp.json", "Processa Settings", "AI Chat Settings", "open("):
			self.assertNotIn(gone, code, f"{gone} is back in the credential lookup")

	def test_a_site_config_key_is_ignored(self):
		"""Belt and braces for the above: even with the old site_config key
		present, an empty connector Secret must still fail."""
		with patch.object(self.gc, "_connector_service_account", return_value=None), patch.dict(
			frappe.conf, {"google_drive_service_account_json": '{"client_email": "legacy@x"}'}
		):
			with self.assertRaises(self.gc.GoogleConfigError):
				self.gc.load_service_account_info("google_drive")

	def test_a_secret_that_is_not_a_whole_key_file_says_so(self):
		"""Pasting just the private key, or an API token, is the likely mistake
		now that the field is the only input — the error must name it."""
		with patch.object(self.gc, "_connector_service_account", return_value="not-json"):
			with self.assertRaises(self.gc.GoogleConfigError) as ctx:
				self.gc.load_service_account_info("google_docs")

		self.assertIn("whole key file", str(ctx.exception))

	def test_every_google_connector_carries_its_own_key(self):
		for connector_id in ("google_drive", "google_docs", "google_sheets", "google_slides"):
			with self.subTest(connector=connector_id):
				doc = frappe.get_doc("BPMN Connector", connector_id)
				self.assertTrue(
					doc.get_password("auth_secret", raise_exception=False),
					"the migration patch should have copied the key here",
				)

	def test_the_settings_field_is_gone(self):
		self.assertIsNone(
			frappe.get_meta("Processa Settings").get_field("google_drive_service_account_json")
		)

	def test_the_secret_field_accepts_a_whole_service_account_key(self):
		"""A Password control caps its input at ``df.length`` or 140 characters.
		At 140 a service-account key — ~2.3kB, mostly the PEM private key —
		cannot be pasted in at all, which made the field that is now the *only*
		credential input unusable for its main purpose.
		"""
		field = frappe.get_meta("BPMN Connector").get_field("auth_secret")
		self.assertGreaterEqual(field.length, 10000)

		live = frappe.get_doc("BPMN Connector", "google_drive").get_password(
			"auth_secret", raise_exception=False
		)
		self.assertGreater(len(live), 140, "sanity: a real key is longer than the old default cap")
		self.assertLess(len(live), field.length)
