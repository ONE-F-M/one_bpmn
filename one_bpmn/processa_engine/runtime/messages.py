# Copyright (c) 2026, one-fm and contributors
"""BPMN messages: deliver one to the wait that catches it, or buffer it when the diagram expects it later."""

import json

import frappe
from frappe import _

from one_bpmn.processa_engine import engine as bpmn_engine
from one_bpmn.processa_engine.assignment import split_users
from one_bpmn.processa_engine.runtime.active_tasks import get_active_tasks_summary, persist_workflow
from one_bpmn.processa_engine.runtime.common import log_task, restore_instance_workflow
from one_bpmn.processa_engine.runtime.engine_loop import (
	BUFFERED_MESSAGES_KEPT,
	live_buffered_messages,
	run_engine,
)
from one_bpmn.processa_engine.runtime.failures import fail_runtime


def receive_message(instance, message_name: str, payload: dict | None = None) -> list:
	"""Deliver a named BPMN message, merge its payload into the catching task's data and run on.

	A message nothing waits for is buffered or ignored, never raised; instance.flags.bpmn_message_caught says which.
	Returns the waiting tasks.
	"""
	if instance.status in ("Completed", "Cancelled", "Suspended"):
		frappe.throw(
			_('Instance "{0}" is already {1} and cannot receive messages.').format(
				instance.name, instance.status
			)
		)

	if not instance.workflow_state:
		frappe.throw(_("Workflow state is missing. The instance may be corrupted."))

	if not message_name:
		frappe.throw(_("message_name is required."))

	wf = restore_instance_workflow(instance)

	prev_assigned = set()
	for row in instance.active_tasks:
		if row.status == "Waiting" and row.assigned_user:
			prev_assigned.update(split_users(row.assigned_user))

	caught = bpmn_engine.send_message(wf, message_name, payload=payload)
	instance.flags.bpmn_message_caught = bool(caught)

	if not caught:
		buffer_message(instance, wf, message_name, payload)
		frappe.logger("one_bpmn").debug(
			f'No task in instance "{instance.name}" is waiting for message "{message_name}".'
		)
		return get_active_tasks_summary(instance)

	log_task(
		instance,
		task_id="",
		task_name=f"Message: {message_name}",
		action="Message Received",
		data=payload,
	)

	previous_flag = frappe.flags.bpmn_engine_action
	frappe.flags.bpmn_engine_action = True
	try:
		run_engine(instance, wf)
	except Exception:
		fail_runtime(instance, phase="receive_message")
	finally:
		frappe.flags.bpmn_engine_action = previous_flag

	persist_workflow(instance, wf, prev_assigned)
	return get_active_tasks_summary(instance)


def buffer_message(instance, wf, message_name: str, payload: dict | None):
	"""Keep a message that arrived with nothing waiting for it, when the diagram declares it and its name is buffered."""
	if not (
		message_name.startswith(bpmn_engine.BUFFERED_MESSAGE_PREFIXES)
		and bpmn_engine.declares_message(wf, message_name)
	):
		return
	kept = live_buffered_messages(instance)
	entry = {"name": message_name, "payload": payload or {}, "received_at": frappe.utils.now()}
	if any(m["name"] == message_name and m["payload"] == entry["payload"] for m in kept):
		return
	kept = [*kept, entry][-BUFFERED_MESSAGES_KEPT:]
	instance.db_set("buffered_messages", json.dumps(kept), update_modified=False)
