# Copyright (c) 2026, one-fm and contributors
"""State shared by every BPMN Process Instance runtime job: markers, the activity log and workflow restore."""

import json

import frappe
from frappe.utils import now_datetime

from one_bpmn.processa_engine import engine as bpmn_engine
from one_bpmn.processa_engine.engine import json_safe_doc_fields

AI_SERVICE_TYPES = ("ai_agent", "ai_task_selector")

# Active-task rows for a suspended agent's human tools have no engine task behind them.
AI_HUMAN_PREFIX = "aihuman::"
# Active-task rows that answer a question a remote A2A agent asked.
A2A_HUMAN_PREFIX = "a2ahuman::"

AI_WAITING_HUMAN_KEY = "_bpmn_ai_waiting_human"
A2A_WAITING_KEY = "_bpmn_a2a_waiting"
AGENT_SANDBOX_WAITING_KEY = "_bpmn_agent_sandbox_waiting"

NOTIFY_KEYS = ("notifyAssignee", "notifyAssigneeBody")


def load_json(value):
	"""Load a JSON field that may already be a dict or list; None when it does not parse."""
	if value is None:
		return None
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return None


def waiting_marker(task, key: str) -> dict | None:
	"""The waiting marker a dispatch left on task.data under key, or None.

	A marked task is STARTED but waiting on a person, a delegate or the sandbox: it is never re-dispatched or completed inline.
	"""
	data = getattr(task, "data", None)
	if not isinstance(data, dict):
		return None
	marker = data.get(key)
	return marker if isinstance(marker, dict) else None


def task_bpmn_id(task) -> str:
	"""The diagram id of a task, falling back to its spec name."""
	return getattr(task.task_spec, "bpmn_id", None) or task.task_spec.name


def ai_service_type(instance, task) -> str:
	"""The serviceType of a task's compile-time extension config ('' if none)."""
	task_cfg = getattr(instance, "_service_task_extensions", {}).get(task_bpmn_id(task)) or {}
	return task_cfg.get("serviceType", "")


def log_task(instance, task_id: str, task_name: str, action: str, data: dict | None = None):
	"""Write one BPMN Activity Log row, once per instance, task_id and action. A failed write is logged, never raised."""
	try:
		if frappe.db.exists(
			"BPMN Activity Log", {"instance": instance.name, "task_id": task_id, "action": action}
		):
			return

		log = frappe.new_doc("BPMN Activity Log")
		log.instance = instance.name
		log.task_id = task_id
		log.task_name = task_name
		log.action = action
		log.timestamp = now_datetime()
		log.user = frappe.session.user
		if data:
			log.data = json.dumps(data, default=str, indent=2)
		log.insert(ignore_permissions=True)  # every engine user writes the System Manager only log
	except Exception:
		frappe.log_error(title="BPMN Activity Log write failed", message=frappe.get_traceback())


def settle_goal_completion(instance, instance_status: str):
	"""Fill in the goal outcome of the instance's agent runs that could not decide it themselves. Never raises."""
	try:
		from one_bpmn.ai_agent_observability.goal_completion import settle_for_instance

		settle_for_instance(instance.name, instance_status)
	except Exception:
		frappe.log_error(title="goal completion settle failed", message=frappe.get_traceback())


def refresh_task_data_from_context(instance, task) -> None:
	"""Copy the context document's current field values into task.data so downstream gateways test it as it is now.

	Never raises: a failed refresh must not strand a task that has otherwise completed.
	"""
	if not (instance.context_doctype and instance.context_docname):
		return
	try:
		ctx = frappe.get_doc(instance.context_doctype, instance.context_docname)
		task.data.update(json_safe_doc_fields(ctx))
	except Exception:
		frappe.log_error(
			title="BPMN: failed to refresh doc fields into task data", message=frappe.get_traceback()
		)


def refresh_user_task_extensions_from_model(instance):
	"""Copy only the notification keys of the live model's user task config over the instance's start-time snapshot."""
	try:
		model_spec_json = frappe.db.get_value("BPMN Process Model", instance.process_model, "serialized_spec")
		if not model_spec_json:
			return

		model_spec = load_json(model_spec_json) or {}
		for bpmn_id, model_cfg in model_spec.get("user_task_extensions", {}).items():
			inst_cfg = instance._user_task_extensions.setdefault(bpmn_id, {})
			for key in NOTIFY_KEYS:
				if key in model_cfg:
					inst_cfg[key] = model_cfg[key]
				else:
					inst_cfg.pop(key, None)
	except Exception:
		frappe.log_error(
			title=f"BPMN: Failed to refresh notifyAssignee config for instance {instance.name}",
			message=frappe.get_traceback(),
		)


def acting_user(instance) -> str:
	"""The user whose action drives this engine pass; scripts run with that user's permissions, not the creator's."""
	if frappe.session.user != "Guest":
		return frappe.session.user
	return instance.initiated_by or "Administrator"


def restore_instance_workflow(instance, run_as: str | None = None):
	"""Load the extension configs onto the instance and rebuild its workflow from workflow_state."""
	spec_snap = load_json(instance.serialized_spec or "{}") or {}
	script_exts = spec_snap.get("script_task_extensions", {})
	instance._service_task_extensions = spec_snap.get("service_task_extensions", {})
	instance._user_task_extensions = spec_snap.get("user_task_extensions", {})
	instance._script_task_extensions = script_exts
	refresh_user_task_extensions_from_model(instance)

	wf = bpmn_engine.restore_workflow(
		workflow_state=load_json(instance.workflow_state),
		context_doctype=instance.context_doctype,
		context_docname=instance.context_docname,
		script_task_extensions=script_exts,
		initiated_by=run_as or instance.initiated_by or "Administrator",
		instance=instance,
	)
	if instance.context_doctype and instance.context_docname:
		bpmn_engine.refresh_context_doc(wf, instance.context_doctype, instance.context_docname)
	return wf
