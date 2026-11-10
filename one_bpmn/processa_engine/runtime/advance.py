# Copyright (c) 2026, one-fm and contributors
"""Advance an instance: complete a User Task and run on, or rerun an Errored instance from its saved state."""

import uuid

import frappe
from frappe import _
from frappe.utils import now_datetime

from one_bpmn.processa_engine import engine as bpmn_engine
from one_bpmn.processa_engine.assignment import split_users
from one_bpmn.processa_engine.engine import TaskState
from one_bpmn.processa_engine.runtime.active_tasks import get_active_tasks_summary, persist_workflow
from one_bpmn.processa_engine.runtime.common import (
	acting_user,
	log_task,
	refresh_task_data_from_context,
	restore_instance_workflow,
)
from one_bpmn.processa_engine.runtime.engine_loop import run_engine
from one_bpmn.processa_engine.runtime.failures import fail_runtime
from one_bpmn.processa_engine.runtime.start import start


def advance(instance, task_id: str, data: dict | None = None) -> list:
	"""Complete the READY User Task task_id with the user's data, run the engine on and return the waiting tasks."""
	if instance.status in ("Completed", "Cancelled", "Suspended"):
		frappe.throw(
			_('Instance "{0}" is already {1} and cannot be advanced.').format(instance.name, instance.status)
		)

	if not instance.workflow_state:
		frappe.throw(_("Workflow state is missing. The instance may be corrupted."))

	wf = restore_instance_workflow(instance, run_as=acting_user(instance))

	try:
		task = wf.get_task_from_id(uuid.UUID(task_id))
	except Exception:
		frappe.throw(_('Task "{0}" not found in this workflow instance.').format(task_id))

	if task.state != TaskState.READY:
		frappe.throw(
			_('Task "{0}" is not in READY state (current state: {1}).').format(
				bpmn_engine.get_task_display_name(task),
				TaskState.get_name(task.state),
			)
		)

	# The root data carries non-document keys; the document's own fields come fresh on top of it.
	if instance.context_doctype and instance.context_docname:
		task.data.update({k: v for k, v in wf.task_tree.data.items() if k not in ("doc",)})
		refresh_task_data_from_context(instance, task)

	if data:
		task.data.update(data)

	# Taken before the row is marked Completed, so sync_active_tasks can diff who was assigned.
	prev_assigned = set()
	for row in instance.active_tasks:
		if row.status == "Waiting" and row.assigned_user:
			prev_assigned.update(split_users(row.assigned_user))

	completed_at = now_datetime()
	for row in instance.active_tasks:
		if row.task_id == task_id:
			row.status = "Completed"
			row.end_time = completed_at
			if row.started_at:
				row.timer_duration = int(frappe.utils.time_diff_in_seconds(completed_at, row.started_at))

	log_task(
		instance,
		task_id=task_id,
		task_name=bpmn_engine.get_task_display_name(task),
		action="Completed",
		data=data,
	)

	previous_flag = frappe.flags.bpmn_engine_action
	frappe.flags.bpmn_engine_action = True
	try:
		task.run()
		run_engine(instance, wf)
	except Exception:
		fail_runtime(instance, phase="advance")
	finally:
		frappe.flags.bpmn_engine_action = previous_flag

	persist_workflow(instance, wf, prev_assigned)
	return get_active_tasks_summary(instance)


def retry_failed_step(instance):
	"""Run an Errored instance again from its last saved state, so the step that failed runs again."""
	if not instance.workflow_state:
		# A failure in the first engine pass saved no state, so the run starts over from the context document.
		initiated_by = instance.initiated_by
		start(instance)
		if initiated_by:
			instance.db_set("initiated_by", initiated_by, update_modified=False)
		return

	wf = restore_instance_workflow(instance, run_as=acting_user(instance))
	prev_assigned = {
		row.assigned_user for row in instance.active_tasks if row.status == "Waiting" and row.assigned_user
	}

	instance.status = "Active"
	previous_flag = frappe.flags.bpmn_engine_action
	frappe.flags.bpmn_engine_action = True
	try:
		run_engine(instance, wf)
	except Exception:
		fail_runtime(instance, phase="retry_failed_step")
	finally:
		frappe.flags.bpmn_engine_action = previous_flag

	persist_workflow(instance, wf, prev_assigned)
