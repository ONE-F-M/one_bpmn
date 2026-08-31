# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Dev Agent Sandbox's push callback (mirrors api/a2a_api.push_callback's
security shape, WI-001933's push endpoint).

Reachable without a Frappe session — the sandbox has no user here — so an
HMAC signature over the exact request body IS the gate, verified against
Processa Settings.agent_callback_secret (the same secret the sandbox
was deployed with — see agent-sandbox/deploy.py). Every failure returns
the same opaque answer: a caller must not be able to use this endpoint to
learn which correlation ids exist or why a signature was rejected.

The sandbox opens the pull request itself, directly against GitHub, before
it ever calls back — this endpoint only records what already happened
(pr_url on a pass, or why one wasn't opened) and resumes whoever is waiting.
It never talks to GitHub on the sandbox's behalf.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import frappe


@frappe.whitelist(allow_guest=True, methods=["POST"])
def report_result() -> dict:
	opaque = {"accepted": False}

	raw_body = frappe.request.get_data()
	presented_signature = (frappe.get_request_header("X-Signature") or "").strip()
	if not presented_signature:
		return opaque

	# .strip() is deliberate — a secret created via `openssl rand -hex 32 |
	# gcloud secrets create ...` carries a trailing newline that a person
	# copy-pasting the same value into this field will not reproduce.
	# Confirmed the hard way: every callback was rejected as a signature
	# mismatch even though both sides held what looked like the identical
	# secret. Symmetric with the .strip() on CALLBACK_HMAC_SECRET in
	# dev_agent_server.py.
	secret = (frappe.get_cached_doc("Processa Settings").get_password("agent_callback_secret") or "").strip()
	if not secret:
		frappe.log_error(
			title="Dev Agent Sandbox: callback rejected — no callback secret configured",
			message="Processa Settings.agent_callback_secret is blank.",
		)
		return opaque

	expected_signature = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
	if not hmac.compare_digest(presented_signature, expected_signature):
		frappe.log_error(
			title="Dev Agent Sandbox: callback rejected — signature mismatch",
			message="Presented X-Signature did not match the expected HMAC.",
		)
		return opaque

	try:
		payload = json.loads(raw_body or b"{}")
	except Exception:
		return opaque
	if not isinstance(payload, dict):
		return opaque

	correlation_id = payload.get("correlation_id")
	if not correlation_id or not frappe.db.exists("Agent Sandbox Run", correlation_id):
		# Deliberately indistinguishable from a signature failure.
		return opaque

	run = frappe.get_doc("Agent Sandbox Run", correlation_id)
	if run.state in ("completed", "failed"):
		return {"accepted": True}  # already settled — a replayed callback is a no-op

	status = payload.get("status")
	run.db_set("result", frappe.as_json(payload), update_modified=False)

	if status == "tests_passed":
		files = payload.get("files") or {}
		pr_url = payload.get("pr_url") or ""
		if files:
			run.db_set("files", frappe.as_json(files), update_modified=False)
		if pr_url:
			run.db_set({"state": "completed", "pr_url": pr_url}, update_modified=False)
		else:
			error = payload.get("pr_error") or "Sandbox reported tests_passed but did not open a pull request."
			run.db_set({"state": "failed", "error_message": error[:500]}, update_modified=False)
	elif status == "tests_passed_no_changes":
		run.db_set(
			{"state": "failed", "error_message": "Tests passed but the agent made no changes to submit."},
			update_modified=False,
		)
	else:
		run.db_set(
			{"state": "failed", "error_message": (payload.get("error") or status or "sandbox run failed")[:500]},
			update_modified=False,
		)

	_enqueue_resume(run)
	return {"accepted": True}


def _enqueue_resume(run) -> None:
	"""Two shapes of caller, one entry point — mirrors tasks.py's
	_wake_a2a_caller exactly, for the same reason:

	- a plain, top-level parked Service Task on a diagram (the standalone
	  Dev Agent map's own dispatch_to_sandbox step) → resume that step
	  directly via kind="agent_sandbox_result".
	- an agent suspended mid-turn because it called dispatch_to_sandbox as
	  an ai_agent tool (e.g. from Dev Agent's own instruction-parsing step)
	  → hand the answer to its checkpoint and resume the agent, exactly as
	  completing a human task does.

	caller_agent_run is only ever set by the second case (see
	bpmn_process_instance._bind_agent_sandbox_wait), so checking it
	first is the whole routing decision.
	"""
	if run.caller_agent_run:
		_resume_waiting_agent(run)
		return

	from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import (
		_enqueue_agent_sandbox_resume,
	)

	_enqueue_agent_sandbox_resume(run.caller_instance, run.caller_wf_task_id, run.name)


def _resume_waiting_agent(run) -> None:
	"""Give the sandbox's outcome to the agent suspended waiting for it.

	Mirrors tasks.py._resume_waiting_agent (the A2A case) exactly: store the
	result on the checkpoint, then resume in the AI worker via
	kind="human_resume" — to the agent this is the same event as a human
	answering the tool call it paused on.
	"""
	import json as _json

	from one_bpmn.agents import checkpoint as _checkpoint

	agent_run = run.caller_agent_run
	if not (agent_run and run.caller_instance):
		return
	if frappe.db.get_value("AI Agent Run", agent_run, "status") != "Suspended":
		return  # already resumed or failed — nothing is waiting

	_checkpoint.store_human_result(agent_run, _sandbox_run_answer(run))

	payload = _json.loads(frappe.db.get_value("AI Agent Run", agent_run, "checkpoint") or "{}")
	frappe.enqueue(
		"one_bpmn.one_bpmn.doctype.bpmn_process_instance"
		".bpmn_process_instance.run_parked_ai_task",
		queue="bpmn_ai_agent",
		timeout=600,
		enqueue_after_commit=True,
		job_id=f"bpmn-ai-{run.caller_instance}-devagentres-{run.name}",
		deduplicate=True,
		instance_name=run.caller_instance,
		kind="human_resume",
		task_id=payload.get("wf_task_id") or run.caller_wf_task_id or "",
		run_as_user="Administrator",
	)


def _sandbox_run_answer(run) -> str:
	"""What the model is told the sandbox tool call returned — same shape
	as _delegation_answer's reasoning in tasks.py: a failure is reported in
	words, not hidden, since the agent asked for this work and deserves to
	know what actually happened."""
	if run.state == "completed":
		return f"Pull request opened: {run.pr_url}" if run.pr_url else "Sandbox run completed with no changes to submit."
	return f"The sandbox run did not complete ({run.state}): {run.error_message or 'no reason given'}"
