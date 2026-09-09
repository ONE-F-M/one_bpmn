# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-002191: credential health for AI Models.

Three promises, each pinned here:

* an enabled model cannot be saved without a provider and a key, and a key the
  provider rejects is refused at save time;
* a model that fails for a credential reason is alerted on within one sweep,
  once per problem, and a later success closes the loop;
* while a model is Unhealthy, new runs on it are refused and counted instead
  of each becoming a failed AI Agent Run.

The state lives in read-only ``health_*`` fields on AI Model.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import remove_encrypted_password

from one_bpmn.agents import model_health
from one_bpmn.agents.model_health import (
	ModelUnavailable,
	alert_unhealthy_models,
	blocked_reason,
	failure_kind,
	is_credential_failure,
	note_run_outcome,
	probe_credentials,
	probe_enabled_models,
	record_failure,
	record_success,
	refuse_new_run,
)

PROBE = "one_bpmn.agents.model_health.probe_credentials"


def _ok():
	return {"ok": True, "code": "OK", "detail": "Anthropic accepted the API key"}


def _rejected():
	return {"ok": False, "code": "INVALID_KEY", "detail": "Anthropic rejected the API key (HTTP 401): invalid x-api-key"}


def _unreachable():
	return {"ok": False, "code": "UNREACHABLE", "detail": "Anthropic did not answer within 15 seconds"}


class HealthCase(FrappeTestCase):
	"""Fixtures are committed (the engine commits observability writes), so
	they are removed by name rather than trusted to the rollback."""

	def setUp(self):
		super().setUp()
		self.models = []
		self.provider = self._provider("Anthropic")
		frappe.flags.skip_ai_model_probe = False
		frappe.flags.ai_model_probe_in_test = True

	def tearDown(self):
		frappe.flags.ai_model_probe_in_test = False
		for m in self.models:
			frappe.db.delete("Notification Log", {"document_type": "AI Model", "document_name": m})
			frappe.db.delete("AI Model", {"name": m})
			remove_encrypted_password("AI Model", m, "api_key")
		frappe.db.commit()
		super().tearDown()

	def _provider(self, name):
		if not frappe.db.exists("AI Provider", name):
			frappe.get_doc({"doctype": "AI Provider", "provider": name}).insert(ignore_permissions=True)
			frappe.db.commit()
		return name

	def _name(self):
		return f"health-probe-{frappe.generate_hash(length=8)}"

	def _health(self, name, *fields):
		if len(fields) == 1:
			return frappe.db.get_value("AI Model", name, fields[0])
		return frappe.db.get_value("AI Model", name, list(fields), as_dict=True)

	def _model(self, *, enabled=1, key="sk-test-not-real", provider="Anthropic", probe=None):
		"""Insert a model with the probe stubbed (default: passes)."""
		name = self._name()
		self.models.append(name)
		doc = frappe.get_doc({
			"doctype": "AI Model",
			"model_name": name,
			"provider": provider,
			"enable_model": enabled,
			"api_key": key,
		})
		with patch(PROBE, return_value=probe or _ok()):
			doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return doc.name


# ---------------------------------------------------------------------------
# Save-time validation
# ---------------------------------------------------------------------------


