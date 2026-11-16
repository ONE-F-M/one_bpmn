"""Starts, checks and cancels the Cloud Run Job execution that carries one sandbox session."""

import frappe

RUN_API = "https://run.googleapis.com/v2"
SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class SandboxJobError(Exception):
	pass


def start_execution(session_name: str, register_token: str) -> str:
	"""Run the Job once for this session and return the execution name."""
	body = {"overrides": {"containerOverrides": [{"env": [
		{"name": "SESSION_ID", "value": session_name},
		{"name": "SESSION_TOKEN", "value": register_token},
		{"name": "PROCESSA_URL", "value": _processa_url()},
	]}]}}
	data = _call("POST", f"{_job_path()}:run", body)
	name = (data.get("metadata") or {}).get("name") or ""
	if not name:
		raise SandboxJobError("Cloud Run accepted the request but named no execution.")
	return name


def execution_status(execution_name: str) -> dict:
	"""The execution's own record: running, succeeded and failed counts and completion time."""
	return _call("GET", f"/{execution_name}")


def cancel_execution(execution_name: str) -> None:
	_call("POST", f"/{execution_name}:cancel", {})


def _job_path() -> str:
	settings = frappe.get_cached_doc("Processa Settings")
	project, region, job = (settings.get(f) for f in ("sandbox_job_project", "sandbox_job_region", "sandbox_job_name"))
	if not (project and region and job):
		raise SandboxJobError("Processa Settings has no Sandbox Job project, region and name.")
	return f"/projects/{project}/locations/{region}/jobs/{job}"


def _processa_url() -> str:
	url = (frappe.get_cached_doc("Processa Settings").get("sandbox_job_processa_url") or "").strip().rstrip("/")
	url = url or frappe.utils.get_url()
	return "https://" + url[len("http://") :] if url.startswith("http://") else url


def _access_token() -> str:
	from google.auth.transport.requests import Request
	from google.oauth2 import service_account

	key = frappe.get_cached_doc("Processa Settings").get_password("agent_sandbox_caller_key", raise_exception=False)
	if not key:
		raise SandboxJobError("Processa Settings has no Sandbox Caller Key, so the Job cannot be started.")
	credentials = service_account.Credentials.from_service_account_info(frappe.parse_json(key), scopes=[SCOPE])
	credentials.refresh(Request())
	return credentials.token


def _call(method: str, path: str, body: dict | None = None) -> dict:
	import requests

	response = requests.request(
		method, f"{RUN_API}{path}", json=body, timeout=30, headers={"Authorization": f"Bearer {_access_token()}"}
	)
	if response.status_code >= 400:
		raise SandboxJobError(f"Cloud Run answered {response.status_code}: {response.text[:300]}")
	return response.json() if response.content else {}
