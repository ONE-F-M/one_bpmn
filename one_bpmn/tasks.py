# Copyright (c) 2026, one-fm and contributors
# Scheduled A2A, conversation, memory and model jobs.
#
# Registered in hooks.py under scheduler_events.

import frappe

from one_bpmn.processa_engine.agent_runtime.job_limits import AI_AGENT_JOB_TIMEOUT
from frappe import _
from frappe.utils import add_to_date, now_datetime

from one_bpmn.processa_engine.runtime.remote_waits import on_a2a_input_required


# 3. Stale chat instance cleanup — close abandoned chat conversations


# A chat instance's `modified` timestamp advances on every engine pass
# (message received, AI reply, close). An instance untouched for this many
# hours is an abandoned conversation whose panel never sent the close call
# (tab closed mid-session, or a fire-and-forget close request that died).
STALE_CHAT_HOURS = 24


def close_stale_chat_instances():
	"""
	Deliver ``ChatConversation_Close_Action`` to chat-driven BPMN Process
	Instances that have been idle past ``STALE_CHAT_HOURS``, so their diagram
	runs the close branch (Cleanup → Conversation Ended) and completes.

	Called hourly by the Frappe scheduler.

	Chat process maps park at an event-based gateway waiting for the next
	user message or a close message. The close message normally comes from
	the UI (end_chat_conversation) when the panel closes — this sweep is the
	backstop for instances the UI orphaned.

	Instances mid-engine-pass or waiting on an AI job are skipped; if one is
	parked somewhere other than the close catch event (e.g. suspended for
	human input), the "no task waiting" error is swallowed and it is left
	untouched.

	The message is delivered to each stale instance directly — NOT via
	close_conversation(), whose by-conversation get_value lookup picks an
	arbitrary Active instance when several share one conversation and could
	close a fresh sibling instead of the stale one.
	"""
	cutoff = add_to_date(now_datetime(), hours=-STALE_CHAT_HOURS)

	stale = frappe.get_all(
		"BPMN Process Instance",
		filters={
			"status": "Active",
			"context_doctype": "Chat Conversation",
			"engine_in_progress": 0,
			"waiting_for_ai": 0,
			"modified": ["<", cutoff],
		},
		pluck="name",
	)

	for instance_name in stale:
		try:
			instance = frappe.get_doc("BPMN Process Instance", instance_name)
			instance.receive_message("ChatConversation_Close_Action", payload={})
			if instance.context_docname:
				from one_bpmn.api.skill_tools import clear_conversation_skills
				clear_conversation_skills(instance.context_docname)
		except frappe.ValidationError:
			pass  # not parked at the close catch event — leave it alone
		except Exception:
			frappe.log_error(
				title=f"BPMN stale chat cleanup failed: {instance_name}",
				message=frappe.get_traceback(),
			)


# 4. A2A delegated tasks — poll remote agents and wake parked processes


def poll_a2a_tasks():
	"""WI-001933: check on delegated A2A tasks and wake what is waiting.

	Called every minute by the scheduler. Claim-first: next_poll_at is
	pushed forward BEFORE the network call, so a slow remote cannot have
	two pollers on the same task. Per-task exponential backoff keeps a
	long delegation cheap, and a task past its deadline is cancelled
	best-effort and failed through the normal BPMN error path.
	"""
	from frappe.utils import cint

	from one_bpmn.agents.a2a.push import PUSH_RECONCILE_SECONDS
	from one_bpmn.processa_engine.runtime.ai_jobs import enqueue_wait_resume
	from one_bpmn.one_bpmn.integrations import a2a_client

	now = now_datetime()
	# Same-site delegations first: no network involved, so they are cheap and
	# should never wait behind a remote's timeout.
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
			# A remote that pushes gets reconciled, not chased: the callback is
			# the primary signal and this is only the safety net that catches a
			# dropped one.
			if row.push_registered:
				interval = PUSH_RECONCILE_SECONDS
			else:
				interval = min(base * (2 ** (attempts - 1)), ceiling)
			# Claim before the network call.
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
				continue  # nothing to poll yet — the send did not return a task id

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
				# Stop polling and ask a person. The remote is waiting on us.
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
			# Revoked mid-flight: fail closed rather than keep talking to it.
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


def _wake_caller_if_any(row) -> None:
	"""Wake the caller only when there is one.

	The reconciler now also visits top-level delegations, which have no parked
	step and no suspended agent. Guarded here rather than relying on the wake
	path to no-op, so "nobody is waiting" stays an explicit case.
	"""
	if row.caller_wf_task_id or row.caller_agent_run:
		_wake_a2a_caller(row)


