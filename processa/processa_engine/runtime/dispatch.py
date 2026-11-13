# Copyright (c) 2026, one-fm and contributors
"""Service Task dispatch and the hooks the engine fires when a task completes."""

import json

import frappe
from frappe.utils import now_datetime

from processa.processa_engine import engine as bpmn_engine
from processa.processa_engine.dispatch.ai_agent import dispatch_ai_agent
from processa.processa_engine.dispatch.connector import dispatch_connector
from processa.processa_engine.dispatch.email import dispatch_email
from processa.processa_engine.dispatch.google_chat import dispatch_google_chat
from processa.processa_engine.dispatch.push_notification import dispatch_push_notification
from processa.processa_engine.dispatch.send_notification import dispatch_send_notification
from processa.processa_engine.dispatch.update_field import dispatch_update_field
from processa.processa_engine.engine import SubWorkflowTask
from processa.processa_engine.runtime.common import log_task, refresh_task_data_from_context, task_bpmn_id


def dispatch_service_task(instance, task, task_cfg_override: dict | None = None):
	"""Run the real-world action of a STARTED Service Task by its compiled serviceType. Always returns True.

	task_cfg_override is for shape_tools.execute_shape, whose ad-hoc AI calls have no Service Task shape to read config from.
	"""
	bpmn_id = getattr(task.task_spec, "bpmn_id", None) or ""
	if task_cfg_override is not None:
		task_cfg = task_cfg_override
	else:
		task_cfg = getattr(instance, "_service_task_extensions", {}).get(bpmn_id, {})

	service_type = task_cfg.get("serviceType", "")

	if service_type == "apply_workflow":
		_apply_workflow(instance, task, task_cfg, bpmn_id)

	elif service_type == "send_email":
		try:
			dispatch_email(instance, task, task_cfg, amp_html=task_cfg.get("ampHtml") or None)
		except Exception:
			# A missing email account or a down mail server must not stop the workflow.
			frappe.log_error(
				title=f"BPMN ServiceTask: send_email failed for task {bpmn_id}",
				message=frappe.get_traceback(),
			)

	elif service_type == "update_field":
		dispatch_update_field(instance, task, task_cfg, bpmn_id)

	elif service_type == "google_chat":
		dispatch_google_chat(instance, task, task_cfg, bpmn_id)

	elif service_type == "connector":
		dispatch_connector(instance, task, task_cfg, bpmn_id)

	elif service_type == "push_notification":
		try:
			dispatch_push_notification(instance, task, task_cfg, bpmn_id)
		except Exception:
			frappe.log_error(
				title=f"BPMN ServiceTask: push_notification failed for task {bpmn_id}",
				message=frappe.get_traceback(),
			)

	elif service_type == "ai_agent":
		dispatch_ai_agent(instance, task, task_cfg, bpmn_id)

	return True


def _apply_workflow(instance, task, task_cfg: dict, bpmn_id: str) -> None:
	"""Apply a Frappe Workflow transition to the context document, then refresh this task's data from it."""
	doctype = task_cfg.get("serviceTargetDoctype") or instance.context_doctype
	docname = instance.context_docname
	target_state = task_cfg.get("workflowState", "")
	doc_status = task_cfg.get("docStatus", "")
	triggered_by = frappe.session.user or instance.initiated_by or "Administrator"

	# A misconfigured task is logged and still completes, so the workflow does not stick.
	if not (doctype and docname):
		frappe.log_error(
			title="BPMN ServiceTask: apply_workflow misconfigured",
			message=(
				f"Task {bpmn_id} ({bpmn_engine.get_task_display_name(task)}) "
				f"is missing doctype={doctype!r} or docname={docname!r}."
			),
		)
		return

	if not target_state and not doc_status:
		frappe.log_error(
			title="BPMN ServiceTask: apply_workflow misconfigured",
			message=(
				f"Task {bpmn_id} ({bpmn_engine.get_task_display_name(task)}) "
				f"has neither workflowState nor docStatus configured."
			),
		)
		return

	from processa.processa_engine.audit import apply_bpmn_workflow_state

	apply_bpmn_workflow_state(
		doctype=doctype,
		docname=docname,
		target_state=target_state,
		doc_status_hint=doc_status,
		only_allow_role=task_cfg.get("onlyAllowEdit", ""),
		triggered_by=triggered_by,
	)

	# The service task runs mid-pass, after the user task's refresh, so a downstream gateway sees the new state only from here.
	refresh_task_data_from_context(instance, task)


