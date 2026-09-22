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


_READ_BUDGET = 15
_REMINDER_AFTER = 8
_READ_ACTIONS = ("read_file", "list_files")
_PROGRESS_ACTIONS = ("edit_file", "write_file")
_PLAN_ACTION = "submit_plan"
_TEST_PATH = re.compile(
	r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+\.\w+$|_test\.\w+$|\.(test|spec)\.\w+$",
	re.IGNORECASE,
)


def _reads_since_last_edit(instance, limit: int) -> int:
	"""How many read_file/list_files calls this run has made, most-recent
	first, stopping at the first edit_file/write_file (success or failure —
	attempting one is the signal, not whether it worked) or at `limit`,
	whichever comes first. Shared by read_budget_exceeded and goal_reminder
	so the two thresholds count the exact same thing."""
	if instance is None:
		return 0
	rows = frappe.get_all(
		"Agent Sandbox Run",
		filters={"caller_instance": instance.name, "state": "completed"},
		fields=["request_payload"],
		order_by="creation desc",
		limit_page_length=limit,
	)
	count = 0
	for row in rows:
		action = (frappe.parse_json(row.request_payload) or {}).get("action")
		if action in _PROGRESS_ACTIONS:
			break
		if action in _READ_ACTIONS:
			count += 1
	return count


def read_budget_exceeded(instance) -> str | None:
	"""None if there's room for another read_file/list_files call this run;
	otherwise the error to return instead of dispatching one.

	Confirmed live (2026-09-13/14): once a per-file re-read cap (the read_file
	Server Script's own dedup-then-refuse logic) forecloses looping on any one
	file, a run can just wander across dozens of *different* unrelated files
	instead and still never call edit_file/write_file — the real problem is
	unbounded exploration with no edit attempt, not which file it lands on.

	Counts read_file/list_files calls back from the most recent, stopping at
	the first edit_file/write_file (in either direction — success or failure,
	since attempting one is itself the signal that matters) or once the count
	reaches _READ_BUDGET. An edit resets the budget: that's real progress,
	not more looking around, however many further reads it takes afterward."""
	if _reads_since_last_edit(instance, _READ_BUDGET + 1) < _READ_BUDGET:
		return None
	return (
		f"You have made {_READ_BUDGET} read-only calls this run without attempting "
		"a single edit. Stop exploring: either attempt the edit now with what "
		"you already have, or state specifically what information is still "
		"missing and why you cannot proceed without it."
	)


def _a2a_instruction(context_docname: str) -> str:
	"""The free-text instruction stored on one A2A Task, or "" if there is
	none — split out purely so a test can mock this one small lookup
	directly instead of a global frappe.db.get_value patch (confirmed to
	have unrelated side effects on later frappe.get_all calls in the same
	test run when tried that way)."""
	payload = frappe.db.get_value("A2A Task", context_docname, "request_payload") or ""
	return (frappe.parse_json(payload) or {}).get("instruction") or ""


def goal_reminder(instance) -> str | None:
	"""A short restatement of the actual work order, to attach alongside an
	ordinary read_file/list_files result once exploration has gone on for a
	while with no edit attempt yet — None below the threshold, once an edit
	has been attempted, or when there's no A2A Task to read the original
	instruction back from.

	A long, tool-result-heavy run can bury the original work order dozens of
	turns back, and a model's effective attention to something that far back
	visibly weakens as the transcript grows, even though it is technically
	still in context — confirmed live: a run that wandered into files with no
	relation to its own work order (backfill patches, an unrelated agent's
	config) well after the point this would have fired. Re-derived from the
	A2A Task's own stored instruction rather than trusting the model's own
	work_item_description argument, since that could itself have drifted
	from the original by the time it would matter."""
	if instance is None:
		return None
	if _reads_since_last_edit(instance, _REMINDER_AFTER) < _REMINDER_AFTER:
		return None
	if getattr(instance, "context_doctype", None) != "A2A Task":
		return None
	context_docname = getattr(instance, "context_docname", None)
	if not context_docname:
		return None
	instruction = _a2a_instruction(context_docname)
	if not instruction:
		return None
	return (
		"Reminder of the actual work order, since a lot of exploring can bury "
		"it: " + instruction
	)


