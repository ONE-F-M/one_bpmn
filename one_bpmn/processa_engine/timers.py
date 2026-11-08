# Copyright (c) 2026, one-fm and contributors
"""Scheduler jobs for Timer Start Events, Timer Catch Events and stranded AI steps."""

import time
from datetime import datetime

import frappe
from frappe.utils import add_to_date, get_datetime, get_system_timezone, now_datetime

from one_bpmn.processa_engine.agent_runtime.job_limits import AI_AGENT_JOB_TIMEOUT
from one_bpmn.processa_engine.runtime.active_tasks import check_completion, sync_active_tasks
from one_bpmn.processa_engine.runtime.common import log_task, refresh_user_task_extensions_from_model
from one_bpmn.processa_engine.runtime.engine_loop import run_engine


# Timer Start Events


def timer_start_is_due(expression: str, now, last_started_at=None) -> bool:
	"""Whether a Timer Start Event's cycle has come due since it last started a run.

	The timeCycle is a cron expression or an ISO 8601 repeating interval; anything else raises.
	"""
	slot = _latest_slot(expression, now)
	if slot is None:
		return False

	if last_started_at is None:
		return slot == now.replace(second=0, microsecond=0)

	return slot > get_datetime(last_started_at)


def _latest_slot(expression: str, now):
	"""The most recent scheduled minute at or before ``now``, or None if there is none."""
	expression = (expression or "").strip()
	if not expression:
		return None

	if expression.upper().startswith("R"):
		return _iso_latest_slot(expression, now)

	from croniter import croniter

	minute = now.replace(second=0, microsecond=0)
	return croniter(expression, add_to_date(minute, minutes=1)).get_prev(datetime)


def _iso_latest_slot(expression: str, now):
	"""Latest ``start + n x period`` at or before ``now``, as a naive local minute."""
	from datetime import timezone
	from zoneinfo import ZoneInfo

	from one_bpmn.processa_engine.engine import TimerEventDefinition

	cycles, start, period = TimerEventDefinition.parse_iso_recurring_interval(expression)
	seconds = period.total_seconds()
	if seconds < 60:
		# The scheduler itself only runs every minute; deploy rejects these.
		return None

	local_tz = ZoneInfo(get_system_timezone())
	now_utc = now.replace(tzinfo=local_tz).astimezone(timezone.utc)
	elapsed = (now_utc - start).total_seconds()
	if elapsed < 0:
		return None

	n = int(elapsed // seconds)
	if cycles >= 0:
		n = min(n, cycles - 1)

	occurrence = (start + n * period).astimezone(local_tz)
	return occurrence.replace(second=0, microsecond=0, tzinfo=None)


def process_timer_start_events():
	"""Every minute: start a BPMN Process Instance for each active model whose timer start cycle is due.

	Only timeCycle is supported on start events; timeDuration and timeDate are not.
	"""
	now = now_datetime()

	new_style = frappe.get_all(
		"BPMN Start Event Config",
		filters={
			"trigger_type": "Scheduler Event",
			"parenttype": "BPMN Process Model",
			"cron_expression": ["!=", ""],
		},
		fields=["name", "parent", "cron_expression", "bpmn_element_id", "last_started_at"],
	)
	# Timer rows without a trigger_type match here, whether it is NULL or empty.
	legacy = frappe.get_all(
		"BPMN Start Event Config",
		filters={
			"event_type": "Timer",
			"parenttype": "BPMN Process Model",
			"cron_expression": ["!=", ""],
		},
		fields=["name", "parent", "cron_expression", "bpmn_element_id", "last_started_at"],
	)
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
			"last_started_at": cfg.last_started_at,
		}
		for cfg in timer_configs_raw
		if cfg.parent in active_models
	]

	for cfg in timer_configs:
		try:
			if not timer_start_is_due(cfg["cron_expression"], now, cfg["last_started_at"]):
				continue

			# Skip when an Active instance of this model started in the last 2 minutes.
			recent_cutoff = frappe.utils.add_to_date(now, minutes=-2)
			existing = frappe.db.exists(
				"BPMN Process Instance",
				{
					"process_model": cfg["model_name"],
					"status": "Active",
					"started_at": (">=", recent_cutoff),
				},
			)
			if existing:
				continue

			_start_timer_instance(cfg["model_name"], cfg["config_name"], now)

		except Exception:
			# An escaping exception would roll back every instance this sweep started.
			frappe.log_error(
				title=f"BPMN Timer Start: failed for model {cfg['model_name']}",
				message=frappe.get_traceback(),
			)


def _start_timer_instance(model_name: str, config_name: str, now):
	"""Create and start a BPMN Process Instance with no context document, triggered by a timer."""
	model = frappe.get_doc("BPMN Process Model", model_name)

	if not model.serialized_spec:
		return

	instance = frappe.new_doc("BPMN Process Instance")
	instance.process_model = model_name
	instance.status = "Active"
	instance.initiated_by = "Administrator"
	instance.started_at = now_datetime()

	instance.insert(ignore_permissions=True)  # scheduler starts the instance as Administrator

	instance.start(
		initial_data={
			"triggered_by": "Timer",
			"trigger_type": "Timer Start Event",
		}
	)

	frappe.db.set_value(
		"BPMN Start Event Config", config_name, "last_started_at", now, update_modified=False
	)
	frappe.db.commit()


# Timer Catch Events