def _retry_delegation(task) -> bool:
	"""Run the worker again if this failed delegation has an attempt left.

	Returns True when a retry was started (the caller must NOT be woken — the
	delegation is live again), False when it is genuinely finished, having first
	escalated if the attempts ran out.
	"""
	from one_bpmn.agents.a2a import delegation, execute

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
			# Back to submitted and the error cleared: the row is one delegation
			# across all its attempts, so a stale failure must not linger on it.
			task.db_set(
				{"state": "submitted", "error_message": None, "error_code": None},
				update_modified=True,
			)
			task.reload()
			frappe.logger("one_bpmn").info(
				f"A2A delegation {task.name}: retrying {task.agent_configuration} "
				f"(attempt {attempt})"
			)
			# fresh=True: run the worker AGAIN, rather than reattaching to what the
			# last attempt left behind. Without it the attempt was counted and
			# nothing re-ran.
			execute.run_for_task(task, config, payload.get("instruction") or "", fresh=True)
			task.reload()
			return task.state not in ("failed", "rejected")

		# No attempt left. Escalate once through the same seam as every other
		# limit, then let the caller be woken with the failure.
		delegation.retries_exhausted(task.name)
		return False
	except Exception:
		frappe.log_error(
			title=f"A2A delegation retry failed ({task.name})", message=frappe.get_traceback()
		)
		return False


def _escalate_deadline(task_name: str, agent_configuration=None, caller_instance=None) -> None:
	"""A delegated task ran out of time — tell the person who owns it.

	WI-002053. Both deadline paths used to set state="timed-out", wake the
	caller and move on, so a worker abandoned at its deadline was invisible
	unless somebody happened to read the row. The escalation is idempotent per
	breach (delegation.notified_at), which matters because this runs on a
	schedule and would otherwise re-alert on every tick.
	"""
	from one_bpmn.agents.a2a import delegation

	# Both numbers come off the row itself rather than the agent's config: the
	# deadline that was APPLIED is creation → deadline, which already accounts
	# for a per-step timeout_minutes override. Reading the config instead would
	# report a limit that was not the one in force.
	allowed = 0
	ran_for = 0
	try:
		row = frappe.db.get_value(
			"A2A Task", task_name, ["creation", "deadline"], as_dict=True
		)
		if row and row.creation:
			started = frappe.utils.get_datetime(row.creation)
			if row.deadline:
				# ROUNDED, not floored. The deadline is stamped a fraction of a
				# second after `creation` is written, so a genuine one-minute
				# allowance measures 59.997 seconds and floors to ZERO — which
				# recorded limit_value 0 and printed "its deadline had already
				# passed", the wording meant for a deadline moved into the past by
				# hand. A one-minute deadline is the shortest a person can set and
				# the likeliest to be used for testing, so it was also the likeliest
				# to be misreported.
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
			# A deadline moved into the past by hand — which is how a breach gets
			# tested — computes as zero allowance, and "allowed 0 minute(s)" reads
			# like a misconfiguration rather than an expired deadline.
			f"Its deadline had already passed; it had been running for about {ran_for} minute(s)."
			if allowed <= 0
			else f"It was allowed {allowed} minute(s) and had been running for about "
			f"{ran_for} when the deadline passed."
		)
		# The deadline covers every attempt, so an alert that names one elapsed
		# time has to say how many attempts fitted inside it — otherwise
		# "running for 30 minutes" reads as one long attempt when it was three
		# short ones.
		+ delegation.attempts_note(task_name),
		instance=caller_instance,
		worker_agent=agent_configuration,
	)


