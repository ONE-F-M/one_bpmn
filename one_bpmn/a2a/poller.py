# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The A2A reconciler: polls remote delegations, settles same-site ones and wakes whatever is waiting on them."""

import frappe
from frappe.utils import add_to_date, now_datetime

from one_bpmn.processa_engine.agent_runtime.job_limits import AI_AGENT_JOB_TIMEOUT
from one_bpmn.processa_engine.runtime.remote_waits import on_a2a_input_required


def poll_a2a_tasks():
	"""Check on delegated A2A tasks every minute and wake what is waiting.

	next_poll_at is claimed before the network call, polling backs off per task, and a task past its deadline is cancelled.
	"""
	from frappe.utils import cint

	from one_bpmn.a2a import client as a2a_client
	from one_bpmn.a2a.push import PUSH_RECONCILE_SECONDS
	from one_bpmn.processa_engine.runtime.ai_jobs import enqueue_wait_resume

	now = now_datetime()
	# Same-site delegations first: no network, so they never wait behind a remote's timeout.
	_reconcile_internal_tasks(now)

	due = frappe.get_all(
		"A2A Task",
		filters={
			"direction": "Outbound",
			"state": ["in", ("submitted", "working", "auth-required")],
			"next_poll_at": ["<=", now],
		},
		fields=[
			"name",
			"remote_agent",
			"remote_task_id",
			"instance",
			"wf_task_id",
			"deadline",
			"poll_attempts",
			"push_registered",
		],
		limit=100,
	)

	for row in due:
		try:
			remote = frappe.get_doc("A2A Remote Agent", row.remote_agent)
			attempts = cint(row.poll_attempts) + 1
			base = cint(remote.poll_base_interval) or 60
			ceiling = cint(remote.poll_max_interval) or 900
			# A remote that pushes is only reconciled here, as a safety net for a dropped callback.
			if row.push_registered:
				interval = PUSH_RECONCILE_SECONDS
			else:
				interval = min(base * (2 ** (attempts - 1)), ceiling)
			frappe.db.set_value(
				"A2A Task",
				row.name,
				{
					"poll_attempts": attempts,
					"last_polled_at": now,
					"next_poll_at": add_to_date(now, seconds=interval),
				},
				update_modified=False,
			)
			frappe.db.commit()

			if row.deadline and now_datetime() > frappe.utils.get_datetime(row.deadline):
				_time_out_task(row, remote)
				continue

			if not row.remote_task_id:
				continue

			result = a2a_client.tasks_get(remote, row.remote_task_id)
			state = a2a_client.remote_state(result) or "working"

			if state == "completed":
				text = a2a_client.remote_text(result)
				frappe.db.set_value(
					"A2A Task",
					row.name,
					{
						"state": "completed",
						"result": frappe.as_json({"text": text}),
						"status_message": text[:500],
						"completed_at": now_datetime(),
					},
					update_modified=True,
				)
				enqueue_wait_resume(row.instance, row.wf_task_id, row.name, "A2A Task")
			elif state in ("failed", "canceled", "rejected"):
				frappe.db.set_value(
					"A2A Task",
					row.name,
					{
						"state": state,
						"error_message": (a2a_client.remote_text(result) or state)[:500],
						"completed_at": now_datetime(),
					},
					update_modified=True,
				)
				enqueue_wait_resume(row.instance, row.wf_task_id, row.name, "A2A Task")
			elif state == "input-required":
				frappe.db.set_value(
					"A2A Task", row.name, {"state": "input-required"}, update_modified=True
				)
				if row.instance:
					instance = frappe.get_doc("BPMN Process Instance", row.instance)
					on_a2a_input_required(instance, row.name, a2a_client.remote_text(result))
			else:
				frappe.db.set_value("A2A Task", row.name, {"state": state}, update_modified=True)
			frappe.db.commit()
		except a2a_client.A2ANotApprovedError as exc:
			# Revoked mid-flight: fail closed.
			frappe.db.set_value(
				"A2A Task",
				row.name,
				{"state": "failed", "error_message": str(exc)[:500], "completed_at": now_datetime()},
				update_modified=True,
			)
			enqueue_wait_resume(row.instance, row.wf_task_id, row.name, "A2A Task")
			frappe.db.commit()
		except Exception:
			frappe.log_error(
				title=f"A2A poll failed: {row.name}", message=frappe.get_traceback()
			)


def wake_caller_if_any(row) -> None:
	"""Wake the caller only when there is one; a top-level delegation has no parked step and no suspended agent."""
	if row.caller_wf_task_id or row.caller_agent_run:
		_wake_a2a_caller(row)


