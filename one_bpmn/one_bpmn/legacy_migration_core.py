# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
#
# Privileged engine for the self-hosted "Processa Legacy Migration V1" BPMN
# process. The two BPMN user-task actions — "Preview Records" and "Run
# Migration" — are backed by the Server Scripts "Legacy Migration – Preview
# Records" and "Legacy Migration – Run Migration", which are thin delegators
# that call preview() / run_migration() here.
#
# Why this lives in app code and not inline in the Server Scripts: the Processa
# script-security validator (one_bpmn/security/script_validator.py) unconditionally
# blocks `ignore_permissions` in Server Scripts, and this migration legitimately
# bypasses permissions (it rewrites arbitrary legacy documents and fabricates
# BPMN Process Instances). So the privileged work belongs in reviewable, deployed
# app code; the Server Scripts remain the BPMN "actions" that drive it.
#
# This replaces the former whitelisted "actioning" endpoints and form buttons on
# the Processa Legacy Migration DocType — the BPMN diagram is now the engine.

import json
from datetime import datetime as _dt

import frappe
from frappe.utils import now_datetime

from SpiffWorkflow.util.task import TaskState
from SpiffWorkflow.bpmn.script_engine import TaskDataEnvironment

from one_bpmn.one_bpmn import engine as bpmn_engine
from one_bpmn.one_bpmn.engine import FrappeScriptEngine, get_serializer


class MigrationScriptEngine(FrappeScriptEngine):
	"""Lenient engine for fast-forward: swallow script-task errors so validation
	scripts (e.g. "Validate PR Reviewer") don't abort the migration. Gateways
	still route because they evaluate before script tasks on error branches."""

	def execute(self, task, script, **kwargs):
		try:
			super().execute(task, script, **kwargs)
		except Exception:
			frappe.log_error(
				title="Legacy Migration: script task execution failed",
				message=frappe.get_traceback(with_context=False),
			)


# ─────────────────────────────────────────────────────────────────────────────
# Preview action
# ─────────────────────────────────────────────────────────────────────────────


def preview(plm):
	"""Count + sample the records the migration would touch, write a durable
	summary onto the config doc, and msgprint the sample list.

	``plm`` is the Processa Legacy Migration context document.
	"""
	target_doctype = plm.target_doctype
	old_status = plm.old_status

	state_field = _get_state_field(target_doctype) if target_doctype else ""
	if not state_field:
		summary = f"DocType '{target_doctype}' has no workflow_state or status field."
		plm.db_set("preview_summary", summary)
		frappe.msgprint(summary, title="Migration Preview", indicator="red")
		return

	count = frappe.db.count(target_doctype, {state_field: old_status})
	samples = frappe.get_all(
		target_doctype,
		filters={state_field: old_status},
		pluck="name",
		limit=10,
		ignore_permissions=True,
	)
	plm.db_set("total_records", count)
	summary = f"Found {count} records in {target_doctype} with {state_field} = {old_status}"
	plm.db_set("preview_summary", summary)

	msg = summary
	if samples:
		msg += "<br><br>Sample records:<ul>"
		for name in samples:
			msg += f"<li>{name}</li>"
		msg += "</ul>"
	frappe.msgprint(msg, title="Migration Preview", indicator="blue")


# ─────────────────────────────────────────────────────────────────────────────
# Run action
# ─────────────────────────────────────────────────────────────────────────────


def run_migration(plm):
	"""Transition every matching legacy record to the target status and
	(optionally) fabricate a fast-forwarded BPMN Process Instance per record.

	Runs synchronously; commits per record so progress + rollback-on-error are
	isolated. ``plm`` is the Processa Legacy Migration context document.
	"""
	plm.db_set({
		"status": "Running",
		"started_at": now_datetime(),
		"run_by": frappe.session.user,
		"migrated_count": 0,
		"failed_count": 0,
	})
	frappe.db.commit()

	state_field = _get_state_field(plm.target_doctype)
	if not state_field:
		plm.db_set({"status": "Failed", "completed_at": now_datetime()})
		frappe.db.commit()
		frappe.log_error(
			title=f"Legacy Migration {plm.name} failed",
			message=(
				f"DocType '{plm.target_doctype}' has neither 'workflow_state' "
				f"nor 'status' field."
			),
		)
		return

	doc_names = frappe.get_all(
		plm.target_doctype,
		filters={state_field: plm.old_status},
		pluck="name",
		ignore_permissions=True,
	)
	plm.db_set("total_records", len(doc_names))
	frappe.db.commit()

	if not doc_names:
		plm.db_set({"status": "Completed", "completed_at": now_datetime()})
		frappe.db.commit()
		return

	migrated = 0
	failed = 0
	for idx, doc_name in enumerate(doc_names):
		try:
			_migrate_single_record(plm, doc_name, state_field)
			migrated += 1
		except Exception:
			failed += 1
			error_tb = frappe.get_traceback(with_context=False)
			frappe.db.rollback()
			_log_row_error(plm, doc_name, error_tb)
			frappe.db.commit()

		if (idx + 1) % 50 == 0:
			plm.db_set({"migrated_count": migrated, "failed_count": failed})
			frappe.db.commit()
			frappe.publish_realtime(
				"legacy_migration_progress",
				{
					"migration_name": plm.name,
					"migrated": migrated,
					"failed": failed,
					"total": len(doc_names),
				},
				user=plm.run_by,
				after_commit=True,
			)

	final_status = "Completed" if migrated > 0 else "Failed"
	plm.db_set({
		"status": final_status,
		"completed_at": now_datetime(),
		"migrated_count": migrated,
		"failed_count": failed,
	})
	frappe.db.commit()
	frappe.publish_realtime(
		"legacy_migration_progress",
		{
			"migration_name": plm.name,
			"migrated": migrated,
			"failed": failed,
			"total": len(doc_names),
			"completed": True,
		},
		user=plm.run_by,
		after_commit=True,
	)