def _time_out_task(row, remote) -> None:
	"""Past the deadline: tell the remote to stop if it will listen, then
	fail through the normal BPMN error path."""
	from one_bpmn.processa_engine.runtime.ai_jobs import enqueue_wait_resume
	from one_bpmn.one_bpmn.integrations import a2a_client

	if row.remote_task_id:
		try:
			a2a_client.tasks_cancel(remote, row.remote_task_id)
		except Exception:
			pass  # best effort — the deadline stands either way
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
	"""Same-site delegations (WI-001933): the target agent runs in this bench,
	so there is nothing to call — just re-derive the state from the run or
	instance doing the work and wake the parked step when it settles.

	Deadlines still apply: a local agent can hang on a human task or a stuck
	map exactly like a remote can.
	"""
	from frappe.utils import cint

	from one_bpmn.agents.a2a import local

	terminal = ("completed", "canceled", "failed", "rejected", "timed-out")
	# Deliberately NOT filtered by state: a local agent can finish between two
	# checks, and such a row is already terminal while its caller is still
	# parked. resume_enqueued is what says "this step has been woken".
	#
	# Two kinds of caller can be waiting, and both must be picked up:
	#   caller_wf_task_id — a parked Service Task on the diagram;
	#   caller_agent_run  — an AGENT suspended mid-turn, because it delegated
	#                       from inside a tool call (WI-001933). It has no
	#                       parked step of its own, so filtering on
	#                       caller_wf_task_id alone left it waiting forever.
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
			# A top-level delegation has NEITHER — nobody local is parked on it.
			# It was therefore never visited, so its state never advanced past
			# "working" even after its instance had finished, and anything
			# polling the row waited forever. Seen with an A2A-startable
			# orchestrator: instance Completed, task still "working" through
			# 150s of polling; one manual refresh_state() settled it at once.
			# It has an instance, so it has a state that can be derived.
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
					# Local work is cheap to check, so the interval stays short
					# and flat rather than backing off into minutes.
					"next_poll_at": add_to_date(now, seconds=30),
				},
				update_modified=False,
			)

			task = frappe.get_doc("A2A Task", row.name)

			# A failed worker may have an attempt left. Checked BEFORE the
			# terminal branch below, because "failed" is terminal and would
			# otherwise wake the caller with a failure that was never final.
			if task.state == "failed" and _retry_delegation(task):
				frappe.db.commit()
				continue

			if task.state in terminal:
				# Finished in the gap between checks — wake the caller now.
				_wake_caller_if_any(row)
				_mark_resumed(row.name)
				frappe.db.commit()
				continue

			# Ask the worker how it actually got on BEFORE judging the clock. The
			# task row lags: nothing writes "completed" onto it until something
			# looks, so a worker that finished perfectly well still reads
			# "working" here. Judging the deadline first threw finished work away.
			#
			# Seen exactly once and it was expensive: a one-minute deadline, a
			# worker that finished at 13:05 having built the connector and written
			# a full report, and a reconciler that did not run until 13:12 —
			# whereupon it marked the task timed-out, discarded the result, and
			# had the orchestrator tell a person "the Connector Agent timed out
			# before finishing this one", which was untrue. The work existed.
			#
			# A deadline is for work that is STILL RUNNING. Finished is finished,
			# however late anyone looked.
			local.refresh(task)
			task.reload()
			if task.state in terminal:
				_wake_caller_if_any(row)
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
				# Stop the worker advancing any further. It cannot interrupt a pass
				# already executing — nothing can — but without this the worker
				# runs on to the end of its map doing work nobody will ever read,
				# which is how a timed-out delegation still finished its job.
				from one_bpmn.agents.a2a import execute

				execute.retire_instance(task.instance)
				_escalate_deadline(
					row.name,
					agent_configuration=getattr(row, "agent_configuration", None),
					caller_instance=getattr(row, "caller_instance", None),
				)
				_wake_caller_if_any(row)
				_mark_resumed(row.name)
				frappe.db.commit()
				continue

			frappe.db.commit()
		except Exception:
			frappe.log_error(
				title=f"A2A internal reconcile failed: {row.name}", message=frappe.get_traceback()
			)


def _wake_a2a_caller(row) -> None:
	"""Wake whatever is waiting on a finished delegation.

	Two shapes of caller, one entry point so every wake path (finished early,
	timed out, finished on this check) treats them alike:

	- a parked Service Task on the diagram → resume that step;
	- an agent suspended mid-turn because it delegated from inside a tool call
	  → hand the answer to its checkpoint and resume the agent.
	"""
	from one_bpmn.processa_engine.runtime.ai_jobs import enqueue_wait_resume

	if row.caller_wf_task_id:
		enqueue_wait_resume(row.caller_instance, row.caller_wf_task_id, row.name, "A2A Task")
		return
	_resume_waiting_agent(row)


def _resume_waiting_agent(row) -> None:
	"""Give a delegated answer to the agent that is suspended waiting for it.

	Mirrors what completing a human task does — store the result on the
	checkpoint, then resume in the AI worker — because to the agent these are
	the same event: the tool call it paused on finally has an answer.
	"""
	import json

	from one_bpmn.processa_engine.agent_runtime import checkpoint as _checkpoint
	from one_bpmn.processa_engine.runtime.ai_jobs import ai_job_queue_of

	run = row.caller_agent_run
	if not (run and row.caller_instance):
		return
	if frappe.db.get_value("AI Agent Run", run, "status") != "Suspended":
		return  # already resumed or failed — nothing is waiting

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
		# The agent resumes through its checkpoint exactly as it does after a
		# person answers; only the source of the answer differs.
		kind="human_resume",
		task_id=payload.get("wf_task_id") or row.wf_task_id or "",
		run_as_user="Administrator",
	)


