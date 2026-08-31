# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The Dev Agent Sandbox connector's dispatch operation.

Mirrors a2a_client_ops.delegate_to_local_agent's parking shape (WI-001933),
but the "remote" here is not another local agent or an A2A-protocol remote —
it is an external Cloud Run service that clones an app into a disposable
sandbox, runs its real test suite, and calls back with the result. That
difference is why this tracks its own "Agent Sandbox Run" doctype
instead of an A2A Task: forcing an HTTP service with a bespoke JSON contract
through the A2A Remote Agent abstraction would misrepresent what it is.

A Handler Path connector, not a declarative HTTP Request one: the sandbox is
deployed IAM-protected (no --allow-unauthenticated), so every call needs a
freshly minted, short-lived Google identity token — something a static
Jinja-templated secret cannot produce. See the "Dev Agent Sandbox" BPMN
Connector's own record for why that trade was made over a no-code
HTTP Request operation.

The sandbox is the coding agent: it does its own reading, writing, and
testing, in its own bounded tool-calling loop, against the model it was
told to use — and on a pass, it opens the pull request itself, directly
against GitHub, rather than handing files back for Processa to deliver.
Nothing about any of that behavior is baked into the sandbox's own code —
``agent_config`` (system_prompt, model, a live API key) and ``github_token``
are both resolved fresh here, from the "Dev Agent" AI Agent Configuration
(and its linked AI Model) and Processa Settings respectively, on every
dispatch, and handed over in the request body. Sending live credentials in
the dispatch payload (rather than static secrets baked into the sandbox's
own deployment) is a deliberate trade: it means Processa keeps full,
per-dispatch control over which model, credential, and GitHub token a run
uses — no sandbox redeploy needed to change any of them — at the cost of a
short-lived exposure of those values to the sandbox's own process memory
for the life of one run. The channel is the same Cloud-Run-IAM-authenticated
HTTPS call every other dispatch already uses.
"""

from __future__ import annotations

import frappe

AGENT_SANDBOX_WAITING_KEY = "_bpmn_agent_sandbox_waiting"
_AGENT_CONFIG_NAME = "Dev Agent"


class AgentSandboxError(Exception):
	"""Raised for a dispatch failure the model should be told about plainly,
	rather than one dispatch_connector's generic handler swallows silently."""


def target_app_choices() -> list[str]:
	"""Dropdown source: every app actually installed on this bench — the
	sandbox clones from this same list, so an app that doesn't exist here
	can't be picked in the first place."""
	return frappe.get_installed_apps()


def dispatch(params: dict, ctx: dict) -> dict | None:
	"""Dispatch a development work order to the Cloud Run sandbox.

	Returns None after parking the Service Task — a real sandbox run (clone,
	install, test) takes minutes, never seconds, so there is no fast path
	that answers inline the way a quick HTTP call might.
	"""
	instance = ctx.get("instance")
	task = ctx.get("task")

	target_app = (params.get("target_app") or "").strip()
	if not target_app:
		raise AgentSandboxError("dispatch_to_sandbox needs a target_app to clone and test.")

	git_branch = (params.get("git_branch") or "").strip()
	if not git_branch:
		raise AgentSandboxError("dispatch_to_sandbox needs a git_branch to start the work from.")

	work_item_description = (params.get("work_item_description") or "").strip()
	if not work_item_description:
		raise AgentSandboxError("dispatch_to_sandbox needs a work_item_description — the work order itself.")

	settings = frappe.get_cached_doc("Processa Settings")
	sandbox_url = (settings.agent_sandbox_url or "").strip().rstrip("/")
	if not sandbox_url:
		raise AgentSandboxError(
			"Processa Settings has no Sandbox URL configured — the Dev Agent has nowhere to dispatch to."
		)

	run = frappe.get_doc({
		"doctype": "Agent Sandbox Run",
		"state": "submitted",
		"target_app": target_app,
		"git_branch": git_branch,
		"bpmn_id": _bpmn_id(task),
		"caller_instance": getattr(instance, "name", None),
		"caller_wf_task_id": _caller_task_id(task),
		"work_item_description": work_item_description,
	})
	run.insert(ignore_permissions=True)

	try:
		agent_config = _resolve_agent_config()
	except AgentSandboxError:
		run.db_set({"state": "failed", "error_message": "Could not resolve a usable model/credential."}, update_modified=False)
		raise

	github_token = settings.get_password("github_token", raise_exception=False) or ""
	if not github_token:
		run.db_set({"state": "failed", "error_message": "No GitHub token configured — cannot deliver a PR."}, update_modified=False)
		raise AgentSandboxError(
			"Processa Settings has no GitHub token configured — the sandbox needs one to open the pull request itself."
		)

	payload = {
		"correlation_id": run.name,
		"target_app": target_app,
		"git_branch": git_branch,
		"work_item_description": work_item_description,
		"agent_config": agent_config,
		"github_token": github_token,
		"callback_url": _callback_url(),
	}
	# request_payload is a plain Code field rendered in the desk UI — never
	# park a live credential there. Audit the shape of what was sent, not the
	# credentials themselves; the real payload (below) still carries them.
	audit_payload = {**payload, "agent_config": {**agent_config, "api_key": "REDACTED"}, "github_token": "REDACTED"}
	run.db_set("request_payload", frappe.as_json(audit_payload), update_modified=False)

	try:
		token = _mint_identity_token(sandbox_url)
	except Exception:
		frappe.log_error(
			title=f"Dev Agent Sandbox: identity token minting failed ({run.name})",
			message=frappe.get_traceback(),
		)
		run.db_set({"state": "failed", "error_message": "Could not authenticate to the sandbox."}, update_modified=False)
		raise AgentSandboxError("Could not authenticate to the sandbox — check the service account configuration.")

	try:
		import requests

		response = requests.post(
			f"{sandbox_url}/run",
			json=payload,
			headers={"Authorization": f"Bearer {token}"},
			timeout=30,
		)
		response.raise_for_status()
	except Exception as exc:
		frappe.log_error(
			title=f"Dev Agent Sandbox: dispatch failed ({run.name})",
			message=frappe.get_traceback(),
		)
		run.db_set({"state": "failed", "error_message": str(exc)[:500]}, update_modified=False)
		raise AgentSandboxError(f"The sandbox rejected the dispatch: {exc}")

	run.db_set("state", "running", update_modified=False)

	# Park exactly as the a2a connector does, so one resume seam pattern
	# serves both — but this waiting marker is our own, never confused with
	# a delegation waiting on another agent.
	if task is not None:
		task.data[AGENT_SANDBOX_WAITING_KEY] = {
			"run": run.name,
			"label": f"Dispatched {target_app}@{git_branch} to the Dev Agent sandbox",
		}
	return None


