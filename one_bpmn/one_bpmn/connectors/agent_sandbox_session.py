"""A sandbox session: one Cloud Run Job execution per Work Item attempt, fed commands over a queue the container polls."""

import hashlib
import hmac
import json
import secrets
import time

import frappe
from frappe.utils import now_datetime, time_diff_in_seconds

from one_bpmn.one_bpmn.connectors import agent_sandbox_job as job

SESSION = "Agent Sandbox Session"
COMMAND = "Agent Sandbox Session Command"
RUNNING_STATES = ("starting", "registered", "active", "closing")
LIVE_STATES = ("queued", "starting", "registered", "active")
REGISTER_WINDOW_SECONDS = 300
SIGNATURE_WINDOW_SECONDS = 300
START_WAIT_SECONDS = 300
FAST_WAIT_SECONDS = 60
POLL_SECONDS = 0.25
MAX_RESULT_CHARS = 1_000_000


def uses_job(agent_name: str | None) -> bool:
	return bool(agent_name and frappe.db.get_value("AI Agent Configuration", agent_name, "sandbox_use_job"))


def ensure_session(*, work_item: str, target_app: str, git_branch: str, agent_name: str, caller_instance: str | None):
	"""The live session for this Work Item, or a new one that starts now or waits in the queue."""
	live = frappe.get_all(SESSION, filters={"work_item": work_item, "state": ["in", list(LIVE_STATES)]}, pluck="name", limit=1)
	if live:
		return frappe.get_doc(SESSION, live[0])
	session = frappe.get_doc({
		"doctype": SESSION, "state": "queued", "work_item": work_item, "target_app": target_app, "git_branch": git_branch,
		"agent_name": agent_name, "caller_instance": caller_instance, "started_at": now_datetime(),
		"attempt": frappe.db.count(SESSION, {"work_item": work_item}) + 1,
	})
	session.flags.ignore_links = True
	session.insert(ignore_permissions=True)
	start_if_room(session)
	return session


def start_if_room(session) -> bool:
	"""Start the Job for a queued session when fewer than the allowed sessions are running."""
	cap = frappe.get_cached_doc("Processa Settings").get("sandbox_job_max_parallel") or 10
	if frappe.db.count(SESSION, {"state": ["in", list(RUNNING_STATES)]}) >= cap:
		return False
	token = secrets.token_urlsafe(32)
	session.db_set({"register_token_hash": _hash(token), "state": "starting", "last_heartbeat": now_datetime()}, update_modified=False)
	try:
		execution = job.start_execution(session.name, token)
	except Exception as exc:
		session.db_set({"state": "lost", "error_message": str(exc)[:500], "closed_at": now_datetime()}, update_modified=False)
		raise
	session.db_set("execution_name", execution, update_modified=False)
	return True


def start_queued() -> int:
	"""Start queued sessions, oldest first, while there is room. Returns how many started."""
	started = 0
	for name in frappe.get_all(SESSION, filters={"state": "queued"}, pluck="name", order_by="creation asc"):
		try:
			if not start_if_room(frappe.get_doc(SESSION, name)):
				break
			started += 1
		except job.SandboxJobError:
			frappe.log_error(title=f"Sandbox session {name}: the Job could not be started", message=frappe.get_traceback())
	return started


def enqueue(session, kind: str, action: str, payload: dict, run: str | None = None):
	"""Add a command to the session's queue. Committed here because the container reads it from another request."""
	frappe.db.commit()  # ends the snapshot, so the locked read sees the container's latest heartbeat
	locked = frappe.get_doc(SESSION, session.name, for_update=True)
	seq = (locked.last_seq or 0) + 1
	locked.db_set("last_seq", seq, update_modified=False)
	command = frappe.get_doc({
		"doctype": COMMAND, "session": session.name, "seq": seq, "kind": kind, "action": action,
		"payload": json.dumps(payload), "state": "pending", "run": run,
	})
	command.flags.ignore_links = True
	command.insert(ignore_permissions=True)
	frappe.db.commit()
	return command


def wait_for(command, timeout: float | None = None, sleep=time.sleep) -> dict | None:
	"""The command's result once the container returns it, or None when it did not in time."""
	deadline = time.monotonic() + (timeout or _timeout_for(command.session))
	while time.monotonic() < deadline:
		row = frappe.db.get_value(COMMAND, command.name, ["state", "result"], as_dict=True)
		if row.state in ("done", "failed"):
			return {"ok": row.state == "done", **(json.loads(row.result) if row.result else {})}
		if frappe.db.get_value(SESSION, command.session, "state") in ("closed", "lost", "cancelled"):
			return None
		sleep(POLL_SECONDS)
		frappe.db.commit()  # ends the snapshot, so the next read sees what the container wrote
	return None