class TestSaveValidation(HealthCase):
	def test_enabled_model_without_key_is_refused(self):
		name = self._name()
		self.models.append(name)
		doc = frappe.get_doc({
			"doctype": "AI Model", "model_name": name, "provider": "Anthropic", "enable_model": 1,
		})
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.insert(ignore_permissions=True)
		self.assertIn("API key", str(ctx.exception))

	def test_enabled_model_without_provider_is_refused(self):
		name = self._name()
		self.models.append(name)
		doc = frappe.get_doc({
			"doctype": "AI Model", "model_name": name, "enable_model": 1, "api_key": "sk-x",
		})
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.insert(ignore_permissions=True)
		self.assertIn("AI Provider", str(ctx.exception))

	def test_disabled_model_needs_neither(self):
		name = self._name()
		self.models.append(name)
		doc = frappe.get_doc({"doctype": "AI Model", "model_name": name, "enable_model": 0})
		with patch(PROBE) as probe:
			doc.insert(ignore_permissions=True)
		probe.assert_not_called()

	def test_a_rejected_key_blocks_the_save(self):
		name = self._name()
		self.models.append(name)
		doc = frappe.get_doc({
			"doctype": "AI Model", "model_name": name, "provider": "Anthropic",
			"enable_model": 1, "api_key": "sk-wrong",
		})
		with patch(PROBE, return_value=_rejected()):
			with self.assertRaises(frappe.ValidationError) as ctx:
				doc.insert(ignore_permissions=True)
		self.assertIn("rejected the API key", str(ctx.exception))
		self.assertFalse(frappe.db.exists("AI Model", name))

	def test_an_unreachable_provider_warns_but_saves(self):
		name = self._model(probe=_unreachable())
		self.assertTrue(frappe.db.exists("AI Model", name))
		# Nothing was proven, so the model is neither Healthy nor Unhealthy.
		self.assertEqual(self._health(name, "health_status"), "Unknown")
		self.assertIsNone(self._health(name, "health_ok_at"))

	def test_a_passing_probe_records_healthy(self):
		name = self._model()
		row = self._health(name, "health_status", "health_check_source", "health_ok_at")
		self.assertEqual(row.health_status, "Healthy")
		self.assertEqual(row.health_check_source, "Save")
		self.assertIsNotNone(row.health_ok_at)

	def test_probe_is_tried_with_the_new_key(self):
		"""The key typed into the form is what gets checked — not the stored one,
		which does not exist yet on insert."""
		name = self._name()
		self.models.append(name)
		doc = frappe.get_doc({
			"doctype": "AI Model", "model_name": name, "provider": "Anthropic",
			"enable_model": 1, "api_key": "sk-fresh",
		})
		with patch(PROBE, return_value=_ok()) as probe:
			doc.insert(ignore_permissions=True)
		provider, key, endpoint = probe.call_args[0]
		self.assertEqual((provider, key), ("Anthropic", "sk-fresh"))

	def test_untouched_key_does_not_reprobe(self):
		name = self._model()
		doc = frappe.get_doc("AI Model", name)
		doc.input_cost = 3
		with patch(PROBE) as probe:
			doc.save(ignore_permissions=True)
		probe.assert_not_called()

	def test_changing_the_key_reprobes(self):
		name = self._model()
		doc = frappe.get_doc("AI Model", name)
		doc.api_key = "sk-replacement"
		with patch(PROBE, return_value=_ok()) as probe:
			doc.save(ignore_permissions=True)
		self.assertEqual(probe.call_args[0][1], "sk-replacement")

	def test_disabling_clears_the_block(self):
		name = self._model()
		record_failure(name, "PROVIDER_DISABLED", "AI Model has no API key set.")
		self.assertIsNotNone(blocked_reason(name))
		doc = frappe.get_doc("AI Model", name)
		doc.enable_model = 0
		doc.save(ignore_permissions=True)
		self.assertIsNone(blocked_reason(name))
		self.assertEqual(self._health(name, "health_status"), "Unknown")

	def test_a_form_save_cannot_reset_platform_health(self):
		"""The form sends back the health fields it loaded. A run that marked
		the model Unhealthy in between must not be undone by an unrelated edit."""
		name = self._model()
		doc = frappe.get_doc("AI Model", name)  # loaded while Healthy
		record_failure(name, "INVALID_KEY", "rejected")
		doc.input_cost = 3
		doc.save(ignore_permissions=True)
		self.assertEqual(self._health(name, "health_status"), "Unhealthy")
		self.assertIsNotNone(blocked_reason(name))

	def test_platform_writes_do_not_change_who_edited_the_model(self):
		name = self._model()
		before = frappe.db.get_value("AI Model", name, ["modified", "modified_by"], as_dict=True)
		record_failure(name, "INVALID_KEY", "rejected")
		after = frappe.db.get_value("AI Model", name, ["modified", "modified_by"], as_dict=True)
		self.assertEqual((before.modified, before.modified_by), (after.modified, after.modified_by))

	def test_patches_and_migrations_skip_the_probe(self):
		name = self._name()
		self.models.append(name)
		doc = frappe.get_doc({
			"doctype": "AI Model", "model_name": name, "provider": "Anthropic",
			"enable_model": 1, "api_key": "sk-x",
		})
		frappe.flags.in_patch = True
		try:
			with patch(PROBE) as probe:
				doc.insert(ignore_permissions=True)
		finally:
			frappe.flags.in_patch = False
		probe.assert_not_called()