def process_timer_catch_events():
	"""Every minute: resume Active BPMN Process Instances whose waiting timer tasks have elapsed."""
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
	"""Restore the live workflow_state, refresh waiting timers, and run the engine forward if any fired.

	serialized_spec is the compiled snapshot and only supplies the extension dicts.
	"""
	from one_bpmn.processa_engine import engine as bpmn_engine
	from one_bpmn.processa_engine.engine import TaskState
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
		instance=instance,
	)

	waiting_before = len(wf.get_tasks(state=TaskState.WAITING))

	wf.refresh_waiting_tasks()

	waiting_after = len(wf.get_tasks(state=TaskState.WAITING))

	# A fired timer runs the full dispatch pipeline, as advance() does after a user task.
	if waiting_after < waiting_before:
		instance._service_task_extensions = spec_data.get("service_task_extensions", {})
		instance._user_task_extensions = spec_data.get("user_task_extensions", {})
		try:
			refresh_user_task_extensions_from_model(instance)
		except Exception:
			pass

		previous_flag = frappe.flags.bpmn_engine_action
		frappe.flags.bpmn_engine_action = True
		try:
			run_engine(instance, wf)
		finally:
			frappe.flags.bpmn_engine_action = previous_flag

		bpmn_engine.clean_doc_from_wf_data(wf)
		instance.workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))

		sync_active_tasks(instance, wf)
		check_completion(instance, wf)

		instance.save(ignore_permissions=True)  # scheduler job, no session user
		if not frappe.flags.in_test:
			frappe.db.commit()

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


# Stranded AI steps

STRANDED_AI_STEP_MINUTES = 10
WATCHDOG_MAX_REQUEUES = 2


def requeue_stranded_ai_steps():
	"""Every five minutes: enqueue the job of a parked AI step that has none, twice at most, then error the instance."""
	names = frappe.get_all(
		"BPMN Process Instance", filters={"status": "Active", "waiting_for_ai": 1}, pluck="name"
	)
	for name in names:
		_requeue_stranded_steps(name)
		frappe.db.commit()


def _requeue_stranded_steps(instance_name: str) -> None:
	frappe.db.rollback()  # ends the snapshot, so the row lock below sees the current row
	if _instance_job_is_running(instance_name):
		return
	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	if instance.status != "Active" or not instance.waiting_for_ai:
		return
	for unit in instance.get_parked_ai_units():
		minutes = int((time.time() - unit["since"]) / 60)
		if unit.get("waits_on") or minutes < STRANDED_AI_STEP_MINUTES or _a_job_is_alive(instance, unit):
			continue
		_requeue_or_error(instance, unit, minutes)


def _instance_job_is_running(instance_name: str) -> bool:
	"""True when run_parked_ai_task holds the instance row, which means its job is running."""
	table = frappe.qb.DocType("BPMN Process Instance")
	row = (
		frappe.qb.from_(table)
		.select(table.name)
		.where(table.name == instance_name)
		.for_update(skip_locked=True)
	).run()
	frappe.db.rollback()  # releases the lock the check took
	return not row


def _a_job_is_alive(instance, unit: dict) -> bool:
	"""Whether the unit's own job, one of its retries or an earlier re-queue is still queued or started."""
	from frappe.utils.background_jobs import is_job_enqueued

	from one_bpmn.processa_engine.runtime.ai_jobs import job_retry_cap

	base = f"bpmn-ai-{instance.name}-{unit['task_id']}"
	retries = job_retry_cap(instance, unit["kind"], unit["task_id"])
	job_ids = [
		base,
		*(f"{base}-r{n}" for n in range(1, retries + 1)),
		*(f"{base}-watchdog-{n}" for n in range(1, WATCHDOG_MAX_REQUEUES + 1)),
	]
	return any(is_job_enqueued(job_id) for job_id in job_ids)


def _requeue_or_error(instance, unit: dict, minutes: int) -> None:
	from one_bpmn.processa_engine.runtime.ai_jobs import ai_job_queue_of

	done = frappe.db.count(
		"BPMN Activity Log",
		{
			"instance": instance.name,
			"action": "Retried",
			"task_id": ["like", f"{unit['task_id']}::watchdog-%"],
		},
	)
	if done >= WATCHDOG_MAX_REQUEUES:
		_error_stranded_instance(instance, unit, minutes)
		return
	attempt = done + 1
	frappe.enqueue(
		"one_bpmn.processa_engine.runtime.ai_jobs.run_parked_ai_task",
		queue=ai_job_queue_of(instance.name),
		timeout=AI_AGENT_JOB_TIMEOUT,
		enqueue_after_commit=True,
		job_id=f"bpmn-ai-{instance.name}-{unit['task_id']}-watchdog-{attempt}",
		deduplicate=True,
		instance_name=instance.name,
		kind=unit["kind"],
		task_id=unit["task_id"],
		run_as_user=instance.initiated_by,
		attempt=0,
	)
	log_task(
		instance,
		task_id=f"{unit['task_id']}::watchdog-{attempt}",
		task_name=unit["label"],
		action="Retried",
		data={"stranded_minutes": minutes, "requeue": attempt},
	)


def _error_stranded_instance(instance, unit: dict, minutes: int) -> None:
	"""Marks the instance Errored the way an exhausted AI job does, leaving the task parked for a manual retry."""
	frappe.db.set_value("BPMN Process Instance", instance.name, "status", "Errored")
	frappe.db.set_value("BPMN Process Instance", instance.name, "waiting_for_ai", 0, update_modified=False)
	error = f"No job ran for '{unit['label']}' in {minutes} minutes, after {WATCHDOG_MAX_REQUEUES} re-queues."
	log_task(
		instance,
		task_id=unit["task_id"],
		task_name=f"AI job ({unit['kind']})",
		action="Errored",
		data={"kind": unit["kind"], "attempts": WATCHDOG_MAX_REQUEUES, "error": error},
	)
	frappe.log_error(title=f"BPMN stranded AI step: {instance.name}", message=error)