def _resolve_agent_config() -> dict:
	"""Everything the sandbox needs to actually be the coding agent for this
	run — resolved fresh from the "Dev Agent" configuration on every dispatch,
	never cached into the sandbox's own code or deployment. Mirrors the exact
	resolution path agents/executor/direct_api.py uses for every other
	in-process ai_agent call: AI Provider holds a name and nothing else (it is
	just the dialect tag), so the credential and enable flag both live on
	AI Model itself (AI Agent Configuration.ai_model -> AI Model.enable_model /
	.api_key), not on AI Provider — a credential rotation or a model change
	here needs no separate wiring, it is the same credential store as
	everything else."""
	cfg = frappe.get_cached_doc("AI Agent Configuration", _AGENT_CONFIG_NAME)
	model_name = (cfg.ai_model or "").strip()
	if not model_name:
		raise AgentSandboxError(f'"{_AGENT_CONFIG_NAME}" has no ai_model configured.')

	meta = frappe.db.get_value(
		"AI Model", model_name, ["enable_model", "model_api_name"], as_dict=True
	)
	if not meta:
		raise AgentSandboxError(f"AI Model {model_name!r} does not exist.")
	if not meta.enable_model:
		raise AgentSandboxError(f"AI Model {model_name!r} is disabled.")

	api_key = frappe.utils.password.get_decrypted_password(
		"AI Model", model_name, "api_key", raise_exception=False
	) or ""
	if not api_key:
		raise AgentSandboxError(f"AI Model {model_name!r} has no api_key configured.")

	return {
		"system_prompt": cfg.system_prompt or "",
		"model": meta.model_api_name or model_name,
		"api_key": api_key,
	}


def _callback_url() -> str:
	return frappe.utils.get_url("/api/method/one_bpmn.api.agent_callback.report_result")


def _mint_identity_token(audience: str) -> str:
	"""A fresh, short-lived Google-signed identity token for this exact
	Cloud Run service — never a static secret. The signing key is the full
	GCP service account JSON stored in Processa Settings' Sandbox Caller Key
	(that service account needs the Cloud Run Invoker role on the sandbox
	service) — resolved fresh here, same as agent_config and github_token,
	rather than a file path on the local bench host."""
	from google.auth.transport.requests import Request as GoogleAuthRequest
	from google.oauth2 import service_account

	settings = frappe.get_cached_doc("Processa Settings")
	key_json = settings.get_password("agent_sandbox_caller_key", raise_exception=False)
	if not key_json:
		raise AgentSandboxError(
			"Processa Settings has no Sandbox Caller Key configured — cannot authenticate to the sandbox."
		)
	try:
		key_info = frappe.parse_json(key_json)
	except Exception as exc:
		raise AgentSandboxError(f"Sandbox Caller Key is not valid JSON: {exc}") from exc

	credentials = service_account.IDTokenCredentials.from_service_account_info(
		key_info, target_audience=audience
	)
	credentials.refresh(GoogleAuthRequest())
	return credentials.token


def _caller_task_id(task) -> str | None:
	"""The SpiffWorkflow id of the step to wake, or None when there is no
	step — mirrors a2a_client_ops._caller_task_id exactly, same reasoning."""
	task_id = getattr(task, "id", None) if task is not None else None
	return str(task_id) if task_id else None


def _bpmn_id(task) -> str | None:
	if task is None:
		return None
	spec = getattr(task, "task_spec", None)
	return getattr(spec, "bpmn_id", None) or getattr(spec, "name", None)
