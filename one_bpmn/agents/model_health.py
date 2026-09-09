# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Credential health for AI Models (WI-002191).

WHY THIS EXISTS
---------------
In July an unset API key on Docu's model stayed broken for four days. Every
message a user sent produced one more failed AI Agent Run carrying the same
PROVIDER_DISABLED text, nobody was told, and the people retrying had no way to
know the wall they were hitting was configuration rather than luck.

Three things close that gap, and they share one set of read-only fields on the
``AI Model`` record itself (``health_*``), written only by the platform:

1. **Validate on save.** An enabled ``AI Model`` needs a key and a provider, and
   a changed key is tried against the provider before the save is accepted.
   Listing the provider's models is free, takes no tokens, and fails exactly
   when the key is wrong.
2. **Notice a failure and say so once.** A run that dies for a credential
   reason marks the model Unhealthy; a scheduled job every fifteen minutes
   re-checks every enabled model and alerts the responsible people once per
   distinct problem, never once per failed run.
3. **Stop paying for known failures.** While a model is Unhealthy, new runs on
   it are refused up front with a message that says what is wrong and that
   somebody has been told. A successful probe (or a successful run) lifts the
   block — the person who fixes the key does not have to do anything else.

WHAT IS AND IS NOT A CREDENTIAL FAILURE
---------------------------------------
Only outcomes that mean "this model cannot work until someone edits its
record" count: no key, a rejected key, a provider name that routes nowhere, a
disabled model still being dispatched. A timeout, a 5xx or a rate limit is the
provider having a bad minute, and treating that as broken credentials would
block a working model on a transient — so those never mark a model Unhealthy
and never alert. They are recorded on the row as the last check and nothing
more.
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.utils import cint, now_datetime
from frappe.utils.password import get_decrypted_password

from one_bpmn.security.refusal import AgentRefusal

# The health fields live on AI Model. Written with update_modified=False so a
# platform write never overwrites who last EDITED the model — that person is
# the alert's fallback recipient.
MODEL_DOCTYPE = "AI Model"

# How long a probe waits for the provider's model list. Long enough for a slow
# API, short enough that a Desk save does not hang.
PROBE_TIMEOUT_SECONDS = 15

# Executor error codes that always mean credentials/configuration.
CREDENTIAL_ERROR_CODES = frozenset({"PROVIDER_DISABLED", "PROVIDER_NOT_FOUND"})

# Probe outcomes that mean the same thing.
CREDENTIAL_PROBE_CODES = frozenset({"NO_KEY", "INVALID_KEY", "NO_DIALECT", "NO_PROVIDER"})

# A FAILED_MODEL_CALL is a credential failure only when the provider said so.
# requests phrases a raise_for_status() as "401 Client Error: Unauthorized for
# url: ..."; the SDK adapters surface the provider's own error type.
_AUTH_MESSAGE = re.compile(
	r"\b40[13]\b|unauthori[sz]ed|forbidden|authentication[_ ]error|invalid[ _-]?(x-)?api[ _-]?key"
	r"|incorrect api key|permission[_ ]denied|api key not valid",
	re.IGNORECASE,
)

# The kinds of problem a person can be told about. One alert per kind per
# model: a run and a probe describe the same missing key in different words,
# and that must not read as two incidents.
_KIND_NO_KEY = "NO_KEY"
_KIND_INVALID_KEY = "INVALID_KEY"
_KIND_NOT_CONFIGURED = "NOT_CONFIGURED"
_KIND_DISABLED = "DISABLED"


class ModelUnavailable(AgentRefusal):
	"""A turn was refused because its model's credentials are known to be broken.

	An :class:`AgentRefusal`, so every surface that already treats a refusal as
	a decision rather than a fault shows this message verbatim instead of a
	reference id — and the engine does not mark the instance Errored.
	"""


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def is_credential_failure(error_code: str | None, error_message: str | None) -> bool:
	"""Did this run fail because of the model's credentials or configuration?"""
	code = (error_code or "").strip()
	if code in CREDENTIAL_ERROR_CODES:
		return True
	if code in ("FAILED_MODEL_CALL", "UNEXPECTED_ERROR"):
		return bool(_AUTH_MESSAGE.search(error_message or ""))
	return False


