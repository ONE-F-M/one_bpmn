"""Settles sandbox runs whose result can no longer arrive, and wakes the agents waiting on them."""

from datetime import datetime

import frappe
from frappe.utils import get_datetime, now_datetime, time_diff_in_seconds

from one_bpmn.one_bpmn.connectors import agent_sandbox_job as job
from one_bpmn.one_bpmn.connectors import agent_sandbox_ops as ops
from one_bpmn.one_bpmn.connectors import agent_sandbox_session as sessions

FAST_ACTIONS = frozenset({
	"read_file", "write_file", "edit_file", "delete_file", "list_files", "read_files", "grep_files",
	"apply_edits", "submit_plan",
})
FAST_SILENCE_SECONDS = 5 * 60
SLOW_SILENCE_SECONDS = 10 * 60
DEADLINE_SECONDS = 45 * 60
OPEN_STATES = ["submitted", "running"]


def reap():
	"""Scheduler entry: settle every open run that is past its limit."""
	for name in frappe.get_all("Agent Sandbox Run", filters={"state": ["in", OPEN_STATES]}, pluck="name"):
		try:
			settle_if_dead(frappe.get_doc("Agent Sandbox Run", name))
		except Exception:
			frappe.log_error(title=f"Agent Sandbox Run {name}: reaper failed", message=frappe.get_traceback())


SESSION_SILENCE_SECONDS = 5 * 60


def reap_sessions():
	"""Scheduler entry: start queued sessions, close idle ones and settle the ones whose container is gone."""
	try:
		sessions.start_queued()
	except Exception:
		frappe.log_error(title="Sandbox sessions: starting the queue failed", message=frappe.get_traceback())
	for name in frappe.get_all(sessions.SESSION, filters={"state": ["in", list(sessions.RUNNING_STATES)]}, pluck="name"):
		try:
			settle_session_if_dead(frappe.get_doc(sessions.SESSION, name))
		except Exception:
			frappe.log_error(title=f"Sandbox session {name}: reaper failed", message=frappe.get_traceback())


def settle_session_if_dead(session) -> bool:
	"""Mark the session lost when its container never registered or went silent; close it when it has been idle."""
	silent_for = _seconds_since(session.last_heartbeat or session.started_at)
	if session.state == "starting":
		if silent_for <= sessions.REGISTER_WINDOW_SECONDS:
			return False
		return _lose(session, "The container never registered.")
	if silent_for > SESSION_SILENCE_SECONDS:
		exited = bool(_execution_status(session).get("completionTime"))
		return _lose(session, "The container exited." if exited else "The container stopped answering.")
	if session.state in ("registered", "active") and _idle_seconds(session) > (session.idle_timeout_seconds or 600):
		sessions.close(session)
	return False


def _lose(session, reason: str) -> bool:
	session.db_set({"state": "lost", "error_message": reason, "closed_at": now_datetime()}, update_modified=False)
	if session.execution_name:
		try:
			job.cancel_execution(session.execution_name)
		except job.SandboxJobError:
			frappe.log_error(title=f"Sandbox session {session.name}: cancel failed", message=frappe.get_traceback())
	for command in frappe.get_all(
		sessions.COMMAND, filters={"session": session.name, "state": ["in", ["pending", "delivered"]]}, fields=["name", "run"]
	):
		frappe.db.set_value(sessions.COMMAND, command.name, {"state": "failed", "result": frappe.as_json({"error": reason})}, update_modified=False)
		if command.run:
			_settle(frappe.get_doc("Agent Sandbox Run", command.run), "stale", f"The sandbox session was lost: {reason}")
	return True


def _execution_status(session) -> dict:
	"""The Job execution's own record, or {} when Cloud Run cannot be asked."""
	if not session.execution_name:
		return {}
	try:
		return job.execution_status(session.execution_name)
	except job.SandboxJobError:
		frappe.log_error(title=f"Sandbox session {session.name}: execution status failed", message=frappe.get_traceback())
		return {}


def _idle_seconds(session) -> float:
	last = frappe.db.get_value(sessions.COMMAND, {"session": session.name}, "creation", order_by="creation desc")
	return _seconds_since(last or session.registered_at or session.started_at)


def settle_overdue():
	"""Settle every open run older than the deadline, without asking the sandbox. For the one-off clean-up."""
	for name in frappe.get_all("Agent Sandbox Run", filters={"state": ["in", OPEN_STATES]}, pluck="name"):
		run = frappe.get_doc("Agent Sandbox Run", name)
		if _seconds_since(run.started_at or run.creation) > DEADLINE_SECONDS:
			_settle(run, "timed_out", f"No result after {DEADLINE_SECONDS // 60} minutes.")


def settle_if_dead(run) -> bool:
	"""Settle the run when it is past its limit; True when it was settled."""
	silent_for = _seconds_since(run.last_heartbeat or run.started_at or run.creation)
	if _seconds_since(run.started_at or run.creation) > DEADLINE_SECONDS:
		_settle(run, "timed_out", f"No result after {DEADLINE_SECONDS // 60} minutes.")
		return True
	if run.action in FAST_ACTIONS:
		if silent_for <= FAST_SILENCE_SECONDS:
			return False
		_settle(run, "stale", f"No answer for {int(silent_for // 60)} minutes, so Processa stopped waiting for it.")
		return True
	if silent_for <= SLOW_SILENCE_SECONDS:
		return False
	return _settle_from_status(run, _sandbox_status(run))


def _settle_from_status(run, job: dict | None) -> bool:
	if job is None:
		_settle(run, "stale", "The sandbox no longer knows this run, so its instance was probably restarted.")
		return True
	if job.get("state") in ("done", "failed"):
		_settle(run, "stale", f"The sandbox finished ({job['state']}) but its callback never arrived.")
		return True
	beat = datetime.fromtimestamp(job["updated_at"]) if job.get("updated_at") else None
	if beat and _seconds_since(beat) <= SLOW_SILENCE_SECONDS:
		run.db_set("last_heartbeat", beat, update_modified=False)
		return False
	_settle(run, "stale", f"The sandbox has reported nothing for {SLOW_SILENCE_SECONDS // 60} minutes.")
	return True


def _sandbox_status(run) -> dict | None:
	"""The sandbox's own record of the run, or None when it does not know it."""
	import requests

	url = (frappe.get_cached_doc("Processa Settings").agent_sandbox_url or "").strip().rstrip("/")
	response = requests.get(
		f"{url}/status/{run.name}", headers={"Authorization": f"Bearer {ops._mint_identity_token(url)}"}, timeout=15
	)
	if response.status_code == 404:
		return None
	response.raise_for_status()
	return response.json()


def _settle(run, state: str, reason: str):
	run.db_set(
		ops._finished({"state": state, "failure_class": "infra", "error_message": reason}), update_modified=False
	)
	if (run.caller_agent_run or run.caller_wf_task_id) and not run.resume_enqueued:
		from one_bpmn.api.agent_callback import _enqueue_resume

		step = ops.supervisor.next_step(run)
		ops.supervisor.record(run, step)
		if ops.retry_eligible(run) and ops.retry_dispatch(run, delay=step["delay"]):
			return
		run.db_set("resume_enqueued", 1, update_modified=False)
		_enqueue_resume(run)


def _seconds_since(moment) -> float:
	return time_diff_in_seconds(now_datetime(), get_datetime(moment))
