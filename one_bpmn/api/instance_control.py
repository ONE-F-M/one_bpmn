# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Operator controls for a process instance: cancel, suspend, resume and retry the failed step."""

import frappe
from frappe import _

RECOVERY_ROLES = {"System Manager", "Process Owner"}


@frappe.whitelist(methods=["POST"])
def cancel_instance(instance_name: str, reason: str) -> dict:
	"""Cancel an unfinished instance and every task still waiting on it."""
	instance = _instance_for_recovery(instance_name, reason)
	if instance.status in ("Completed", "Cancelled"):
		frappe.throw(
			_('Instance "{0}" is already {1} and cannot be cancelled.').format(instance_name, instance.status)
		)

	instance.status = "Cancelled"
	for row in instance.active_tasks:
		if row.status == "Waiting":
			row.status = "Cancelled"
	instance.log_operator_action("Cancelled", reason)
	instance.save()
	return {"instance": instance_name, "status": instance.status}


@frappe.whitelist(methods=["POST"])
def suspend_instance(instance_name: str, reason: str) -> dict:
	"""Pause an Active instance; timers, messages and parked AI jobs leave it alone until resumed."""
	instance = _instance_for_recovery(instance_name, reason)
	if instance.status != "Active":
		frappe.throw(
			_('Instance "{0}" is {1}. Only an Active instance can be suspended.').format(
				instance_name, instance.status
			)
		)

	instance.status = "Suspended"
	instance.log_operator_action("Suspended", reason)
	instance.save()
	return {"instance": instance_name, "status": instance.status}


@frappe.whitelist(methods=["POST"])
def resume_instance(instance_name: str, reason: str = "") -> dict:
	"""Return a Suspended instance to Active and queue again any AI step parked on it."""
	from one_bpmn.api.instance_api import retry_ai_task

	instance = _instance_for_recovery(instance_name)
	if instance.status != "Suspended":
		frappe.throw(
			_('Instance "{0}" is {1}. Only a Suspended instance can be resumed.').format(
				instance_name, instance.status
			)
		)

	instance.status = "Active"
	instance.log_operator_action("Resumed", reason)
	instance.save()
	# A parked AI job that ran while the instance was suspended returned without doing its work.
	for unit in instance.get_parked_ai_units():
		retry_ai_task(instance_name, unit["task_id"], kind=unit["kind"])
	return {"instance": instance_name, "status": instance.status}


@frappe.whitelist(methods=["POST"])
def retry_failed_step(instance_name: str, reason: str = "") -> dict:
	"""Run an Errored instance again from its last saved state, so the step that failed runs again."""
	instance = _instance_for_recovery(instance_name)
	if instance.status != "Errored":
		frappe.throw(
			_('Instance "{0}" is {1}. Only an Errored instance can retry its failed step.').format(
				instance_name, instance.status
			)
		)

	instance.retry_failed_step()
	instance.log_operator_action("Retried", reason)
	return {"instance": instance_name, "status": instance.status}


def _instance_for_recovery(instance_name: str, reason: str | None = None):
	"""The instance, once the caller holds a recovery role and write permission on it."""
	if not RECOVERY_ROLES & set(frappe.get_roles()):
		frappe.throw(_("Only a Process Owner or System Manager can do this."), frappe.PermissionError)
	if reason is not None and not reason.strip():
		frappe.throw(_("A reason is required."))
	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	instance.check_permission("write")
	return instance
