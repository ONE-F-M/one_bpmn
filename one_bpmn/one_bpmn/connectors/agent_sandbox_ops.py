# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The Dev Agent Sandbox connector's operations: sandbox_dispatch (the bare
HTTP primitive for the fast, synchronous file-op tools) and dispatch_action
(one generic handler serving every slow, parked operation — currently
run_tests and open_pull_request).

Each of the six sandbox tools (read_file, write_file, edit_file, list_files,
run_tests, open_pull_request) is its own real, directly-callable BPMN shape
inside the Dev Agent's dev_agent_tools ad-hoc sub-process — matching how the
Orchestrator Agent's own tools are real Script/Service Tasks, not
schema-only declarations. All the reasoning (which tool to call, with what
arguments) happens once, in Processa's own AI Agent Task; nothing here ever
sees a model name or an LLM API key. Execution of the action itself always
happens sandbox-side, against its own isolated clone of the target app —
nothing here reads or writes app files or talks to GitHub's Contents API
directly.

Two dispatch shapes, chosen by how long the action takes:
- read_file/write_file/edit_file/list_files call sandbox_dispatch(), a fast,
  synchronous round trip to the sandbox's /tool_call endpoint — these
  answer inline within one request.
- run_tests/open_pull_request are two named Connector Operations that both
  point at dispatch_action(), which reads which one it was configured as
  (ctx["operation"]) and forwards that as the action to
  _dispatch_single_action() — parking the calling Service Task and waiting
  for an async callback (api/agent_callback.py) once the sandbox is done.
  These are minutes-scale (a real test suite run, or a
  re-test-then-push-then-open-PR), so nothing here holds a request open
  that long. One shared handler means a new slow sandbox action only needs
  a new BPMN Connector Operation record naming this same handlerPath — no
  new Python function.

Every call needs a freshly minted, short-lived Google identity token — the
sandbox is deployed IAM-protected (no --allow-unauthenticated), so a static
Jinja-templated secret cannot authenticate it. See the "Dev Agent Sandbox"
BPMN Connector's own record for why a Handler Path connector was chosen
over a no-code HTTP Request operation.
"""

from __future__ import annotations

import re
import frappe

AGENT_SANDBOX_WAITING_KEY = "_bpmn_agent_sandbox_waiting"


class AgentSandboxError(Exception):
	"""Raised for a dispatch failure the model should be told about plainly,
	rather than one dispatch_connector's generic handler swallows silently."""


_SANDBOX_ONLY_TARGET_APPS = ["mobile_app_ionic", "one_lms"]
"""target_app values the sandbox clones and can run against but that never
appear in frappe.get_installed_apps() here. mobile_app_ionic has no
hooks.py, so bench install-app fails on it outright — it's a standalone
Vue/Ionic/Capacitor project, cloned into the sandbox's apps/ purely to be
a coding-loop target, never installed onto any site. one_lms is a real
Frappe app the sandbox installs, but this bench itself doesn't have it —
kept as an explicit list rather than assuming this bench's install state
always mirrors the sandbox's clone set."""


def target_app_choices() -> list[str]:
	"""Dropdown source: every app the sandbox can actually target — apps
	installed on this bench (the sandbox clones the same set) plus the
	sandbox-only apps above that this bench's install state can't surface
	on its own."""
	return frappe.get_installed_apps() + _SANDBOX_ONLY_TARGET_APPS


_WORK_ITEM_ID = re.compile(r"\bWI-\d+\b")


def work_item_id_for(a2a_task: str | None) -> str:
	"""The Work Item behind an A2A delegation, so the sandbox can name its branch
	after it. Prefers the Agent Delegation's reference, then an id written into
	the instruction; "" when there is neither."""
	if not a2a_task:
		return ""
	ref = frappe.db.get_value(
		"Agent Delegation", {"a2a_task": a2a_task}, ["reference_doctype", "reference_name"], as_dict=True
	)
	if ref and ref.reference_doctype == "Work Item" and ref.reference_name:
		return ref.reference_name
	payload = frappe.db.get_value("A2A Task", a2a_task, "request_payload") or ""
	match = _WORK_ITEM_ID.search(payload)
	return match.group(0) if match else ""


def _a2a_task_of(instance) -> str | None:
	if getattr(instance, "context_doctype", None) == "A2A Task":
		return getattr(instance, "context_docname", None)
	return None


def sandbox_dispatch(action: str, target_app: str, git_branch: str, work_item_description: str,
                      args: dict, a2a_task: str | None = None) -> dict:
	"""The bare primitive the Sandbox Tool Server Scripts (Sandbox Tool:
	Read File / Write File / Edit File / List Files) call — one fast,
	synchronous HTTP round trip to the sandbox's own /tool_call endpoint,
	executed there against the target app's working tree.

	Deliberately as thin as frontend/primitives.py's own functions: this
	holds no tool policy (that lives in the calling Server Script, visible
	and editable without a deploy — see that module's own docstring for the
	same reasoning) — it exists only because Server Scripts cannot import
	requests/socket/urllib themselves (security/script_validator.py's
	FORBIDDEN_MODULES). It resolves settings, mints the identity token,
	makes the one call, and reports what happened.

	NEVER RAISES — every path returns {"ok": True, "response": <the
	sandbox's own JSON>} or {"ok": False, "error": "..."}, matching
	frontend/primitives.py's own discipline (an exception here would end
	the calling tool's turn rather than informing it).

	No parking: unlike dispatch_action's run_tests/open_pull_request, these are
	seconds-scale (a git fetch against an already-locally-cloned repo, plus
	a local file read/write and — for write/edit — a commit+push), not
	minutes-scale, so there's nothing here worth suspending the caller's
	turn over."""
	settings = frappe.get_cached_doc("Processa Settings")
	sandbox_url = (settings.agent_sandbox_url or "").strip().rstrip("/")
	if not sandbox_url:
		return {"ok": False, "error": "Processa Settings has no Sandbox URL configured."}
	github_token = settings.get_password("github_token", raise_exception=False) or ""
	if not github_token:
		return {"ok": False, "error": "Processa Settings has no GitHub token configured."}

	try:
		token = _mint_identity_token(sandbox_url)
	except Exception as exc:
		frappe.log_error(title=f"Dev Agent Sandbox: {action} auth failed", message=frappe.get_traceback())
		return {"ok": False, "error": f"Could not authenticate to the sandbox: {exc}"}

	try:
		import requests

		response = requests.post(
			f"{sandbox_url}/tool_call",
			json={
				"action": action,
				"target_app": target_app,
				"git_branch": git_branch,
				"work_item_description": work_item_description,
				"work_item_id": work_item_id_for(a2a_task),
				"args": args,
				"github_token": github_token,
			},
			headers={"Authorization": f"Bearer {token}"},
			timeout=60,
		)
		response.raise_for_status()
		return {"ok": True, "response": response.json()}
	except Exception as exc:
		frappe.log_error(title=f"Dev Agent Sandbox: {action} call failed", message=frappe.get_traceback())
		return {"ok": False, "error": f"The sandbox rejected the call: {exc}"}


