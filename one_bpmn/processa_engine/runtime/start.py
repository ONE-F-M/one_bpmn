# Copyright (c) 2026, one-fm and contributors
"""Start an instance: build its workflow from the model's compiled spec and run it to the first wait."""

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from one_bpmn.processa_engine import engine as bpmn_engine
from one_bpmn.processa_engine.engine import json_safe_doc_fields
from one_bpmn.processa_engine.runtime.active_tasks import (
	check_completion,
	save_without_version_check,
	sync_active_tasks,
	sync_call_activity_rows,
)
from one_bpmn.processa_engine.runtime.common import load_json
from one_bpmn.processa_engine.runtime.engine_loop import run_engine
from one_bpmn.processa_engine.runtime.failures import fail_runtime


def start(instance, initial_data: dict | None = None):
	"""Create the workflow from the linked model's compiled spec and run automated tasks up to the first wait.

	initial_data is merged into the root data after the context document's fields.
	"""
	model = frappe.get_doc("BPMN Process Model", instance.process_model)

	if not model.serialized_spec:
		frappe.throw(
			_('Process model "{0}" has no compiled spec. Call compile_process_model() first.').format(
				instance.process_model
			)
		)

	spec = load_json(model.serialized_spec)
	sp_specs = load_json(model.subprocess_specs) or {}

	data = {
		"context_doctype": instance.context_doctype or "",
		"context_docname": instance.context_docname or "",
		"process_model": instance.process_model or "",
	}

	# Conditional start events such as `docstatus == 0` read the doc's fields from task data.
	if instance.context_doctype and instance.context_docname:
		try:
			ctx = frappe.get_doc(instance.context_doctype, instance.context_docname)
			data.update(json_safe_doc_fields(ctx))
		except Exception:
			frappe.log_error(
				title="BPMN: failed to inject doc fields into task data",
				message=frappe.get_traceback(),
			)

	if initial_data:
		data.update(initial_data)

	instance._service_task_extensions = spec.get("service_task_extensions", {})
	instance._user_task_extensions = spec.get("user_task_extensions", {})
	instance._script_task_extensions = spec.get("script_task_extensions", {})

	wf = bpmn_engine.create_workflow(
		serialized_spec=spec,
		subprocess_specs=sp_specs,
		initial_data=data,
		context_doctype=instance.context_doctype,
		context_docname=instance.context_docname,
		script_task_extensions=instance._script_task_extensions,
		initiated_by=instance.initiated_by or frappe.session.user,
		instance=instance,
	)

	previous_flag = frappe.flags.bpmn_engine_action
	frappe.flags.bpmn_engine_action = True
	try:
		run_engine(instance, wf)
	except Exception:
		fail_runtime(instance, phase="start")
	finally:
		frappe.flags.bpmn_engine_action = previous_flag

	bpmn_engine.clean_doc_from_wf_data(wf)
	instance.workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))
	instance.serialized_spec = model.serialized_spec
	sync_call_activity_rows(instance, wf)
	instance.status = "Active"
	instance.started_at = now_datetime()
	instance.initiated_by = frappe.session.user

	sync_active_tasks(instance, wf)
	check_completion(instance, wf)
	save_without_version_check(instance)