def failure_kind(code: str | None, message: str | None) -> str:
	"""Collapse an error into the handful of kinds worth alerting on separately."""
	code = (code or "").strip()
	text = (message or "").lower()
	if code == "NO_KEY" or "no api key" in text:
		return _KIND_NO_KEY
	if code in ("NO_DIALECT", "NO_PROVIDER", "PROVIDER_NOT_FOUND"):
		return _KIND_NOT_CONFIGURED
	if code == "PROVIDER_DISABLED" and "is disabled" in text:
		return _KIND_DISABLED
	return _KIND_INVALID_KEY


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------


def probe_credentials(
	provider: str | None, api_key: str | None, endpoint: str | None = "", timeout: int | None = None
) -> dict:
	"""Try a key against its provider without spending a token.

	Lists the provider's models — the cheapest authenticated call each API
	offers. Returns ``{"ok", "code", "detail"}`` where ``code`` is one of
	``OK``, ``NO_PROVIDER``, ``NO_DIALECT``, ``NO_KEY``, ``INVALID_KEY``,
	``PROVIDER_ERROR`` or ``UNREACHABLE``. Never raises.
	"""
	from one_bpmn.agents.executor.direct_api import DirectApiExecutor

	provider = (provider or "").strip()
	if not provider:
		return {
			"ok": False,
			"code": "NO_PROVIDER",
			"detail": _("the model names no AI Provider, so nothing can route a call to it"),
		}
	dialect = DirectApiExecutor._DIALECTS.get(provider.lower())
	if not dialect:
		return {
			"ok": False,
			"code": "NO_DIALECT",
			"detail": _(
				"AI Provider '{0}' is not a dialect the platform can speak — name the "
				"provider Anthropic, OpenAI or Google"
			).format(provider),
		}
	if not (api_key or "").strip():
		return {"ok": False, "code": "NO_KEY", "detail": _("no API key is set")}

	base = (endpoint or "").strip().rstrip("/") or DirectApiExecutor._DEFAULT_ENDPOINTS.get(dialect, "")
	if dialect == "Anthropic":
		url = f"{base}/v1/models?limit=1"
		headers = {
			"x-api-key": api_key,
			"anthropic-version": DirectApiExecutor._ANTHROPIC_API_VERSION,
		}
	elif dialect == "OpenAI":
		url = f"{base}/models"
		headers = {"Authorization": f"Bearer {api_key}"}
	else:
		url = f"{base}/models?pageSize=1"
		headers = {"x-goog-api-key": api_key}

	import requests

	timeout = timeout or PROBE_TIMEOUT_SECONDS
	try:
		resp = requests.get(url, headers=headers, timeout=timeout)
	except requests.Timeout:
		return {
			"ok": False,
			"code": "UNREACHABLE",
			"detail": _("{0} did not answer within {1} seconds").format(dialect, timeout),
		}
	except requests.RequestException as exc:
		return {"ok": False, "code": "UNREACHABLE", "detail": str(exc)[:200]}

	if resp.status_code in (401, 403):
		return {
			"ok": False,
			"code": "INVALID_KEY",
			"detail": _("{0} rejected the API key (HTTP {1}): {2}").format(
				dialect, resp.status_code, _error_text(resp)
			),
		}
	if resp.status_code >= 400:
		return {
			"ok": False,
			"code": "PROVIDER_ERROR",
			"detail": _("{0} answered HTTP {1}: {2}").format(dialect, resp.status_code, _error_text(resp)),
		}
	return {"ok": True, "code": "OK", "detail": _("{0} accepted the API key").format(dialect)}


def _error_text(resp) -> str:
	"""The provider's own words for what went wrong, bounded."""
	try:
		body = resp.json()
		err = body.get("error") if isinstance(body, dict) else None
		if isinstance(err, dict):
			return str(err.get("message") or err.get("type") or err)[:160]
		if err:
			return str(err)[:160]
	except Exception:
		pass
	return (resp.text or "")[:160].strip()