# ---------------------------------------------------------------------------
# The probe itself
# ---------------------------------------------------------------------------


class TestProbe(FrappeTestCase):
	def _resp(self, status, body=None, text=""):
		resp = MagicMock()
		resp.status_code = status
		resp.text = text
		resp.json.return_value = body if body is not None else {}
		return resp

	def test_no_provider(self):
		self.assertEqual(probe_credentials("", "sk")["code"], "NO_PROVIDER")

	def test_unknown_dialect(self):
		self.assertEqual(probe_credentials("Test Provider", "sk")["code"], "NO_DIALECT")

	def test_no_key(self):
		self.assertEqual(probe_credentials("Anthropic", "")["code"], "NO_KEY")

	def test_accepted(self):
		with patch("requests.get", return_value=self._resp(200, {"data": []})) as get:
			result = probe_credentials("Anthropic", "sk-ok")
		self.assertTrue(result["ok"])
		url, kwargs = get.call_args[0][0], get.call_args[1]
		self.assertTrue(url.startswith("https://api.anthropic.com/v1/models"))
		self.assertEqual(kwargs["headers"]["x-api-key"], "sk-ok")

	def test_rejected_is_a_credential_failure(self):
		body = {"error": {"type": "authentication_error", "message": "invalid x-api-key"}}
		with patch("requests.get", return_value=self._resp(401, body)):
			result = probe_credentials("OpenAI", "sk-bad")
		self.assertEqual(result["code"], "INVALID_KEY")
		self.assertIn("invalid x-api-key", result["detail"])

	def test_server_error_is_not_a_credential_failure(self):
		with patch("requests.get", return_value=self._resp(503, text="overloaded")):
			result = probe_credentials("Google", "sk")
		self.assertEqual(result["code"], "PROVIDER_ERROR")

	def test_timeout_is_unreachable(self):
		import requests

		with patch("requests.get", side_effect=requests.Timeout):
			self.assertEqual(probe_credentials("Anthropic", "sk")["code"], "UNREACHABLE")

	def test_custom_endpoint_is_honoured(self):
		with patch("requests.get", return_value=self._resp(200, {})) as get:
			probe_credentials("OpenAI", "sk", "https://proxy.example/v1/")
		self.assertEqual(get.call_args[0][0], "https://proxy.example/v1/models")


# ---------------------------------------------------------------------------
# Classifying run failures
# ---------------------------------------------------------------------------


class TestClassification(FrappeTestCase):
	def test_provider_codes_always_count(self):
		self.assertTrue(is_credential_failure("PROVIDER_DISABLED", "AI Model 'x' has no API key set."))
		self.assertTrue(is_credential_failure("PROVIDER_NOT_FOUND", "AI Provider '' not found."))

	def test_http_auth_failures_count(self):
		self.assertTrue(is_credential_failure("FAILED_MODEL_CALL", "401 Client Error: Unauthorized for url: https://api.openai.com/v1/chat/completions"))
		self.assertTrue(is_credential_failure("UNEXPECTED_ERROR", "AuthenticationError: invalid x-api-key"))

	def test_transient_failures_do_not(self):
		self.assertFalse(is_credential_failure("FAILED_MODEL_CALL", "HTTP 529"))
		self.assertFalse(is_credential_failure("TIMEOUT", "Request timed out."))
		self.assertFalse(is_credential_failure("FAILED_MODEL_CALL", "404 Client Error: Not Found for url"))
		self.assertFalse(is_credential_failure("SUCCESS", ""))

	def test_kinds_collapse_run_and_probe_wording(self):
		self.assertEqual(failure_kind("PROVIDER_DISABLED", "AI Model 'x' has no API key set."), "NO_KEY")
		self.assertEqual(failure_kind("NO_KEY", "no API key is set"), "NO_KEY")
		self.assertEqual(failure_kind("INVALID_KEY", "rejected"), "INVALID_KEY")
		self.assertEqual(failure_kind("FAILED_MODEL_CALL", "401 Client Error"), "INVALID_KEY")
		self.assertEqual(failure_kind("PROVIDER_NOT_FOUND", "not found"), "NOT_CONFIGURED")
		self.assertEqual(failure_kind("PROVIDER_DISABLED", "AI Model 'x' is disabled."), "DISABLED")


