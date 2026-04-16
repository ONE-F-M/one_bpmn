# Copyright (c) 2026, one-fm and contributors
# Scheduled tasks for BPMN timer event processing.
#
# Registered in hooks.py under scheduler_events.
# These run at minute-level intervals via Frappe's scheduler.

import frappe
from frappe import _
from frappe.utils import now_datetime


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

	timer_configs_raw = frappe.get_all(
		"BPMN Start Event Config",
		filters={
			"event_type": "Timer",
			"parenttype": "BPMN Process Model",
			"cron_expression": ["!=", ""],
		},
		fields=["name", "parent", "cron_expression", "bpmn_element_id"],
	)

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
		frappe.logger("one_bpmn").warning(f"Timer Start: model {model_name} has no compiled spec — skipping")
		return

	instance = frappe.new_doc("BPMN Process Instance")
	instance.process_model = model_name
	instance.status = "Active"
	instance.initiated_by = "Administrator"
	instance.started_at = now_datetime()

	# no context doc for timer-start instances
	if model.trigger_doctype:
		instance.context_doctype = model.trigger_doctype

	instance.insert(ignore_permissions=True)

	instance.start(
		initial_data={
			"triggered_by": "Timer",
			"trigger_type": "Timer Start Event",
		}
	)

	frappe.logger("one_bpmn").info(
		f"BPMN Timer Start: created instance {instance.name} for model {model_name}"
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
	Restore a process instance, refresh waiting timer tasks, and if any
	became READY, run the engine forward and save.
	"""
	from SpiffWorkflow.util.task import TaskState
	from one_bpmn.one_bpmn import engine as bpmn_engine
	import json

	instance = frappe.get_doc("BPMN Process Instance", instance_name)

	if not instance.serialized_spec:
		return

	# Restore the workflow
	spec_data = (
		json.loads(instance.serialized_spec)
		if isinstance(instance.serialized_spec, str)
		else instance.serialized_spec
	)

	wf = bpmn_engine.restore_workflow(
		workflow_state=spec_data,
		context_doctype=instance.context_doctype,
		context_docname=instance.context_docname,
		script_task_extensions=spec_data.get("script_task_extensions"),
	)

	waiting_before = len(wf.get_tasks(state=TaskState.WAITING))

	# Refresh — this updates timer events that have elapsed
	wf.refresh_waiting_tasks()

	waiting_after = len(wf.get_tasks(state=TaskState.WAITING))

	# If any tasks transitioned, run the engine forward
	if waiting_after < waiting_before:
		# Some timers fired — run the engine to process newly READY tasks
		ready_tasks = wf.get_tasks(state=TaskState.READY)
		for task in ready_tasks:
			# Only auto-complete non-manual tasks (service, script, etc.)
			# User Tasks still require human action
			if not task.task_spec.manual:
				task.run()

		wf.do_engine_steps()

		# Serialize and save
		bpmn_engine.clean_doc_from_wf_data(wf)
		serialized = bpmn_engine.serialize_workflow(wf)

		# Merge extensions back
		model_spec = (
			json.loads(instance.serialized_spec)
			if isinstance(instance.serialized_spec, str)
			else instance.serialized_spec
		)
		for key in ("service_task_extensions", "script_task_extensions", "user_task_extensions"):
			if key in model_spec:
				serialized[key] = model_spec[key]

		instance.serialized_spec = json.dumps(serialized)

		instance._sync_active_tasks(wf)
		instance._check_completion(wf)

		instance.save(ignore_permissions=True)
		frappe.db.commit()

		frappe.logger("one_bpmn").info(
			f"BPMN Timer Catch: refreshed instance {instance_name} — "
			f"{waiting_before - waiting_after} timer(s) fired"
		)

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