def probe_model(model: str, timeout: int | None = None) -> dict:
	"""Probe a stored model's own credentials. Same result shape as
	:func:`probe_credentials`."""
	row = frappe.db.get_value(
		"AI Model", model, ["provider", "api_endpoint", "enable_model"], as_dict=True
	)
	if not row:
		return {"ok": False, "code": "NOT_FOUND", "detail": _("AI Model '{0}' does not exist").format(model)}
	key = get_decrypted_password("AI Model", model, "api_key", raise_exception=False) or ""
	return probe_credentials(row.provider, key, row.api_endpoint, timeout=timeout)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_HEALTH_FIELDS = [
	"name",
	"health_status",
	"health_check_source",
	"health_checked_at",
	"health_ok_at",
	"health_error_code",
	"health_error_message",
	"health_failures",
	"health_problem",
	"health_alerted_at",
	"health_alerted_problem",
	"health_alerted_to",
	"health_refused_runs",
]


def health_row(model: str | None) -> dict | None:
	"""The model's health fields, or None when the model does not exist."""
	if not model:
		return None
	return frappe.db.get_value(MODEL_DOCTYPE, model, _HEALTH_FIELDS, as_dict=True)


def _write(model: str, values: dict) -> bool:
	"""Write health fields without touching modified/modified_by. False when
	the model no longer exists."""
	if not frappe.db.exists(MODEL_DOCTYPE, model):
		return False
	frappe.db.set_value(MODEL_DOCTYPE, model, values, update_modified=False)
	return True


def record_failure(model: str | None, code: str, detail: str | None, source: str = "Run") -> None:
	"""Mark a model Unhealthy for a credential reason. Idempotent per problem:
	a second identical failure only bumps the counter."""
	if not model:
		return
	existing = health_row(model)
	if not existing:
		return
	_write(
		model,
		{
			"health_status": "Unhealthy",
			"health_check_source": source,
			"health_checked_at": now_datetime(),
			"health_error_code": (code or "")[:140],
			"health_error_message": (detail or "")[:1000],
			"health_problem": failure_kind(code, detail),
			"health_failures": cint(existing.health_failures) + 1,
		},
	)


def record_success(model: str | None, source: str = "Run") -> None:
	"""Mark a model Healthy.

	A successful run on a model that is already Healthy writes nothing — that
	would be a write per run for no reader. A probe or a save always writes, so
	the record shows when it was last checked.
	"""
	if not model:
		return
	existing = health_row(model)
	if not existing:
		return
	if source == "Run" and existing.health_status == "Healthy":
		return
	now = now_datetime()
	values = {
		"health_status": "Healthy",
		"health_check_source": source,
		"health_checked_at": now,
		"health_ok_at": now,
		"health_error_code": "",
		"health_error_message": "",
		"health_problem": "",
		"health_failures": 0,
	}
	was_alerted = existing.health_status == "Unhealthy" and bool(existing.health_alerted_problem)
	if was_alerted:
		# The problem is over; the next one starts a fresh alert cycle.
		values["health_alerted_problem"] = ""
	if not _write(model, values):
		return
	if was_alerted:
		_notify_recovery(model, existing)


def record_transient(model: str | None, code: str, detail: str | None, source: str = "Probe") -> None:
	"""A check that proved nothing either way — the provider was unreachable or
	answered with a server error. Recorded so the record shows when it was
	last looked at, without changing its status."""
	if not model:
		return
	_write(
		model,
		{
			"health_check_source": source,
			"health_checked_at": now_datetime(),
			"health_error_code": (code or "")[:140],
			"health_error_message": (detail or "")[:1000],
		},
	)


def clear_health(model: str | None) -> None:
	"""A model that was switched off is not a health problem. It goes back to
	Unknown so a later re-enable starts clean, and nothing blocks on it."""
	if not model:
		return
	_write(
		model,
		{
			"health_status": "Unknown",
			"health_problem": "",
			"health_alerted_problem": "",
			"health_failures": 0,
		},
	)


def note_run_outcome(model: str | None, error_code: str | None, error_message: str | None) -> None:
	"""Fold a finished run into the model's health. Called from
	``finalize_ai_run``; never raises, because a bookkeeping failure must not
	fail the run it is about."""
	if not model:
		return
	try:
		if (error_code or "") == "SUCCESS":
			record_success(model, source="Run")
		elif is_credential_failure(error_code, error_message):
			record_failure(model, error_code or "", error_message, source="Run")
	except Exception:
		frappe.log_error(
			title="AI Model Health: could not record run outcome", message=frappe.get_traceback()
		)