def _delegation_answer(task) -> str:
	"""What the model is told the delegated agent said.

	A failure is reported in words rather than hidden: the agent asked another
	agent to do something and deserves to know it did not happen, so it can
	say so or try something else.
	"""
	if task.state == "completed":
		payload = frappe.parse_json(task.result or "{}") or {}
		answer = (
			payload.get("text")
			or task.status_message
			or "The other agent finished but sent no reply."
		)
		# A worker that ran out of turns still comes back "completed" — it
		# finished its run, it just never finished the WORK. The delegation row
		# knows which limit stopped it, so say so here rather than leaving the
		# model to guess from an empty answer.
		from one_bpmn.agents.a2a import delegation

		return answer + delegation.limit_note(task.name)
	reason = task.error_message or "no reason given"
	return f"The other agent did not complete this ({task.state}): {reason}"


def _mark_resumed(a2a_task: str) -> None:
	"""Belt and braces beside enqueue_wait_resume's own stamp: the reconciler
	must never hand the same finished task to the engine twice, even if the
	enqueue helper changes or fails."""
	frappe.db.set_value("A2A Task", a2a_task, "resume_enqueued", 1, update_modified=False)


def sweep_conversation_retention():
	"""Daily: archive or delete chat conversations idle past their TTL.

	Off unless an administrator sets a TTL on Processa Settings, so a site that
	has not asked for retention does nothing beyond one settings read.
	"""
	from one_bpmn.agents.memory import retention

	try:
		result = retention.sweep_expired_conversations()
		if result.get("swept"):
			frappe.logger("one_bpmn").info(
				f"Conversation retention: {result['action']}d {result['swept']} conversation(s)"
			)
	except Exception:
		frappe.log_error(
			title="Conversation retention sweep failed", message=frappe.get_traceback()
		)


def apply_due_model_rates():
	"""Daily: apply any model rate whose effective date has passed.

	Folding pricing onto AI Model left one rate per model and no date, so a
	published price rise had nowhere to be recorded in advance and depended on
	somebody remembering it. The catalogue carries the dated changes; this is
	what makes them happen. A no-op on any day nothing is due, and it will not
	touch a rate that does not still match the exact published one it replaces.
	"""
	from one_bpmn.one_bpmn.patches.v1_0.seed_ai_model_catalogue import apply_due_rates

	try:
		for line in apply_due_rates():
			frappe.logger("one_bpmn").info(f"AI Model rate applied: {line}")
	except Exception:
		frappe.log_error(title="Model rate update failed", message=frappe.get_traceback())


def compact_idle_conversations():
	"""Hourly: the TIME trigger for conversation compaction.

	The count and turn-boundary triggers hang off the chat message hook, but an
	idle conversation by definition produces no messages — so the one trigger
	that cannot be a hook is a sweep. It queues exactly the same background job
	the other two do.

	Does nothing at all unless some agent has an idle threshold configured.
	"""
	from one_bpmn.agents.memory import compaction_triggers

	try:
		result = compaction_triggers.sweep_idle_conversations()
		if result.get("queued"):
			frappe.logger("one_bpmn").info(
				f"Conversation compaction: queued {result['queued']} of "
				f"{result['considered']} idle conversations"
			)
	except Exception:
		frappe.log_error(
			title="Conversation compaction: idle sweep failed",
			message=frappe.get_traceback(),
		)


def chase_unanswered_clarifications():
	"""Hourly: nudge a question nobody has answered, then raise it.

	WI-002050. It never answers the question. Every source on human-in-the-loop
	work says the same thing — do not block forever, and do not proceed on a
	timeout — so this does the first half (somebody is told) and deliberately
	not the second (nothing is assumed). The agent stays blocked, which is the
	whole point of having asked.
	"""
	from one_bpmn.agents import clarification

	try:
		result = clarification.chase_unanswered()
		if result.get("reminded") or result.get("escalated"):
			frappe.logger("one_bpmn").info(
				f"AI clarifications: reminded {result['reminded']}, escalated {result['escalated']}"
			)
	except Exception:
		frappe.log_error(
			title="AI Clarification: chasing unanswered questions failed",
			message=frappe.get_traceback(),
		)


def check_ai_model_credentials():
	"""WI-002191: every 15 minutes. Re-checks every enabled model's key — a
	pass lifts the block on a model that was Unhealthy, a credential failure
	marks one nobody has tried to run yet — then alerts once per model per
	distinct problem. Probe first, so an alert describes the current state."""
	from one_bpmn.agents import model_health

	model_health.probe_enabled_models()
	model_health.alert_unhealthy_models()


def prune_ai_memory():
	"""Nightly. Retires decayed, never-corroborated and minor aged memories by
	setting expires_on, with the reason in metadata. Thresholds live on
	Processa Settings, AI Memory section; the rows stay for audit."""
	from one_bpmn.agents.memory.prune import prune_memories

	prune_memories()
def check_ai_memory_volume():
	"""Daily. Tells the platform team when AI Memory has grown past the point
	where exact (index-free) semantic ranking should be reconsidered. The
	thresholds live on Processa Settings, AI Memory section."""
	from one_bpmn.agents.memory.volume_alert import check_volume

	check_volume()
