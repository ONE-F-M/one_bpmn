# Copyright (c) 2026, one-fm and contributors
"""BPMN Send Task: send a Frappe Notification against the context document."""

import frappe


def dispatch_send_notification(instance, task, task_cfg: dict, bpmn_id: str) -> None:
	"""Send the Notification named by notificationName; never raises.

	Writes {bpmn_id}_sent = 1 into the task's scope on success, or {bpmn_id}_send_error with the reason, for the AI Task Selector.
	"""
	scope = getattr(task.workflow, "data", None)
	try:
		notification_name = (task_cfg.get("notificationName") or "").strip()
		if not notification_name:
			return
		if not (instance.context_doctype and instance.context_docname):
			raise ValueError("send task has no context document to render against")

		notification = frappe.get_doc("Notification", notification_name)
		doc = frappe.get_doc(instance.context_doctype, instance.context_docname)
		notification.send(doc)

		if isinstance(scope, dict):
			scope[f"{bpmn_id}_sent"] = 1
	except Exception as exc:
		if isinstance(scope, dict):
			scope[f"{bpmn_id}_send_error"] = str(exc)
		frappe.log_error(
			title=f"BPMN send task failed: {bpmn_id} on {instance.name}",
			message=frappe.get_traceback(),
		)