# ---------------------------------------------------------------------------
# Refusing new runs
# ---------------------------------------------------------------------------


def blocked_reason(model: str | None) -> str | None:
	"""Why a new run on *model* must not start right now, or None."""
	row = health_row(model)
	if not row or row.health_status != "Unhealthy":
		return None
	if row.health_alerted_at:
		told = _("An administrator was alerted at {0}.").format(
			frappe.utils.format_datetime(row.health_alerted_at)
		)
	else:
		told = _("An administrator will be alerted within fifteen minutes.")
	return _(
		"AI Model '{0}' is unavailable: {1} New runs on it are paused until its "
		"credentials are fixed and the next check passes. {2}"
	).format(model, _sentence(row.health_error_message), told)


def refuse_new_run(model: str | None) -> str | None:
	"""The dispatch-time gate. Returns the refusal text and counts the run it
	prevented, or None when the model may be used."""
	reason = blocked_reason(model)
	if reason:
		_count_suppressed(model)
	return reason


def _count_suppressed(model: str) -> None:
	Model = DocType(MODEL_DOCTYPE)
	try:
		(
			frappe.qb.update(Model)
			.set(Model.health_refused_runs, Model.health_refused_runs + 1)
			.where(Model.name == model)
			.run()
		)
	except Exception:
		pass


def _sentence(text: str | None) -> str:
	text = (text or "").strip() or _("its provider rejected the credentials")
	return text if text.endswith((".", "!", "?")) else text + "."


# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------


def alert_recipients(model: str) -> list[str]:
	"""Who is told. The users picked on Processa Settings first; else whoever
	last edited the model, because they know where its key came from; else
	every enabled System Manager."""
	users = _dedupe(configured_recipients())
	if users:
		return users

	who = frappe.db.get_value("AI Model", model, ["modified_by", "owner"], as_dict=True) or {}
	for user in (who.get("modified_by"), who.get("owner")):
		if _is_real_user(user):
			return [user]

	managers = frappe.get_all(
		"Has Role", filters={"role": "System Manager", "parenttype": "User"}, pluck="parent"
	)
	return _dedupe(u for u in managers if _is_real_user(u))


def configured_recipients() -> list[str]:
	"""The Credential Alert Recipients rows on Processa Settings, in order."""
	return frappe.get_all(
		"User Group Member",
		filters={
			"parenttype": "Processa Settings",
			"parent": "Processa Settings",
			"parentfield": "ai_health_alert_recipients",
		},
		pluck="user",
		order_by="idx asc",
	)


def _is_real_user(user: str | None) -> bool:
	if not user or user in ("Administrator", "Guest"):
		return False
	return bool(frappe.db.get_value("User", user, "enabled"))


def _dedupe(items) -> list[str]:
	seen, out = set(), []
	for item in items:
		if item not in seen:
			seen.add(item)
			out.append(item)
	return out


def alert_unhealthy_models() -> list[str]:
	"""Scheduler (after the probe, every fifteen minutes): tell someone about
	each Unhealthy model whose current problem has not been announced yet.
	Returns the models alerted."""
	rows = frappe.get_all(
		MODEL_DOCTYPE,
		filters={"health_status": "Unhealthy"},
		fields=[
			"name",
			"health_problem",
			"health_alerted_problem",
			"health_error_code",
			"health_error_message",
			"health_failures",
			"health_refused_runs",
			"health_check_source",
		],
	)
	alerted = []
	for row in rows:
		if row.health_problem and row.health_problem == row.health_alerted_problem:
			continue
		recipients = alert_recipients(row.name)
		subject = _("AI Model '{0}' cannot reach its provider").format(row.name)
		body = _alert_body(row)
		told = _deliver(recipients, subject, body, row.name)
		_write(
			row.name,
			{
				"health_alerted_problem": row.health_problem
				or failure_kind(row.health_error_code, row.health_error_message),
				"health_alerted_at": now_datetime(),
				"health_alerted_to": ", ".join(told),
			},
		)
		alerted.append(row.name)
		if not told:
			frappe.logger("one_bpmn").warning(
				f"AI Model Health: '{row.name}' is unhealthy and nobody could be alerted — "
				"set Credential Alert Recipients in Processa Settings."
			)
	return alerted