def on_engine_task_complete(instance, task):
	"""Log an automated task's completion and run a Send Task's notification. Engine-internal tasks are skipped."""
	task_spec = task.task_spec
	bpmn_id = getattr(task_spec, "bpmn_id", None)
	spec_name = getattr(task_spec, "name", "") or ""

	if not bpmn_id and (spec_name in ("Start", "End") or spec_name.endswith(".EndJoin")):
		return

	# Send Tasks never sit in STARTED, so their action runs here.
	if isinstance(task_spec, bpmn_engine.SendTask) and bpmn_id:
		task_cfg = getattr(instance, "_service_task_extensions", {}).get(bpmn_id, {})
		if task_cfg.get("notificationName"):
			dispatch_send_notification(instance, task, task_cfg, bpmn_id)

	# A completed subprocess parent ends its AI Task Selector run.
	if isinstance(task_spec, SubWorkflowTask):
		try:
			from processa.ai_agent_observability.observability import finalize_open_selector_runs

			finalize_open_selector_runs(instance.name, bpmn_id or spec_name)
		except Exception:
			pass

	log_task(
		instance,
		task_id=str(task.id),
		task_name=bpmn_engine.get_task_display_name(task),
		action="Completed",
		data=dict(task.data),
	)


def on_adhoc_task_complete(instance, task):
	"""After an ad-hoc inner task completes: refresh the context doc for the next inline script and record the outcome."""
	if instance.context_doctype and instance.context_docname:
		bpmn_engine.refresh_context_doc(
			task.workflow.top_workflow, instance.context_doctype, instance.context_docname
		)

	# No-op when no outcome-less AI Agent Tool Call matches, as for a plain ad-hoc task.
	try:
		from processa.ai_agent_observability.observability import record_activation_outcome

		bpmn_id = task_bpmn_id(task)
		record_activation_outcome(instance.name, bpmn_id, compose_task_outcome(instance, task, bpmn_id))
	except Exception:
		frappe.log_error(title="BPMN: activation outcome recording failed", message=frappe.get_traceback())


def compose_task_outcome(instance, task, bpmn_id: str) -> str:
	"""One-line summary of what a completed ad-hoc inner task did, from its config and the data it wrote."""
	svc_cfg = getattr(instance, "_service_task_extensions", {}).get(bpmn_id) or {}
	script_cfg = getattr(instance, "_script_task_extensions", {}).get(bpmn_id) or {}
	parts = []

	if svc_cfg.get("serviceType") == "update_field":
		target = svc_cfg.get("updateFieldDoctype") or instance.context_doctype or "document"
		try:
			for row in json.loads(svc_cfg.get("updateFieldRows") or "[]"):
				parts.append(f'set {target}.{row.get("field")} = "{row.get("value")}"')
		except Exception:
			pass

	script_name = script_cfg.get("serverScript") or svc_cfg.get("serverScript")
	if script_name:
		written = {}
		try:
			from processa.ai_agent_registry.definitions.assistant.helpers import server_script_result_keys

			for key in server_script_result_keys(script_name):
				if key in (task.data or {}):
					written[key] = task.data[key]
		except Exception:
			pass
		if written:
			values = ", ".join(f"{k} = {v!r}" for k, v in written.items())
			parts.append(f'ran Server Script "{script_name}" → {values}')
		else:
			parts.append(f'ran Server Script "{script_name}"')

	if svc_cfg.get("notificationName"):
		parts.append(f'sent notification "{svc_cfg["notificationName"]}"')

	if not parts and "UserTask" in type(task.task_spec).__name__:
		parts.append(f"completed by {frappe.session.user}")

	summary = "; ".join(parts) if parts else "completed"
	return f"Completed {now_datetime().strftime('%H:%M:%S')} - {summary}"


def log_adhoc_activation(instance, sp, task):
	"""Activity log entry for an ad-hoc task the gate activated; log_task drops engine-restart repeats."""
	log_task(
		instance,
		task_id=str(task.id),
		task_name=bpmn_engine.get_task_display_name(task),
		action="Ad-Hoc Task Activated",
		data={"bpmn_id": task_bpmn_id(task), "parent_subprocess": sp.spec.name},
	)


def log_ai_task_selected(instance, bpmn_id: str, chosen_tools: list, arguments: dict | None = None):
	"""Activity log entry pointing at an AI Task Selector decision; the full record is on AI Agent Tool Call."""
	summary = json.dumps(arguments or {}, default=str)
	if len(summary) > 500:
		summary = summary[:500] + "…"
	log_task(
		instance,
		task_id=f"{bpmn_id}::decision::{'+'.join(chosen_tools) or 'none'}",
		task_name=f"AI Task Selector ({bpmn_id})",
		action="AI Task Selected",
		data={"chosen_tools": chosen_tools, "arguments_summary": summary},
	)