def _migrate_single_record(plm, doc_name, state_field):
	# bpmn_engine_action bypasses the BPMN guard that blocks direct state
	# changes on BPMN-controlled documents.
	old_flag = getattr(frappe.flags, "bpmn_engine_action", False)
	frappe.flags.bpmn_engine_action = True
	try:
		target_doc = frappe.get_doc(plm.target_doctype, doc_name)
		target_doc.set(state_field, plm.target_status)
		target_doc.save(ignore_permissions=True)
	finally:
		frappe.flags.bpmn_engine_action = old_flag

	if plm.create_process_instance:
		existing = frappe.db.exists("BPMN Process Instance", {
			"process_model": plm.process_model,
			"context_doctype": plm.target_doctype,
			"context_docname": doc_name,
			"status": "Active",
		})
		if not existing:
			_create_fast_forwarded_instance(plm, target_doc)

	frappe.db.commit()


def _create_fast_forwarded_instance(plm, target_doc):
	"""Create a real BPMN Process Instance by fast-forwarding the SpiffWorkflow
	engine to the target state position (valid, actionable serialized state)."""
	model = frappe.get_doc("BPMN Process Model", plm.process_model)
	if not model.serialized_spec:
		frappe.throw(f"Process model '{plm.process_model}' has no compiled spec.")

	spec = _load_json(model.serialized_spec)
	service_exts = spec.get("service_task_extensions", {})
	user_exts = spec.get("user_task_extensions", {})
	script_exts = spec.get("script_task_extensions", {})

	data = {"context_doctype": plm.target_doctype, "context_docname": target_doc.name}
	for field in target_doc.meta.fields:
		val = target_doc.get(field.fieldname)
		if isinstance(val, (str, int, float, bool)) or val is None:
			data[field.fieldname] = val
	data["docstatus"] = int(target_doc.docstatus or 0)

	extra = {"datetime": _dt, "frappe": frappe, "doc": target_doc}
	env = TaskDataEnvironment(extra)
	migration_engine = MigrationScriptEngine(
		env,
		script_task_extensions=script_exts,
		context_doctype=plm.target_doctype,
		context_docname=target_doc.name,
		initiated_by=frappe.session.user,
	)

	serializer = get_serializer()
	wf = serializer.deserialize_json(json.dumps(spec))
	wf.script_engine = migration_engine
	if data:
		wf.task_tree.data.update(data)

	target_reached = False
	user_task_completions = {}
	activity_log_entries = []

	for _iter in range(100):
		wf.refresh_waiting_tasks()
		wf.do_engine_steps()

		started = [
			t for t in wf.get_tasks(state=TaskState.STARTED)
			if not getattr(t.task_spec, "manual", False)
		]
		for task in started:
			bpmn_id = getattr(task.task_spec, "bpmn_id", None) or ""
			task_cfg = service_exts.get(bpmn_id, {})
			activity_log_entries.append({
				"task_id": str(task.id),
				"task_name": bpmn_engine.get_task_display_name(task),
				"action": "Completed",
			})
			if task_cfg.get("workflowState") == plm.target_status:
				target_reached = True
			if plm.target_task_id and bpmn_id == plm.target_task_id:
				target_reached = True
			task.complete()

		if target_reached:
			wf.refresh_waiting_tasks()
			wf.do_engine_steps()
			for t in wf.get_tasks(state=TaskState.STARTED):
				if not getattr(t.task_spec, "manual", False):
					activity_log_entries.append({
						"task_id": str(t.id),
						"task_name": bpmn_engine.get_task_display_name(t),
						"action": "Completed",
					})
					t.complete()
			wf.refresh_waiting_tasks()
			wf.do_engine_steps()
			break

		if not started:
			ready = bpmn_engine.get_ready_user_tasks(wf)
			if not ready:
				break
			for task in ready:
				bpmn_id = getattr(task.task_spec, "bpmn_id", None) or ""
				count = user_task_completions.get(bpmn_id, 0)
				if count >= 3:
					frappe.throw(
						f"Cannot advance workflow past task "
						f"'{bpmn_engine.get_task_display_name(task)}' — required data "
						f"may be missing on document '{target_doc.name}'."
					)
				user_task_completions[bpmn_id] = count + 1
				task.data.update(data)
				ut_cfg = user_exts.get(bpmn_id, {})
				first_action = _extract_first_action(ut_cfg.get("taskActions", ""))
				if first_action:
					task.data["action"] = first_action
				activity_log_entries.append({
					"task_id": str(task.id),
					"task_name": bpmn_engine.get_task_display_name(task),
					"action": "Completed",
				})
				task.run()

	if not target_reached:
		frappe.throw(
			f"Could not reach target state '{plm.target_status}' in process model "
			f"'{plm.process_model}' for document '{target_doc.name}'. The document "
			f"data may not satisfy the workflow gateway conditions."
		)

	bpmn_engine.clean_doc_from_wf_data(wf)
	workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))

	instance = frappe.new_doc("BPMN Process Instance")
	instance.process_model = plm.process_model
	instance.context_doctype = plm.target_doctype
	instance.context_docname = target_doc.name
	instance.status = "Active"
	instance.initiated_by = frappe.session.user
	instance.started_at = now_datetime()
	instance.serialized_spec = model.serialized_spec
	instance.workflow_state = workflow_state

	ready_tasks = bpmn_engine.get_ready_user_tasks(wf)
	for task in ready_tasks:
		bpmn_id = getattr(task.task_spec, "bpmn_id", None) or ""
		ut_cfg = user_exts.get(bpmn_id, {})
		instance.append("active_tasks", {
			"task_id": str(task.id),
			"task_name": bpmn_engine.get_task_display_name(task),
			"task_type": bpmn_engine.get_task_type_label(task),
			"status": "Waiting",
			"started_at": now_datetime(),
			"assigned_user": task.data.get("assigned_user") or "",
			"assigned_role": task.data.get("assigned_role") or "",
			"task_actions": ut_cfg.get("taskActions", ""),
			"target_doctype": plm.target_doctype,
			"target_docname": target_doc.name,
		})

	if wf.is_completed():
		instance.status = "Completed"
		instance.completed_at = now_datetime()

	instance.insert(ignore_permissions=True)

	for entry in activity_log_entries:
		_write_activity_log(instance.name, entry["task_id"], entry["task_name"], entry["action"], plm.name)
	for task in ready_tasks:
		_write_activity_log(
			instance.name, str(task.id), bpmn_engine.get_task_display_name(task), "Started", plm.name
		)


