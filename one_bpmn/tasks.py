# Copyright (c) 2026, one-fm and contributors
# Scheduled tasks for BPMN timer event processing.
#
# Registered in hooks.py under scheduler_events.
# These run at minute-level intervals via Frappe's scheduler.

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime


# 1. Timer Start Events — create new instances on schedule


def process_timer_start_events():
	"""
	Evaluate all Timer Start Event configurations and start new BPMN
	Process Instances when their cron/cycle expression matches.

	Called every minute by the Frappe scheduler.

	For each active BPMN Process Model with a Timer start event:
	  1. Read the cron_expression from the BPMN Start Event Config row
	  2. Check if the current minute matches the cron expression
	  3. If yes, create and start a new BPMN Process Instance (unless
	     a duplicate-prevention check fails)

	Timer Start Events with timeDuration or timeDate are not supported
	(those only make sense for intermediate catch events, not start events).
	Only timeCycle (cron expressions) trigger repeated process instances.
	"""
	from croniter import croniter

	now = now_datetime()

	# New-style rows: trigger_type explicitly set to "Scheduler Event".
	new_style = frappe.get_all(
		"BPMN Start Event Config",
		filters={
			"trigger_type": "Scheduler Event",
			"parenttype": "BPMN Process Model",
			"cron_expression": ["!=", ""],
		},
		fields=["name", "parent", "cron_expression", "bpmn_element_id"],
	)
	# Legacy rows: created before trigger_type was introduced — event_type is
	# "Timer" but trigger_type has not been backfilled yet.  We omit the
	# trigger_type filter here so we reliably catch both NULL and empty-string
	# values without relying on MySQL IN-NULL semantics.
	legacy = frappe.get_all(
		"BPMN Start Event Config",
		filters={
			"event_type": "Timer",
			"parenttype": "BPMN Process Model",
			"cron_expression": ["!=", ""],
		},
		fields=["name", "parent", "cron_expression", "bpmn_element_id"],
	)
	# Merge and deduplicate by child-row name.
	seen = set()
	timer_configs_raw = []
	for cfg in new_style + legacy:
		if cfg.name not in seen:
			seen.add(cfg.name)
			timer_configs_raw.append(cfg)

	if not timer_configs_raw:
		return

	parent_names = list({cfg.parent for cfg in timer_configs_raw})
	active_models = set(
		frappe.get_all(
			"BPMN Process Model",
			filters={
				"name": ["in", parent_names],
				"is_active": 1,
			},
			pluck="name",
		)
	)

	timer_configs = [
		{
			"config_name": cfg.name,
			"model_name": cfg.parent,
			"cron_expression": cfg.cron_expression,
			"bpmn_element_id": cfg.bpmn_element_id,
		}
		for cfg in timer_configs_raw
		if cfg.parent in active_models
	]

	for cfg in timer_configs:
		try:
			cron_expr = cfg.cron_expression.strip()
			if not cron_expr:
				continue

			# croniter.match() checks if the given datetime matches the pattern.
			if not croniter.match(cron_expr, now):
				continue

			# Duplicate prevention: don't start if an Active instance already
			# exists for this model (with no context doc — timer-started
			# instances typically don't have a context document).
			# We check within the last 2 minutes to avoid race conditions.
			recent_cutoff = frappe.utils.add_to_date(now, minutes=-2)
			existing = frappe.db.exists(
				"BPMN Process Instance",
				{
					"process_model": cfg.model_name,
					"status": "Active",
					"started_at": (">=", recent_cutoff),
				},
			)
			if existing:
				continue

			_start_timer_instance(cfg.model_name)

		except Exception:
			frappe.log_error(
				title=f"BPMN Timer Start: failed for model {cfg.model_name}",
				message=frappe.get_traceback(),
			)