def _retry_delegation(task) -> bool:
	"""Run the worker again if this failed delegation has an attempt left.

	True when a retry started and the caller must not be woken; False when it is finished, after escalating if attempts ran out.
	"""
	from one_bpmn.a2a import delegation, execute

	try:
		if delegation.should_retry(task.name):
			attempt = delegation.note_attempt(task.name)
			config = frappe.db.get_value(
				"AI Agent Configuration",
				task.agent_configuration,
				["name", "agent_id", "agent_type", "process_model"],
				as_dict=True,
			)
			if not config:
				return False
			payload = frappe.parse_json(task.request_payload or "{}") or {}
			# One row spans every attempt, so the last failure is cleared.
			task.db_set(
				{"state": "submitted", "error_message": None, "error_code": None},
				update_modified=True,
			)
			task.reload()
			frappe.logger("one_bpmn").info(
				f"A2A delegation {task.name}: retrying {task.agent_configuration} "
				f"(attempt {attempt})"
			)
			# fresh=True runs the worker again instead of reattaching to the last attempt.
			execute.run_for_task(task, config, payload.get("instruction") or "", fresh=True)
			task.reload()
			return task.state not in ("failed", "rejected")

		delegation.retries_exhausted(task.name)
		return False
	except Exception:
		frappe.log_error(
			title=f"A2A delegation retry failed ({task.name})", message=frappe.get_traceback()
		)
		return False