# ---------------------------------------------------------------------------
# State, blocking and alerting
# ---------------------------------------------------------------------------


class TestHealthState(HealthCase):
	def test_a_credential_failure_blocks_new_runs(self):
		name = self._model()
		self.assertIsNone(refuse_new_run(name))
		note_run_outcome(name, "PROVIDER_DISABLED", f"AI Model '{name}' has no API key set.")
		reason = refuse_new_run(name)
		self.assertIn(name, reason)
		self.assertIn("has no API key set", reason)
		self.assertIn("will be alerted", reason)
		self.assertEqual(self._health(name, "health_refused_runs"), 1)

	def test_a_transient_run_failure_does_not_block(self):
		name = self._model()
		note_run_outcome(name, "TIMEOUT", "Request timed out.")
		note_run_outcome(name, "FAILED_MODEL_CALL", "HTTP 529")
		self.assertIsNone(refuse_new_run(name))
		self.assertEqual(self._health(name, "health_status"), "Healthy")

	def test_a_success_lifts_the_block(self):
		name = self._model()
		record_failure(name, "INVALID_KEY", "rejected")
		self.assertIsNotNone(blocked_reason(name))
		note_run_outcome(name, "SUCCESS", "")
		self.assertIsNone(blocked_reason(name))
		self.assertEqual(self._health(name, "health_failures"), 0)

	def test_a_run_success_on_a_healthy_model_writes_nothing(self):
		name = self._model()  # Healthy from the save probe
		checked = self._health(name, "health_checked_at")
		note_run_outcome(name, "SUCCESS", "")
		self.assertEqual(self._health(name, "health_checked_at"), checked)

	def test_a_run_success_on_an_unknown_model_marks_it_healthy(self):
		name = self._model(probe=_unreachable())  # Unknown
		note_run_outcome(name, "SUCCESS", "")
		self.assertEqual(self._health(name, "health_status"), "Healthy")

	def test_repeated_failures_count_once_per_run(self):
		name = self._model()
		for _ in range(3):
			record_failure(name, "PROVIDER_DISABLED", "no API key set")
		row = self._health(name, "health_failures", "health_problem")
		self.assertEqual(row.health_failures, 3)
		self.assertEqual(row.health_problem, "NO_KEY")

	def test_unknown_model_is_never_blocked(self):
		self.assertIsNone(refuse_new_run("no-such-model-anywhere"))
		self.assertIsNone(refuse_new_run(""))
		self.assertIsNone(refuse_new_run(None))

	def test_bookkeeping_failure_never_raises(self):
		with patch("one_bpmn.agents.model_health.record_failure", side_effect=RuntimeError("boom")):
			note_run_outcome("whatever", "PROVIDER_DISABLED", "x")  # must not raise


def _set_recipients(users):
	"""Replace the Credential Alert Recipients rows on Processa Settings."""
	settings = frappe.get_doc("Processa Settings")
	settings.set("ai_health_alert_recipients", [])
	for user in users:
		settings.append("ai_health_alert_recipients", {"user": user})
	settings.save(ignore_permissions=True)