def _start_timer_instance(model_name: str):
	"""
	Create and start a new BPMN Process Instance triggered by a timer.

	Timer-started instances have no context document — they are
	standalone process executions triggered by the scheduler.
	"""
	model = frappe.get_doc("BPMN Process Model", model_name)

	if not model.serialized_spec:
		return

	instance = frappe.new_doc("BPMN Process Instance")
	instance.process_model = model_name
	instance.status = "Active"
	instance.initiated_by = "Administrator"
	instance.started_at = now_datetime()

	instance.insert(ignore_permissions=True)

	instance.start(
		initial_data={
			"triggered_by": "Timer",
			"trigger_type": "Timer Start Event",
		}
	)

	frappe.db.commit()


# 2. Timer Catch Events — resume waiting instances after timer elapses


def process_timer_catch_events():
	"""
	Check all Active BPMN Process Instances for WAITING timer tasks
	and resume execution if the timer has elapsed.

	Called every minute by the Frappe scheduler.

	SpiffWorkflow tracks timer state internally. The approach:
	  1. Find all Active instances
	  2. Restore the SpiffWorkflow engine
	  3. Call wf.refresh_waiting_tasks() — this checks all WAITING tasks
	     and transitions timer tasks to READY if their time has elapsed
	  4. If any tasks became READY, run the engine forward and save
	"""
	active_instances = frappe.get_all(
		"BPMN Process Instance",
		filters={"status": "Active"},
		pluck="name",
	)

	for instance_name in active_instances:
		try:
			_refresh_timer_tasks(instance_name)
		except Exception:
			frappe.log_error(
				title=f"BPMN Timer Catch: failed for instance {instance_name}",
				message=frappe.get_traceback(),
			)