def _timeout_for(session_name: str) -> int:
	state = frappe.db.get_value(SESSION, session_name, "state")
	return START_WAIT_SECONDS if state in ("queued", "starting") else FAST_WAIT_SECONDS


def register(session_name: str, token: str) -> dict | None:
	"""Prove the container with its one-time token and hand it the session settings, or None when the proof fails."""
	session = frappe.get_doc(SESSION, session_name) if frappe.db.exists(SESSION, session_name) else None
	if not session or session.state != "starting" or not session.register_token_hash:
		return None
	if not hmac.compare_digest(session.register_token_hash, _hash(token or "")):
		return None
	if time_diff_in_seconds(now_datetime(), session.last_heartbeat) > REGISTER_WINDOW_SECONDS:
		return None
	key = secrets.token_urlsafe(32)
	session.db_set({"register_token_hash": "", "state": "registered", "registered_at": now_datetime(), "last_heartbeat": now_datetime()}, update_modified=False)
	session.session_key = key
	session.save(ignore_permissions=True)
	return {
		"session_key": key,
		"work_item": session.work_item, "attempt": session.attempt, "target_app": session.target_app,
		"git_branch": session.git_branch, "agent_name": session.agent_name,
		"github_token": frappe.get_cached_doc("Processa Settings").get_password("github_token", raise_exception=False) or "",
		"idle_timeout_seconds": session.idle_timeout_seconds,
	}


def verified_session(body: dict, signature: str, raw: bytes):
	"""The session whose key signed this request within the time window, or None."""
	name = body.get("session")
	if not (name and signature and frappe.db.exists(SESSION, name)):
		return None
	session = frappe.get_doc(SESSION, name)
	key = session.get_password("session_key", raise_exception=False)
	if not key or session.state not in ("registered", "active", "closing"):
		return None
	if not hmac.compare_digest(signature, hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()):
		return None
	if abs(time.time() - float(body.get("ts") or 0)) > SIGNATURE_WINDOW_SECONDS:
		return None
	return session


def next_command(session) -> dict | None:
	"""Mark the session alive and hand over the oldest pending command, if any."""
	frappe.db.commit()  # ends the snapshot, so the update below sees a close the reaper just wrote
	state = frappe.db.get_value(SESSION, session.name, "state")
	session.db_set(
		{"last_heartbeat": now_datetime(), "state": "closing" if state == "closing" else "active"},
		update_modified=False,
	)
	rows = frappe.get_all(COMMAND, filters={"session": session.name, "state": "pending"}, fields=["name", "seq", "kind", "action", "payload"], order_by="seq asc", limit_page_length=1)
	if not rows:
		return None
	row = rows[0]
	frappe.db.set_value(COMMAND, row.name, {"state": "delivered", "delivered_at": now_datetime()}, update_modified=False)
	return {"seq": row.seq, "kind": row.kind, "action": row.action, "payload": json.loads(row.payload or "{}")}


def accept_result(session, seq: int, status: str, result: dict) -> bool:
	"""Record command seq's result. A repeat of a finished command changes nothing."""
	rows = frappe.get_all(COMMAND, filters={"session": session.name, "seq": seq}, fields=["name", "state", "run", "kind"], limit_page_length=1)
	if not rows:
		return False
	row = rows[0]
	if row.state in ("done", "failed"):
		return True
	text = json.dumps(result)
	if len(text) > MAX_RESULT_CHARS:
		result, status = {"error": f"The result was {len(text)} characters, over the {MAX_RESULT_CHARS} limit."}, "error"
	frappe.db.set_value(
		COMMAND, row.name,
		{"state": "done" if status == "ok" else "failed", "result": json.dumps(result), "done_at": now_datetime()},
		update_modified=False,
	)
	if row.kind == "close":
		session.db_set({"state": "closed", "closed_at": now_datetime()}, update_modified=False)
	if row.run:
		from one_bpmn.api.agent_callback import settle_as_agent

		settle_as_agent(frappe.get_doc("Agent Sandbox Run", row.run), {**result, "correlation_id": row.run})
	return True


def close(session) -> None:
	"""Ask the container to push and exit."""
	session.db_set("state", "closing", update_modified=False)
	enqueue(session, "close", "close", {})


def _hash(token: str) -> str:
	return hashlib.sha256(token.encode()).hexdigest()