def _model_link(model: str) -> str:
	"""The AI Model record as a link the reader can click from the email."""
	url = frappe.utils.get_url_to_form("AI Model", model)
	return f'<a href="{url}">{frappe.utils.escape_html(model)}</a>'


def _alert_body(row) -> str:
	lines = [
		_("Every run on <b>{0}</b> is failing for a credential reason.").format(_model_link(row.name)),
		"",
		_("What the provider said: {0}").format(frappe.utils.escape_html(row.health_error_message or "")),
		_("Seen by: {0} · consecutive failures: {1} · runs refused so far: {2}").format(
			row.health_check_source or "Run", cint(row.health_failures), cint(row.health_refused_runs)
		),
		"",
		_(
			"Open the AI Model record {0}, enter or replace its API key, and save. The save "
			"checks the key with the provider; once it passes, runs resume on their own."
		).format(_model_link(row.name)),
	]
	return "<br>".join(lines)


def _deliver(recipients: list[str], subject: str, body: str, model: str) -> list[str]:
	"""In-app alert plus an email, to each recipient. Returns who got the in-app
	alert. Never raises."""
	told = []
	for user in recipients:
		try:
			note = frappe.new_doc("Notification Log")
			note.for_user = user
			note.type = "Alert"
			note.subject = subject
			note.email_content = body
			note.document_type = "AI Model"
			note.document_name = model
			note.insert(ignore_permissions=True)
			told.append(user)
		except Exception:
			frappe.log_error(title="AI Model Health: in-app alert failed", message=frappe.get_traceback())
	if told:
		try:
			_send_email(told, subject, body)
		except Exception:
			frappe.log_error(title="AI Model Health: alert email failed", message=frappe.get_traceback())
	return told


def _send_email(recipients: list[str], subject: str, body: str) -> None:
	try:
		from one_fm.processor import sendemail

		sendemail(recipients=recipients, subject=subject, message=body, is_external_mail=True)
	except ImportError:
		frappe.sendmail(recipients=recipients, subject=subject, message=body)


def _notify_recovery(model: str, previous: dict) -> None:
	"""Close the loop for the people who were alerted."""
	users = [u.strip() for u in (previous.get("health_alerted_to") or "").split(",") if u.strip()]
	if not users:
		return
	subject = _("AI Model '{0}' is reachable again").format(model)
	body = _(
		"The credentials of {0} passed the check at {1}. Runs on this model have resumed."
	).format(_model_link(model), frappe.utils.format_datetime(now_datetime()))
	_deliver(users, subject, body, model)


# ---------------------------------------------------------------------------
# Scheduled probe
# ---------------------------------------------------------------------------


def probe_enabled_models(timeout: int | None = None) -> dict:
	"""Scheduler: check every enabled model's credentials.

	Models sharing one key and endpoint are probed once — since the connection
	moved onto the model, one Anthropic key typically sits on six rows, and six
	identical calls every cycle would say nothing the first did not.
	"""
	models = frappe.get_all(
		"AI Model", filters={"enable_model": 1}, fields=["name", "provider", "api_endpoint"]
	)
	summary = {"healthy": [], "unhealthy": [], "unreachable": []}
	by_connection: dict[tuple, dict] = {}
	for row in models:
		key = get_decrypted_password("AI Model", row.name, "api_key", raise_exception=False) or ""
		conn = ((row.provider or "").strip().lower(), (row.api_endpoint or "").strip(), key)
		if conn not in by_connection:
			by_connection[conn] = probe_credentials(row.provider, key, row.api_endpoint, timeout=timeout)
		result = by_connection[conn]
		if result["ok"]:
			record_success(row.name, source="Probe")
			summary["healthy"].append(row.name)
		elif result["code"] in CREDENTIAL_PROBE_CODES:
			record_failure(row.name, result["code"], result["detail"], source="Probe")
			summary["unhealthy"].append(row.name)
		else:
			record_transient(row.name, result["code"], result["detail"], source="Probe")
			summary["unreachable"].append(row.name)
	return summary