class TestAlerting(HealthCase):
	def setUp(self):
		super().setUp()
		self._saved_recipients = model_health.configured_recipients()
		_set_recipients([])

	def tearDown(self):
		_set_recipients(self._saved_recipients)
		super().tearDown()

	def _notes(self, model):
		return frappe.get_all(
			"Notification Log",
			filters={"document_type": "AI Model", "document_name": model},
			fields=["for_user", "subject"],
			order_by="creation asc",
		)

	def test_alert_goes_out_once_per_problem(self):
		name = self._model()
		record_failure(name, "PROVIDER_DISABLED", f"AI Model '{name}' has no API key set.")
		with patch("one_bpmn.agents.model_health._send_email"):
			with patch("one_bpmn.agents.model_health.alert_recipients", return_value=["Administrator"]):
				first = alert_unhealthy_models()
				# The same problem seen again by a probe, in the probe's words.
				record_failure(name, "NO_KEY", "no API key is set", source="Probe")
				second = alert_unhealthy_models()
		self.assertIn(name, first)
		self.assertNotIn(name, second)
		self.assertEqual(len(self._notes(name)), 1)
		row = self._health(name, "health_alerted_problem", "health_alerted_at")
		self.assertEqual(row.health_alerted_problem, "NO_KEY")
		self.assertIsNotNone(row.health_alerted_at)
		self.assertIn("was alerted at", blocked_reason(name))

	def test_a_different_problem_is_a_new_alert(self):
		name = self._model()
		record_failure(name, "PROVIDER_DISABLED", f"AI Model '{name}' has no API key set.")
		with patch("one_bpmn.agents.model_health._send_email"):
			with patch("one_bpmn.agents.model_health.alert_recipients", return_value=["Administrator"]):
				alert_unhealthy_models()
				record_failure(name, "INVALID_KEY", "Anthropic rejected the API key (HTTP 401)")
				again = alert_unhealthy_models()
		self.assertIn(name, again)
		self.assertEqual(len(self._notes(name)), 2)

	def test_recovery_tells_the_people_who_were_alerted(self):
		name = self._model()
		record_failure(name, "INVALID_KEY", "rejected")
		with patch("one_bpmn.agents.model_health._send_email"):
			with patch("one_bpmn.agents.model_health.alert_recipients", return_value=["Administrator"]):
				alert_unhealthy_models()
			record_success(name, source="Probe")
		subjects = [n.subject for n in self._notes(name)]
		self.assertEqual(len(subjects), 2)
		self.assertIn("reachable again", subjects[-1])
		self.assertEqual(self._health(name, "health_alerted_problem"), "")

	def test_healthy_models_are_never_alerted(self):
		name = self._model()
		with patch("one_bpmn.agents.model_health._deliver") as deliver:
			alerted = alert_unhealthy_models()
		self.assertNotIn(name, alerted)
		deliver.assert_not_called()

	def test_configured_recipients_win(self):
		name = self._model()
		_set_recipients(["Guest", "Administrator"])
		self.assertEqual(model_health.alert_recipients(name), ["Guest", "Administrator"])

	def test_fallback_skips_administrator_and_lands_on_a_real_user(self):
		name = self._model()
		# Owner and modified_by are Administrator here, which is not a person.
		with patch("one_bpmn.agents.model_health.configured_recipients", return_value=[]), \
			patch("one_bpmn.agents.model_health._is_real_user", side_effect=lambda u: u == "someone@example.com"), \
			patch("frappe.get_all", return_value=["Administrator", "someone@example.com"]):
			self.assertEqual(model_health.alert_recipients(name), ["someone@example.com"])

	def test_old_text_value_is_migrated_to_rows(self):
		"""The field used to be free text. The patch turns each entry that names a
		User into a row and logs the rest, then clears the old value."""
		from one_bpmn.one_bpmn.patches.v1_0.ai_health_recipients_to_users import execute, migrate_text

		_set_recipients([])
		rows, unmatched = migrate_text("Administrator, nobody@example.invalid; Guest")
		self.assertEqual(rows, ["Administrator", "Guest"])
		self.assertEqual(unmatched, ["nobody@example.invalid"])
		self.assertEqual(model_health.configured_recipients(), ["Administrator", "Guest"])
		# Nothing left to migrate: a second run changes nothing.
		execute()
		self.assertEqual(model_health.configured_recipients(), ["Administrator", "Guest"])


# ---------------------------------------------------------------------------
# The scheduled probe
# ---------------------------------------------------------------------------