def plan_required_error(instance) -> str | None:
	"""None once this run has submitted a plan (the submit_plan tool);
	otherwise the error to return instead of dispatching an edit_file or
	write_file call.

	Planning and executing an unfamiliar, multi-file change in one
	continuous, unsupervised tool-calling loop is a harder task than either
	half alone — requiring a plan first, before any file is touched, forces
	the model to commit to a concrete approach in writing rather than
	discovering one file at a time while already mid-edit."""
	if instance is None:
		return None
	exists = frappe.db.exists("Agent Sandbox Run", {
		"caller_instance": instance.name,
		"state": "completed",
		"request_payload": ["like", f'%"action": "{_PLAN_ACTION}"%'],
	})
	if exists:
		return None
	return (
		"Submit a plan first with submit_plan — name which files you will "
		"change and what each change is — before making any edit."
	)


_REPRODUCE_MESSAGE = (
	"Reproduce the bug first: write or edit a test that fails because of it, "
	"call run_tests and confirm it actually fails, then make this change."
)


_BUG_PIPELINE_PROCESSES = ("Bug Agent", "Bug Planner", "Bug Programmer", "Bug Reviewer")


def repeat_run_tests_without_progress_error(instance, action: str) -> str | None:
	"""None unless `action` is "run_tests", this instance is running one of
	the Bug pipeline's own processes, AND the single most recent Agent
	Sandbox Run for it was itself a failed run_tests -- i.e. calling
	run_tests again right now would just re-run the exact same thing with
	nothing changed in between. Scoped to the Bug pipeline only: Dev Agent
	and the other specialists share this same dispatch_action/run_tests path
	and are deliberately left untouched.

	Confirmed live (WI-000433, A2A-165115): Bug Programmer called run_tests
	four times in a row against the unmodified suite, never once attempting
	an edit, and burned its whole turn budget doing it. Checking only the
	MOST RECENT row (not "was there ever a failure") is deliberate: reading
	a file or submitting a plan in between is real re-investigation, not a
	blind repeat, and must not be refused."""
	if action != "run_tests" or instance is None:
		return None
	if getattr(instance, "process_model", None) not in _BUG_PIPELINE_PROCESSES:
		return None
	rows = frappe.get_all(
		"Agent Sandbox Run",
		filters={"caller_instance": instance.name},
		fields=["state", "request_payload"],
		order_by="creation desc",
		limit_page_length=1,
	)
	if not rows:
		return None
	last_action = (frappe.parse_json(rows[0].request_payload) or {}).get("action")
	if rows[0].state == "failed" and last_action == "run_tests":
		return (
			"The last run_tests call already failed and nothing has changed "
			"since -- running it again right now will fail the same way. "
			"Write or edit the file the failure actually points to first "
			"(a reproducing test if you have not written one yet, otherwise "
			"the fix), then call run_tests again."
		)
	return None


def reproduction_required_error(instance, path: str | None = None) -> str | None:
	"""None if `path` is itself a test file (writing or editing a test is
	always allowed, reproducing the bug included), or if this run already
	shows a completed edit_file/write_file to a test file FOLLOWED BY a
	run_tests that failed -- real evidence the bug was reproduced before
	anything else was touched; otherwise the error to return instead of
	dispatching the edit.

	Checking only "does a failed run_tests row exist anywhere in this run"
	was the first version and is deliberately not enough: an unrelated,
	pre-existing failure in the untouched suite would satisfy that check
	without the model ever having written a reproducing test. Ordering
	(a test file written, THEN a failure) is what proves reproduction, not
	just a failure existing somewhere in this run's history."""
	if path and _TEST_PATH.search(path):
		return None
	if instance is None:
		return _REPRODUCE_MESSAGE
	rows = frappe.get_all(
		"Agent Sandbox Run",
		filters={"caller_instance": instance.name},
		fields=["state", "request_payload"],
		order_by="creation asc",
	)
	test_file_written = False
	for row in rows:
		payload = frappe.parse_json(row.request_payload) or {}
		action = payload.get("action")
		args = payload.get("args") or {}
		if row.state == "completed" and action in _PROGRESS_ACTIONS and _TEST_PATH.search(args.get("path") or ""):
			test_file_written = True
		elif row.state == "failed" and action == "run_tests" and test_file_written:
			return None
	return _REPRODUCE_MESSAGE