def _dispatch_single_action(params: dict, ctx: dict, action: str) -> dict | None:
	"""Shared park/track logic behind dispatch_action — every sandbox tool
	slow enough (minutes, not seconds) to need a dispatch-then-park-then-
	callback shape, carrying one action + its own args rather than a whole
	bundled work order. Each call still gets its own Agent Sandbox Run row —
	these are meaningful, individually-worth-auditing runs, unlike the fast
	tools sandbox_dispatch serves."""
	instance = ctx.get("instance")
	task = ctx.get("task")
	work_item_id = work_item_id_for(_a2a_task_of(instance))

	target_app = (params.get("target_app") or "").strip()
	git_branch = (params.get("git_branch") or "").strip()
	work_item_description = (params.get("work_item_description") or "").strip()
	if not (target_app and git_branch and work_item_description):
		raise AgentSandboxError(f"{action} needs target_app, git_branch, and work_item_description.")

	settings = frappe.get_cached_doc("Processa Settings")
	sandbox_url = (settings.agent_sandbox_url or "").strip().rstrip("/")
	if not sandbox_url:
		raise AgentSandboxError(
			f"Processa Settings has no Sandbox URL configured — {action} has nowhere to dispatch to."
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

	github_token = settings.get_password("github_token", raise_exception=False) or ""
	if not github_token:
		run.db_set({"state": "failed", "error_message": "No GitHub token configured."}, update_modified=False)
		raise AgentSandboxError("Processa Settings has no GitHub token configured.")

	args = {k: v for k, v in params.items() if k not in ("target_app", "git_branch", "work_item_description")}
	payload = {
		"correlation_id": run.name,
		"action": action,
		"target_app": target_app,
		"git_branch": git_branch,
		"work_item_description": work_item_description,
		"work_item_id": work_item_id,
		"args": args,
		"github_token": github_token,
		"callback_url": _callback_url(),
	}
	audit_payload = {**payload, "github_token": "REDACTED"}
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
			title=f"Dev Agent Sandbox: {action} dispatch failed ({run.name})",
			message=frappe.get_traceback(),
		)
		run.db_set({"state": "failed", "error_message": str(exc)[:500]}, update_modified=False)
		raise AgentSandboxError(f"The sandbox rejected the dispatch: {exc}")

	run.db_set("state", "running", update_modified=False)

	if task is not None:
		task.data[AGENT_SANDBOX_WAITING_KEY] = {
			"run": run.name,
			"label": f"{action} for {target_app}@{git_branch}",
		}
	return None


def dispatch_action(params: dict, ctx: dict) -> dict | None:
	"""One generic handler serving every minutes-scale sandbox action —
	currently "run_tests" and "open_pull_request" — as distinct connector
	operations that all point here. Which action to forward is read from
	ctx["operation"] (the operation this Service Task was configured as, set
	by dispatch_connector), not hardcoded per function — so adding a new
	slow, parked sandbox action needs only a new BPMN Connector Operation
	record naming this same handlerPath, no new Python. (The sandbox itself
	still needs to know what to do with that action name — this only removes
	the Processa-side code requirement.)

	open_pull_request's own PR re-tests itself before opening (see
	dev_agent_server.py's _tool_open_pull_request), so pass/fail flagging on
	the PR is accurate regardless of what the model last saw."""
	action = (ctx.get("operation") or "").strip()
	if not action:
		raise AgentSandboxError("dispatch_action was not called through a configured connector operation.")
	return _dispatch_single_action(params, ctx, action)


def _callback_url() -> str:
	"""The sandbox's own /run validation hard-requires an https callback_url
	(dev_agent_server.py's _validate_payload) — this endpoint is never
	dispatched to over anything else. get_url() constructs its scheme from
	the current request context or the site's host_name config, neither of
	which is reliable here: this runs inside a background job (an AI Agent
	Run's own turn), with no live request to read a scheme from, and
	falls back toward http unless host_name says otherwise. Confirmed live:
	a real production dispatch got rejected with a 422 because the
	constructed URL was http:// even though the site is genuinely served
	over https externally — only Frappe's own internal guess was wrong, not
	the actual endpoint. Forcing the scheme here is correct precisely
	because it's already a hard requirement, not a new one."""
	url = frappe.utils.get_url("/api/method/one_bpmn.api.agent_callback.report_result")
	if url.startswith("http://"):
		url = "https://" + url[len("http://"):]
	return url


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
