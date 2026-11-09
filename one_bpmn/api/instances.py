# Copyright (c) 2026, one-fm and contributors
"""Process instance endpoints for the instance pages, desk forms and messages; the work is in processa_engine.instances."""

import frappe

from one_bpmn.processa_engine.instances import cancellation, control, listing, starting, task_actions


@frappe.whitelist()
def list_process_instances(
	filters=None,
	limit_start=0,
	limit_page_length=20,
	order_by="creation desc",
	pending_action_by=None,
	search=None,
) -> list:
	"""List BPMN process instances with their waiting tasks joined as current_step."""
	return listing.list_process_instances(
		filters, limit_start, limit_page_length, order_by, pending_action_by, search
	)


@frappe.whitelist()
def start_process(
	model_name: str,
	context_doctype: str = None,
	context_docname: str = None,
	initial_data: str = None,
) -> dict:
	"""Create and start a BPMN Process Instance; returns its name, status and first active tasks."""
	return starting.start_process(model_name, context_doctype, context_docname, initial_data)


@frappe.whitelist()
def start_process_async(
	model_name: str,
	context_doctype: str = None,
	context_docname: str = None,
	initial_data: str = None,
) -> dict:
	"""Queue start_process as a background job that runs as the caller."""
	return starting.start_process_async(model_name, context_doctype, context_docname, initial_data)


@frappe.whitelist()
def complete_task(
	instance_name: str,
	task_id: str,
	data: str = None,
) -> dict:
	"""Complete a User Task in a running instance and advance the workflow."""
	return task_actions.complete_task(instance_name, task_id, data)


@frappe.whitelist()
def get_parked_ai_tasks(instance_name: str) -> list:
	"""The parked AI units of an instance, for the diagram marker and the retry button."""
	return task_actions.get_parked_ai_tasks(instance_name)


@frappe.whitelist()
def get_suspended_ai_tasks(instance_name: str) -> list:
	"""The agents of this instance suspended waiting for a person."""
	return task_actions.get_suspended_ai_tasks(instance_name)


@frappe.whitelist()
def retry_ai_task(instance_name: str, task_id: str, kind: str = "service_task") -> dict:
	"""Queue a parked AI unit again after its automatic retries ran out."""
	return task_actions.retry_ai_task(instance_name, task_id, kind)


@frappe.whitelist()
def get_instance_tasks(instance_name: str) -> dict:
	"""The status and current active tasks of a process instance."""
	return listing.get_instance_tasks(instance_name)


@frappe.whitelist()
def get_processa_controlled_doctypes() -> list:
	"""Every DocType whose lifecycle an active BPMN Process Model drives."""
	return listing.get_processa_controlled_doctypes()


@frappe.whitelist()
def get_active_bpmn_tasks(doctype: str, docname: str) -> list:
	"""The Waiting User Task actions on a document, for the desk form buttons."""
	return task_actions.get_active_bpmn_tasks(doctype, docname)


@frappe.whitelist()
def trigger_process_by_message(
	message_name: str,
	payload: str = None,
	context_doctype: str = None,
	context_docname: str = None,
) -> dict:
	"""Start the process whose Message Start Event declares message_name and deliver the message to it."""
	return starting.trigger_process_by_message(message_name, payload, context_doctype, context_docname)


@frappe.whitelist()
def send_message(
	message_name: str,
	context_doctype: str = None,
	context_docname: str = None,
	instance_name: str = None,
	payload: str = None,
) -> dict:
	"""Deliver a BPMN message to a running process instance."""
	return starting.send_message(message_name, context_doctype, context_docname, instance_name, payload)


@frappe.whitelist(methods=["POST"])
def cancel_instance(instance_name: str, reason: str) -> dict:
	"""Cancel an unfinished instance and every task still waiting on it."""
	return control.cancel_instance(instance_name, reason)


@frappe.whitelist(methods=["POST"])
def suspend_instance(instance_name: str, reason: str) -> dict:
	"""Pause an Active instance until it is resumed."""
	return control.suspend_instance(instance_name, reason)


@frappe.whitelist(methods=["POST"])
def resume_instance(instance_name: str, reason: str = "") -> dict:
	"""Return a Suspended instance to Active and queue again any AI step parked on it."""
	return control.resume_instance(instance_name, reason)


@frappe.whitelist(methods=["POST"])
def retry_failed_step(instance_name: str, reason: str = "") -> dict:
	"""Run an Errored instance again from its last saved state."""
	return control.retry_failed_step(instance_name, reason)


@frappe.whitelist(methods=["POST"])
def request_cancellation(doctype: str, docname: str) -> dict:
	"""Start the DocType's cancellation process on a submitted document; the document stays submitted."""
	frappe.has_permission(doctype, "cancel", docname, throw=True)
	return cancellation.request_cancellation(doctype, docname)