def _escalate_deadline(task_name: str, agent_configuration=None, caller_instance=None) -> None:
	"""Tell the owner a delegated task ran out of time; delegation.notified_at keeps it to one alert per breach."""
	from one_bpmn.a2a import delegation

	# Both numbers come off the row, so a per-step timeout override is the limit reported.
	allowed = 0
	ran_for = 0
	try:
		row = frappe.db.get_value(
			"A2A Task", task_name, ["creation", "deadline"], as_dict=True
		)
		if row and row.creation:
			started = frappe.utils.get_datetime(row.creation)
			if row.deadline:
				# Rounded: the deadline is stamped just after creation, so a one-minute allowance measures 59.99s.
				allowed = max(
					0, round((frappe.utils.get_datetime(row.deadline) - started).total_seconds() / 60)
				)
			ran_for = max(0, int((now_datetime() - started).total_seconds() // 60))
	except Exception:
		pass
	delegation.stopped_at_limit(
		a2a_task=task_name,
		reason="delegation_deadline_minutes",
		limit_value=allowed,
		reached_value=ran_for,
		detail=(
			f"Its deadline had already passed; it had been running for about {ran_for} minute(s)."
			if allowed <= 0
			else f"It was allowed {allowed} minute(s) and had been running for about "
			f"{ran_for} when the deadline passed."
		)
		+ delegation.attempts_note(task_name),
		instance=caller_instance,
		worker_agent=agent_configuration,
	)


def _time_out_task(row, remote) -> None:
	"""Past the deadline: ask the remote to stop, then fail through the normal BPMN error path."""
	from one_bpmn.a2a import client as a2a_client
	from one_bpmn.processa_engine.runtime.ai_jobs import enqueue_wait_resume

	if row.remote_task_id:
		try:
			a2a_client.tasks_cancel(remote, row.remote_task_id)
		except Exception:
			pass  # best effort, the deadline stands either way
	frappe.db.set_value(
		"A2A Task",
		row.name,
		{
			"state": "timed-out",
			"error_message": "the delegated task passed its deadline",
			"completed_at": now_datetime(),
		},
		update_modified=True,
	)
	_escalate_deadline(
		row.name,
		agent_configuration=getattr(row, "agent_configuration", None),
		caller_instance=getattr(row, "caller_instance", None),
	)
	enqueue_wait_resume(row.instance, row.wf_task_id, row.name, "A2A Task")
	frappe.db.commit()


def _reconcile_internal_tasks(now) -> None:
	"""Same-site delegations: re-derive the state from the worker's run or instance and wake the caller when it settles."""
	from frappe.utils import cint

	from one_bpmn.a2a import local

	terminal = ("completed", "canceled", "failed", "rejected", "timed-out")
	# Not filtered by state: a row can turn terminal while its caller is still parked; resume_enqueued marks the wake.
	rows = frappe.get_all(
		"A2A Task",
		filters={
			"direction": "Internal",
			"resume_enqueued": 0,
			"next_poll_at": ["<=", now],
		},
		or_filters={
			"caller_wf_task_id": ["is", "set"],
			"caller_agent_run": ["is", "set"],
			# A top-level delegation has neither caller, but its instance still gives it a state.
			"instance": ["is", "set"],
		},
		fields=[
			"name",
			"caller_instance",
			"caller_wf_task_id",
			"caller_agent_run",
			"wf_task_id",
			"deadline",
			"poll_attempts",
			"state",
			"instance",
			"agent_configuration",
			"request_payload",
		],
		limit=100,
	)
	for row in rows:
		try:
			attempts = cint(row.poll_attempts) + 1
			frappe.db.set_value(
				"A2A Task",
				row.name,
				{
					"poll_attempts": attempts,
					"last_polled_at": now,
					"next_poll_at": add_to_date(now, seconds=30),
				},
				update_modified=False,
			)

			task = frappe.get_doc("A2A Task", row.name)

			# Before the terminal branch: a failed worker with an attempt left is not final.
			if task.state == "failed" and _retry_delegation(task):
				frappe.db.commit()
				continue

			if task.state in terminal:
				wake_caller_if_any(row)
				_mark_resumed(row.name)
				frappe.db.commit()
				continue

			# Refresh before judging the clock: the row lags, and finished work is finished however late it is seen.
			local.refresh(task)
			task.reload()
			if task.state in terminal:
				wake_caller_if_any(row)
				_mark_resumed(row.name)
				frappe.db.commit()
				continue

			if row.deadline and now_datetime() > frappe.utils.get_datetime(row.deadline):
				task.db_set(
					{
						"state": "timed-out",
						"error_message": "the delegated task passed its deadline",
						"completed_at": now_datetime(),
					},
					update_modified=True,
				)
				# Stops the worker advancing; a pass already executing still finishes.
				from one_bpmn.a2a import execute

				execute.retire_instance(task.instance)
				_escalate_deadline(
					row.name,
					agent_configuration=getattr(row, "agent_configuration", None),
					caller_instance=getattr(row, "caller_instance", None),
				)
				wake_caller_if_any(row)
				_mark_resumed(row.name)
				frappe.db.commit()
				continue

			frappe.db.commit()
		except Exception:
			frappe.log_error(
				title=f"A2A internal reconcile failed: {row.name}", message=frappe.get_traceback()
			)


def _wake_a2a_caller(row) -> None:
	"""Resume the parked Service Task, or hand the answer to the agent suspended mid-turn on this delegation."""
	from one_bpmn.processa_engine.runtime.ai_jobs import enqueue_wait_resume

	if row.caller_wf_task_id:
		enqueue_wait_resume(row.caller_instance, row.caller_wf_task_id, row.name, "A2A Task")
		return
	_resume_waiting_agent(row)


def _resume_waiting_agent(row) -> None:
	"""Store the delegated answer on the suspended agent's checkpoint and resume it in the AI worker, as a human answer would."""
	import json

	from one_bpmn.processa_engine.agent_runtime import checkpoint as _checkpoint
	from one_bpmn.processa_engine.runtime.ai_jobs import ai_job_queue_of

	run = row.caller_agent_run
	if not (run and row.caller_instance):
		return
	if frappe.db.get_value("AI Agent Run", run, "status") != "Suspended":
		return

	task = frappe.get_doc("A2A Task", row.name)
	_checkpoint.store_human_result(run, _delegation_answer(task))

	payload = json.loads(frappe.db.get_value("AI Agent Run", run, "checkpoint") or "{}")
	frappe.enqueue(
		"one_bpmn.processa_engine.runtime.ai_jobs.run_parked_ai_task",
		queue=ai_job_queue_of(row.caller_instance),
		timeout=AI_AGENT_JOB_TIMEOUT,
		enqueue_after_commit=True,
		job_id=f"bpmn-ai-{row.caller_instance}-a2ares-{row.name}",
		deduplicate=True,
		instance_name=row.caller_instance,
		kind="human_resume",
		task_id=payload.get("wf_task_id") or row.wf_task_id or "",
		run_as_user="Administrator",
	)


def _delegation_answer(task) -> str:
	"""What the model is told the delegated agent said; a failure is reported in words."""
	if task.state == "completed":
		payload = frappe.parse_json(task.result or "{}") or {}
		answer = (
			payload.get("text")
			or task.status_message
			or "The other agent finished but sent no reply."
		)
		# A worker that ran out of turns still reports completed, so name the limit that stopped it.
		from one_bpmn.a2a import delegation

		return answer + delegation.limit_note(task.name)
	reason = task.error_message or "no reason given"
	return f"The other agent did not complete this ({task.state}): {reason}"


def _mark_resumed(a2a_task: str) -> None:
	"""Stamp resume_enqueued so the reconciler never hands the same finished task to the engine twice."""
	frappe.db.set_value("A2A Task", a2a_task, "resume_enqueued", 1, update_modified=False)