def record_plan(target_app: str, git_branch: str, work_item_description: str, plan: str, *,
                 bpmn_id: str | None = None, instance=None) -> None:
	"""Records the submit_plan tool's call as a completed Agent Sandbox Run
	row — the same row plan_required_error looks for. No sandbox HTTP call:
	submitting a plan is a decision about what to do, not something the
	sandbox needs to execute, so this settles synchronously like
	sandbox_dispatch's fast tools do, just without a network round trip."""
	doc = frappe.get_doc({
		"doctype": "Agent Sandbox Run",
		"state": "completed",
		"target_app": target_app,
		"git_branch": git_branch,
		"bpmn_id": bpmn_id,
		"caller_instance": getattr(instance, "name", None),
		"work_item_description": work_item_description,
		"request_payload": frappe.as_json({"action": _PLAN_ACTION, "args": {"plan": plan}}),
	})
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)


def sandbox_dispatch(action: str, target_app: str, git_branch: str, work_item_description: str,
                      args: dict, a2a_task: str | None = None, *,
                      bpmn_id: str | None = None, instance=None) -> dict:
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
	turn over.

	Every call still gets its own Agent Sandbox Run row — same auditability
	dispatch_action's run_tests/open_pull_request already have, just settled
	in one pass (running -> completed/failed) instead of parked at "running"
	for a callback to resume. bpmn_id/instance are optional and keyword-only
	purely so tracking can never become a REQUIRED argument a caller forgets
	and breaks on — omitting them still creates the row, just with those two
	fields left blank. Row creation itself is wrapped so a DB hiccup here
	degrades to no row at all rather than breaking the NEVER RAISES
	guarantee above."""
	run = None
	try:
		run = frappe.get_doc({
			"doctype": "Agent Sandbox Run",
			"state": "running",
			"target_app": target_app,
			"git_branch": git_branch,
			"bpmn_id": bpmn_id,
			"caller_instance": getattr(instance, "name", None),
			"work_item_description": work_item_description,
		})
		run.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title=f"Dev Agent Sandbox: {action} could not create a tracking row",
			message=frappe.get_traceback(),
		)
		run = None

	settings = frappe.get_cached_doc("Processa Settings")
	sandbox_url = (settings.agent_sandbox_url or "").strip().rstrip("/")
	if not sandbox_url:
		error = "Processa Settings has no Sandbox URL configured."
		if run:
			run.db_set({"state": "failed", "error_message": error}, update_modified=False)
		return {"ok": False, "error": error}
	github_token = settings.get_password("github_token", raise_exception=False) or ""
	if not github_token:
		error = "Processa Settings has no GitHub token configured."
		if run:
			run.db_set({"state": "failed", "error_message": error}, update_modified=False)
		return {"ok": False, "error": error}

	payload = {
		"action": action,
		"target_app": target_app,
		"git_branch": git_branch,
		"work_item_description": work_item_description,
		"work_item_id": work_item_id_for(a2a_task),
		"args": args,
	}
	if run:
		run.db_set("request_payload", frappe.as_json(payload), update_modified=False)

	try:
		token = _mint_identity_token(sandbox_url)
	except Exception as exc:
		frappe.log_error(title=f"Dev Agent Sandbox: {action} auth failed", message=frappe.get_traceback())
		error = f"Could not authenticate to the sandbox: {exc}"
		if run:
			run.db_set({"state": "failed", "error_message": error[:500]}, update_modified=False)
		return {"ok": False, "error": error}

	try:
		import requests

		response = requests.post(
			f"{sandbox_url}/tool_call",
			json={**payload, "github_token": github_token},
			headers={"Authorization": f"Bearer {token}"},
			timeout=60,
		)
		response.raise_for_status()
		data = response.json()
		if run:
			run.db_set({"state": "completed", "result": frappe.as_json(data)}, update_modified=False)
		return {"ok": True, "response": data}
	except Exception as exc:
		frappe.log_error(title=f"Dev Agent Sandbox: {action} call failed", message=frappe.get_traceback())
		error = f"The sandbox rejected the call: {exc}"
		if run:
			run.db_set({"state": "failed", "error_message": error[:500]}, update_modified=False)
		return {"ok": False, "error": error}


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

	progress_error = repeat_run_tests_without_progress_error(instance, action)
	if progress_error:
		raise AgentSandboxError(progress_error)

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