class TestScheduledProbe(HealthCase):
	def test_probe_marks_and_clears(self):
		name = self._model()
		with patch(PROBE, return_value=_rejected()):
			summary = probe_enabled_models()
		self.assertIn(name, summary["unhealthy"])
		self.assertIsNotNone(blocked_reason(name))
		with patch(PROBE, return_value=_ok()):
			summary = probe_enabled_models()
		self.assertIn(name, summary["healthy"])
		self.assertIsNone(blocked_reason(name))

	def test_unreachable_leaves_status_alone(self):
		name = self._model()
		with patch(PROBE, return_value=_unreachable()):
			summary = probe_enabled_models()
		self.assertIn(name, summary["unreachable"])
		self.assertEqual(self._health(name, "health_status"), "Healthy")

	def test_models_sharing_a_connection_are_probed_once(self):
		a = self._model(key="sk-shared")
		b = self._model(key="sk-shared")
		with patch(PROBE, return_value=_ok()) as probe:
			probe_enabled_models()
		keys = [c[0][1] for c in probe.call_args_list]
		self.assertEqual(keys.count("sk-shared"), 1)
		self.assertEqual(self._health(a, "health_check_source"), "Probe")
		self.assertEqual(self._health(b, "health_check_source"), "Probe")

	def test_disabled_models_are_not_probed(self):
		name = self._model(enabled=0, key="")
		with patch(PROBE, return_value=_ok()) as probe:
			probe_enabled_models()
		self.assertNotIn(name, [c[0] for c in probe.call_args_list])
		self.assertEqual(self._health(name, "health_status"), "Unknown")


# ---------------------------------------------------------------------------
# The gates
# ---------------------------------------------------------------------------


class TestGates(HealthCase):
	def test_invoke_agent_refuses_a_blocked_model_as_a_refusal(self):
		from one_bpmn.api import agent_invocation

		name = self._model()
		record_failure(name, "PROVIDER_DISABLED", f"AI Model '{name}' has no API key set.")
		config = {"agent_id": "probe-agent", "ai_model": name, "agent_type": "Chat", "name": "Probe Agent"}
		with patch.object(agent_invocation, "_resolve_config", return_value=config), \
			patch.object(agent_invocation, "_authorize"), \
			patch("one_bpmn.security.rate_limit.enforce"):
			with self.assertRaises(ModelUnavailable) as ctx:
				agent_invocation.invoke_agent("probe-agent", "hello")
		self.assertIn(name, str(ctx.exception))
		self.assertEqual(self._health(name, "health_refused_runs"), 1)

	def test_model_unavailable_is_an_agent_refusal(self):
		from one_bpmn.security.refusal import AgentRefusal

		self.assertTrue(issubclass(ModelUnavailable, AgentRefusal))

	def test_dispatch_refuses_without_creating_a_run(self):
		"""The dispatcher's gate: task variables carry the refusal, no AI Agent
		Run is created, the executor is never reached."""
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		name = self._model()
		record_failure(name, "INVALID_KEY", "rejected")

		instance = MagicMock()
		instance.context_doctype = ""
		instance.context_docname = ""
		instance.name = "probe-instance"
		instance.initiated_by = "Administrator"
		instance.process_model = ""
		instance._script_task_extensions = {}
		task = MagicMock()
		task.data = {}
		task_cfg = {"aiModel": name, "aiProvider": "Anthropic", "aiSystemPrompt": "s", "aiUserPrompt": "u"}

		runs_before = frappe.db.count("AI Agent Run")
		with patch("one_bpmn.agents.observability.create_ai_run") as create_run, \
			patch("one_bpmn.agents.executor.get_executor") as get_executor:
			try:
				dispatchers.dispatch_ai_agent(instance, task, task_cfg, "probe_task")
			except Exception as exc:  # pragma: no cover - a fixture gap, not the gate
				self.fail(f"dispatch raised before reaching the gate: {exc!r}")
		self.assertEqual(task.data.get("probe_task_error_code"), "PROVIDER_DISABLED")
		self.assertIn(name, task.data.get("probe_task_error_message", ""))
		create_run.assert_not_called()
		get_executor.assert_not_called()
		self.assertEqual(frappe.db.count("AI Agent Run"), runs_before)