def _write_activity_log(instance_name, task_id, task_name, action, migration_name):
	try:
		log = frappe.new_doc("BPMN Activity Log")
		log.instance = instance_name
		log.task_id = task_id
		log.task_name = task_name
		log.action = action
		log.timestamp = now_datetime()
		log.user = frappe.session.user
		log.data = json.dumps({"migrated": True, "migration": migration_name})
		log.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="Legacy Migration: Activity Log write failed",
			message=frappe.get_traceback(),
		)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _get_state_field(target_doctype):
	meta = frappe.get_meta(target_doctype)
	if meta.has_field("workflow_state"):
		return "workflow_state"
	if meta.has_field("status"):
		return "status"
	return ""


def _log_row_error(plm, doc_name, error_message):
	try:
		frappe.get_doc({
			"doctype": "Legacy Migration Error Log",
			"parent": plm.name,
			"parenttype": "Processa Legacy Migration",
			"parentfield": "error_logs",
			"document_doctype": plm.target_doctype,
			"document_name": doc_name,
			"error_message": (error_message or "")[:65535],
			"timestamp": now_datetime(),
		}).db_insert()
	except Exception:
		frappe.log_error(
			title=f"Legacy Migration: error log insert failed for {doc_name}",
			message=frappe.get_traceback(),
		)


def _extract_first_action(actions_raw):
	if not actions_raw:
		return ""
	trimmed = actions_raw.strip()
	if trimmed.startswith("["):
		try:
			parsed = json.loads(trimmed)
			if isinstance(parsed, list) and parsed:
				return parsed[0].get("action", "")
		except (TypeError, ValueError):
			pass
	parts = [a.strip() for a in trimmed.split(",") if a.strip()]
	return parts[0] if parts else ""


def _load_json(value):
	if value is None:
		return None
	if isinstance(value, (dict, list)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError):
		return None
