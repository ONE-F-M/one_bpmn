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

	from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import (
		_enqueue_a2a_resume,
	)
	from one_bpmn.one_bpmn.integrations import a2a_client

	now = now_datetime()
	due = frappe.get_all(
		"A2A Task",
		filters={
			"direction": "Outbound",
			"state": ["in", ("submitted", "working", "auth-required")],
			"next_poll_at": ["<=", now],
		},
		fields=["name", "remote_agent", "remote_task_id", "instance", "wf_task_id", "deadline", "poll_attempts"],
		limit=100,
	)

	for row in due:
		try:
			remote = frappe.get_doc("A2A Remote Agent", row.remote_agent)
			attempts = cint(row.poll_attempts) + 1
			base = cint(remote.poll_base_interval) or 60
			ceiling = cint(remote.poll_max_interval) or 900
			# Claim before the network call.
			frappe.db.set_value(
				"A2A Task",
				row.name,
				{
					"poll_attempts": attempts,
					"last_polled_at": now,
					"next_poll_at": add_to_date(now, seconds=min(base * (2 ** (attempts - 1)), ceiling)),
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
	_enqueue_a2a_resume(row.instance, row.wf_task_id, row.name)
	frappe.db.commit()