def _refresh_timer_tasks(instance_name: str):
	"""
	Restore a process instance's LIVE engine state, refresh waiting timer
	tasks, and if any became READY, run the engine forward and save.

	Field contract (same as start()/advance()): ``workflow_state`` holds the
	live serialized workflow; ``serialized_spec`` is the compiled spec
	snapshot — a pristine, never-run workflow plus the compile-time
	extension dicts. This function previously restored the SNAPSHOT as if
	it were live state: at best a silent no-op (a fresh workflow has no
	waiting timers, so timer catch events never actually resumed), and had
	a fresh copy ever produced fired timers it would have re-run the
	process from scratch and overwritten the real progress.
	"""
	from SpiffWorkflow.util.task import TaskState
	from one_bpmn.one_bpmn import engine as bpmn_engine
	import json

	instance = frappe.get_doc("BPMN Process Instance", instance_name)

	if not instance.workflow_state:
		return

	spec_data = (
		json.loads(instance.serialized_spec)
		if isinstance(instance.serialized_spec, str)
		else (instance.serialized_spec or {})
	) or {}

	workflow_state = (
		json.loads(instance.workflow_state)
		if isinstance(instance.workflow_state, str)
		else instance.workflow_state
	)

	wf = bpmn_engine.restore_workflow(
		workflow_state=workflow_state,
		context_doctype=instance.context_doctype,
		context_docname=instance.context_docname,
		script_task_extensions=spec_data.get("script_task_extensions"),
		initiated_by=instance.initiated_by or "Administrator",
	)

	waiting_before = len(wf.get_tasks(state=TaskState.WAITING))

	# Refresh — this updates timer events that have elapsed
	wf.refresh_waiting_tasks()

	waiting_after = len(wf.get_tasks(state=TaskState.WAITING))

	# If any timers fired, run the engine forward through the full dispatch
	# pipeline (gated ad-hoc stepping, service/AI dispatch, activity
	# logging) — exactly like advance() does after a user task completes.
	if waiting_after < waiting_before:
		instance._service_task_extensions = spec_data.get("service_task_extensions", {})
		instance._user_task_extensions = spec_data.get("user_task_extensions", {})
		try:
			instance._refresh_user_task_extensions_from_model()
		except Exception:
			pass

		frappe.flags.bpmn_engine_action = True
		try:
			instance._run_engine(wf)
		finally:
			frappe.flags.bpmn_engine_action = False

		# Persist the LIVE state to workflow_state; serialized_spec (the
		# compiled snapshot) is never touched here.
		bpmn_engine.clean_doc_from_wf_data(wf)
		instance.workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))

		instance._sync_active_tasks(wf)
		instance._check_completion(wf)

		instance.save(ignore_permissions=True)
		if not frappe.flags.in_test:
			frappe.db.commit()

		# Publish realtime for auto-refresh
		frappe.publish_realtime(
			"bpmn_instance_updated",
			{
				"instance_name": instance_name,
				"status": instance.status,
			},
			after_commit=True,
			user="all",
		)

		if instance.context_doctype and instance.context_docname:
			frappe.publish_realtime(
				"doc_update",
				{
					"modified": str(now_datetime()),
					"doctype": instance.context_doctype,
					"name": instance.context_docname,
				},
				doctype=instance.context_doctype,
				docname=instance.context_docname,
				after_commit=True,
			)


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
	from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import (
		_enqueue_a2a_resume,
	)
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
				_enqueue_a2a_resume(row.instance, row.wf_task_id, row.name)
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
				_enqueue_a2a_resume(row.instance, row.wf_task_id, row.name)
			elif state == "input-required":
				# Stop polling and ask a person. The remote is waiting on us.
				frappe.db.set_value(
					"A2A Task", row.name, {"state": "input-required"}, update_modified=True
				)
				if row.instance:
					instance = frappe.get_doc("BPMN Process Instance", row.instance)
					instance._on_a2a_input_required(row.name, a2a_client.remote_text(result))
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
			_enqueue_a2a_resume(row.instance, row.wf_task_id, row.name)
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
				allowed = max(
					0, int((frappe.utils.get_datetime(row.deadline) - started).total_seconds() // 60)
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
	from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import (
		_enqueue_a2a_resume,
	)
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
	_enqueue_a2a_resume(row.instance, row.wf_task_id, row.name)
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
			if row.deadline and now_datetime() > frappe.utils.get_datetime(row.deadline):
				task.db_set(
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
				_wake_caller_if_any(row)
				_mark_resumed(row.name)
				frappe.db.commit()
				continue

			local.refresh(task)
			task.reload()
			if task.state in terminal:
				_wake_caller_if_any(row)
				_mark_resumed(row.name)
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
	from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import (
		_enqueue_a2a_resume,
	)

	if row.caller_wf_task_id:
		_enqueue_a2a_resume(row.caller_instance, row.caller_wf_task_id, row.name)
		return
	_resume_waiting_agent(row)


def _resume_waiting_agent(row) -> None:
	"""Give a delegated answer to the agent that is suspended waiting for it.

	Mirrors what completing a human task does — store the result on the
	checkpoint, then resume in the AI worker — because to the agent these are
	the same event: the tool call it paused on finally has an answer.
	"""
	import json

	from one_bpmn.agents import checkpoint as _checkpoint

	run = row.caller_agent_run
	if not (run and row.caller_instance):
		return
	if frappe.db.get_value("AI Agent Run", run, "status") != "Suspended":
		return  # already resumed or failed — nothing is waiting

	task = frappe.get_doc("A2A Task", row.name)
	_checkpoint.store_human_result(run, _delegation_answer(task))

	payload = json.loads(frappe.db.get_value("AI Agent Run", run, "checkpoint") or "{}")
	frappe.enqueue(
		"one_bpmn.one_bpmn.doctype.bpmn_process_instance"
		".bpmn_process_instance.run_parked_ai_task",
		queue="bpmn_ai_agent",
		timeout=600,
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
	"""Belt and braces beside _enqueue_a2a_resume's own stamp: the reconciler
	must never hand the same finished task to the engine twice, even if the
	enqueue helper changes or fails."""
	frappe.db.set_value("A2A Task", a2a_task, "resume_enqueued", 1, update_modified=False)
