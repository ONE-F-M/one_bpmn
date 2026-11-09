# Copyright (c) 2026, one-fm and contributors
"""Move an open record to a new process map: replay the old instance's history without side effects, then swap instances."""

import datetime
import json
from uuid import UUID

import frappe
from frappe import _
from frappe.utils import create_batch, now_datetime
from rq.timeouts import JobTimeoutException

from one_bpmn.processa_engine import engine as bpmn_engine
from one_bpmn.processa_engine.assignment import add_frappe_assignment, resolve_assignment, split_users
from one_bpmn.processa_engine.audit import apply_bpmn_workflow_state
from one_bpmn.processa_engine.engine import (
	CallActivityMixin,
	CatchingEvent,
	FrappeScriptEngine,
	MultiInstanceTask,
	SubWorkflowTask,
	TaskDataEnvironment,
	TaskNotFoundException,
	TaskState,
	WorkflowException,
)
from one_bpmn.processa_engine.runtime.common import log_task, task_bpmn_id
from one_bpmn.processa_engine.runtime.messages import receive_message

# Engine steps one replay may run; a loop the history cannot leave hits it.
TASK_RUN_LIMIT = 500
BATCH_SIZE = 25
OPEN_INSTANCE_STATUSES = ("Active", "Errored")
FINISHED_MESSAGE = "processa:legacy_migration:finished"


class MigrationSkip(Exception):
	"""A record that cannot move; reason is one of the Legacy Migration Error Log reasons."""

	def __init__(self, reason: str, detail: str):
		super().__init__(detail)
		self.reason = reason
		self.detail = detail


class ReplayScriptEngine(FrappeScriptEngine):
	def execute(self, task, script, **kwargs):
		"""Script tasks do not run during a replay; gateway conditions still evaluate."""


def start(migration_name: str) -> None:
	"""Queue a migration's open old-map instances as run_batch jobs of BATCH_SIZE on the long queue."""
	plm = frappe.get_doc("Processa Legacy Migration", migration_name)
	user = plm.run_by or frappe.session.user
	try:
		plm.check_process_ownership(
			frappe.get_doc("BPMN Process Model", plm.from_model),
			frappe.get_doc("BPMN Process Model", plm.to_model),
			user,
		)
	except frappe.PermissionError as e:
		frappe.clear_messages()
		log_error_row(migration_name, frappe._dict(), "Error", str(e))
		plm.db_set({"status": "Running", "run_by": user, "started_at": now_datetime()})
		finish(migration_name)
		return

	names = frappe.get_all(
		"BPMN Process Instance",
		filters={
			"process_model": plm.from_model,
			"context_doctype": plm.target_doctype,
			"status": ["in", OPEN_INSTANCE_STATUSES],
		},
		pluck="name",
		order_by="started_at asc",
	)
	batches = list(create_batch(names, BATCH_SIZE))
	plm.db_set(
		{
			"status": "Running",
			"run_by": user,
			"started_at": now_datetime(),
			"completed_at": None,
			"total_records": len(names),
			"total_batches": len(batches),
			"batches_done": 0,
			"migrated_count": 0,
			"failed_count": 0,
		}
	)
	if not batches:
		finish(migration_name)
		return
	for n, batch in enumerate(batches, start=1):
		frappe.enqueue(
			"one_bpmn.processa_engine.legacy_migration.run_batch",
			queue="long",
			timeout=600,
			job_id=f"plm::{migration_name}::{n}",
			deduplicate=True,
			enqueue_after_commit=True,
			migration_name=migration_name,
			instance_names=list(batch),
		)


def run_batch(migration_name: str, instance_names: list) -> None:
	"""Move one batch, committing after each record; a timeout or batch failure logs every record it did not move."""
	moved = failed = 0
	reached = 0
	try:
		ctx = build_context(frappe.get_doc("Processa Legacy Migration", migration_name))
		frappe.only_for(["System Manager", "Process Owner"])
		for name in instance_names:
			if migrate_record(ctx, frappe.get_doc("BPMN Process Instance", name)):
				moved += 1
			else:
				failed += 1
			reached += 1
			frappe.db.commit()
	except JobTimeoutException:
		frappe.db.rollback()
		failed += _log_unmoved(
			migration_name, instance_names[reached:], "Timed out", _("The batch ran out of time.")
		)
		_count_batch(migration_name, moved, failed)
		frappe.db.commit()
		raise
	except Exception:
		frappe.db.rollback()
		detail = frappe.get_traceback(with_context=False)
		failed += _log_unmoved(migration_name, instance_names[reached:], "Error", detail)
		_count_batch(migration_name, moved, failed)
		frappe.db.commit()
		raise
	_count_batch(migration_name, moved, failed)


def _log_unmoved(migration_name: str, instance_names: list, reason: str, detail: str) -> int:
	"""An Error Log row for each instance a batch did not move; returns how many."""
	for name in instance_names:
		log_error_row(migration_name, frappe.get_doc("BPMN Process Instance", name), reason, detail)
	return len(instance_names)


def _count_batch(migration_name: str, moved: int, failed: int) -> None:
	"""Add one batch's counts in a single update; the batch that completes the run calls finish."""
	plm_table = frappe.qb.DocType("Processa Legacy Migration")
	(
		frappe.qb.update(plm_table)
		.set(plm_table.migrated_count, plm_table.migrated_count + moved)
		.set(plm_table.failed_count, plm_table.failed_count + failed)
		.set(plm_table.batches_done, plm_table.batches_done + 1)
		.where(plm_table.name == migration_name)
	).run()
	plm = frappe.db.get_value(
		"Processa Legacy Migration",
		migration_name,
		["migrated_count", "failed_count", "total_records", "batches_done", "total_batches", "run_by"],
		as_dict=True,
	)
	frappe.publish_realtime(
		"legacy_migration_progress",
		{
			"migration_name": migration_name,
			"migrated": plm.migrated_count,
			"failed": plm.failed_count,
			"total": plm.total_records,
			"batches_done": plm.batches_done,
			"total_batches": plm.total_batches,
		},
		user=plm.run_by,
		after_commit=True,
	)
	if plm.batches_done == plm.total_batches:
		finish(migration_name)


def finish(migration_name: str) -> None:
	"""Close a run: Completed when a record moved or there was nothing to move, else Failed; tell the PLM's own process."""
	plm = frappe.get_doc("Processa Legacy Migration", migration_name)
	nothing_to_move = not plm.total_records and not plm.error_logs
	status = "Completed" if plm.migrated_count or nothing_to_move else "Failed"
	plm.db_set({"status": status, "completed_at": now_datetime()})
	frappe.publish_realtime(
		"legacy_migration_progress",
		{"migration_name": migration_name, "completed": True},
		user=plm.run_by,
		after_commit=True,
	)
	own_instance = frappe.db.get_value(
		"BPMN Process Instance",
		{
			"context_doctype": "Processa Legacy Migration",
			"context_docname": migration_name,
			"status": "Active",
		},
	)
	if own_instance:
		receive_message(
			frappe.get_doc("BPMN Process Instance", own_instance),
			FINISHED_MESSAGE,
			{"migration_status": status},
		)


def build_context(plm) -> frappe._dict:
	"""What every replay of one Processa Legacy Migration needs, loaded once."""
	to_spec = json.loads(frappe.db.get_value("BPMN Process Model", plm.to_model, "serialized_spec"))
	from_spec = json.loads(frappe.db.get_value("BPMN Process Model", plm.from_model, "serialized_spec"))
	to_wf = _spec_workflow(to_spec)
	return frappe._dict(
		plm=plm,
		to_spec=to_spec,
		to_wf=to_wf,
		to_ids=_element_ids(to_wf),
		from_ids=_element_ids(_spec_workflow(from_spec)),
		state_map={d.old_state: d.new_state for d in plm.state_map},
		state_field=state_field(plm.target_doctype),
		set_states={
			bpmn_id: cfg["workflowState"]
			for bpmn_id, cfg in to_spec.get("service_task_extensions", {}).items()
			if cfg.get("workflowState")
		},
	)


def migrate_record(ctx, old) -> bool:
	"""Move one record fully or not at all; a record that cannot move gets an Error Log row. True when it moved.

	Commits nothing: the batch job commits after each record, so a refused record's row is kept with it."""
	frappe.db.savepoint("plm_record")
	try:
		wf, _last_state = replay(ctx, old)
		new = _insert_new_instance(ctx, old, wf)
		_copy_history(ctx, old, new)
		_repoint_todos(old, new)
		_retire(old, new)
		state = frappe.db.get_value(old.context_doctype, old.context_docname, ctx.state_field)
		previous_flag = frappe.flags.bpmn_engine_action
		frappe.flags.bpmn_engine_action = True
		try:
			apply_bpmn_workflow_state(
				old.context_doctype,
				old.context_docname,
				ctx.state_map[state],
				triggered_by=frappe.session.user,
			)
		finally:
			frappe.flags.bpmn_engine_action = previous_flag
	except MigrationSkip as skip:
		frappe.db.rollback(save_point="plm_record")
		log_error_row(ctx.plm.name, old, skip.reason, skip.detail)
		return False
	except JobTimeoutException:
		# run_batch logs the timed-out record together with the ones its batch did not reach.
		raise
	except Exception:
		frappe.db.rollback(save_point="plm_record")
		log_error_row(ctx.plm.name, old, "Error", frappe.get_traceback(with_context=False))
		return False
	return True


def log_error_row(plm_name: str, old, reason: str, detail: str) -> None:
	"""Add a Legacy Migration Error Log row for a record that did not move."""
	frappe.get_doc(
		{
			"doctype": "Legacy Migration Error Log",
			"parent": plm_name,
			"parenttype": "Processa Legacy Migration",
			"parentfield": "error_logs",
			"idx": frappe.db.count("Legacy Migration Error Log", {"parent": plm_name}) + 1,
			"document_doctype": old.context_doctype,
			"document_name": old.context_docname,
			"old_instance": old.name,
			"reason": reason,
			"error_message": detail,
			"timestamp": now_datetime(),
		}
	).db_insert()


def _insert_new_instance(ctx, old, wf):
	"""The new instance waiting where the replay stopped, its tasks assigned like the old ones. No email is sent."""
	old_wf = bpmn_engine.restore_workflow(json.loads(old.workflow_state))
	old_rows = {}
	for row in old.active_tasks:
		if row.status == "Waiting":
			old_rows[task_bpmn_id(old_wf.get_task_from_id(UUID(row.task_id)))] = row

	new = frappe.new_doc("BPMN Process Instance")
	new.update(
		{
			"process_model": ctx.plm.to_model,
			"migrated_from": old.name,
			"status": "Active",
			"context_doctype": old.context_doctype,
			"context_docname": old.context_docname,
			"initiated_by": old.initiated_by,
			"started_at": old.started_at,
			"serialized_spec": json.dumps(ctx.to_spec),
		}
	)
	new._user_task_extensions = ctx.to_spec.get("user_task_extensions", {})
	to_assign = []
	for task in bpmn_engine.get_ready_user_tasks(wf):
		bpmn_id = task_bpmn_id(task)
		old_row = old_rows.get(bpmn_id)
		row = {
			"task_id": str(task.id),
			"task_name": bpmn_engine.get_task_display_name(task),
			"task_type": bpmn_engine.get_task_type_label(task),
			"status": "Waiting",
			"started_at": now_datetime(),
			"task_actions": new._user_task_extensions.get(bpmn_id, {}).get("taskActions", ""),
			"target_doctype": old.context_doctype,
			"target_docname": old.context_docname,
		}
		if old_row:
			for field in ("assigned_user", "assigned_role", "reliever_user", "relieved_user"):
				row[field] = old_row.get(field)
		else:
			row["assigned_user"] = resolve_assignment(new, task)
			row["relieved_user"] = ",".join(p[0] for p in new._relief_pairs)
			row["reliever_user"] = ",".join(p[1] for p in new._relief_pairs)
			to_assign.append((row["assigned_user"], row["task_name"]))
		new.append("active_tasks", row)

	bpmn_engine.clean_doc_from_wf_data(wf)
	new.workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))
	frappe.only_for(["System Manager", "Process Owner"])
	new.insert(ignore_permissions=True)  # perms: the migration acts for the process
	for users, task_name in to_assign:
		for user in split_users(users):
			add_frappe_assignment(new, user, task_name)
	return new


def _copy_history(ctx, old, new) -> None:
	"""Copy the old instance's Activity Log to the new one with original users and times, then log the move."""
	fields = [
		"name",
		"creation",
		"modified",
		"owner",
		"modified_by",
		"instance",
		"task_id",
		"task_name",
		"action",
		"timestamp",
		"user",
		"data",
	]
	rows = frappe.get_all(
		"BPMN Activity Log",
		filters={"instance": old.name},
		fields=[f for f in fields if f != "name"],
		order_by="timestamp asc, creation asc",
	)
	values = [
		[frappe.generate_hash(length=10), *(new.name if f == "instance" else row[f] for f in fields[1:])]
		for row in rows
	]
	frappe.db.bulk_insert("BPMN Activity Log", fields=fields, values=values)
	log_task(new, "", _("Migrated"), "Migrated", {"migrated_from": old.name, "migration": ctx.plm.name})


def _repoint_todos(old, new) -> None:
	"""Open process ToDos on the record that name the old instance now name the new one."""
	for todo in frappe.get_all(
		"ToDo",
		filters={
			"reference_type": old.context_doctype,
			"reference_name": old.context_docname,
			"type": "Process",
			"status": "Open",
			"description": ["like", f"%{old.name}%"],
		},
		fields=["name", "description"],
	):
		frappe.db.set_value("ToDo", todo.name, "description", todo.description.replace(old.name, new.name))


def _retire(old, new) -> None:
	"""Cancel the old instance and its Waiting tasks, and log which instance replaced it."""
	frappe.db.set_value(
		"BPMN Process Instance",
		old.name,
		{"status": "Cancelled", "completed_at": now_datetime()},
		update_modified=False,
	)
	for row in old.active_tasks:
		if row.status == "Waiting":
			frappe.db.set_value("BPMN Active Task", row.name, "status", "Cancelled", update_modified=False)
	log_task(old, "", _("Retired"), "Retired", {"replaced_by": new.name})


def replay(ctx, old) -> tuple:
	"""Replay one old instance on the new map; returns the workflow and the last state it set. Writes nothing."""
	old_wf, old_waits, new_state = check_instance(ctx, old)
	steps = _history(ctx, old, old_wf)

	wf = _spec_workflow(ctx.to_spec)
	wf.script_engine = ReplayScriptEngine(
		TaskDataEnvironment({"frappe": frappe, "datetime": datetime}),
		context_doctype=old.context_doctype,
		context_docname=old.context_docname,
	)
	wf.task_tree.data.update(_old_variables(old_wf))
	wf.task_tree.data.update(context_doctype=old.context_doctype, context_docname=old.context_docname)

	progress = {"last_state": None, "runs": 0}
	try:
		_advance(ctx, wf, progress)
		for step in steps:
			_check_no_new_step(ctx, wf)
			_apply(ctx, wf, step, progress)
	except WorkflowException as e:
		# A gateway condition that cannot evaluate on the copied data.
		raise MigrationSkip("Replay stuck", str(e)) from e

	if old.status == "Active":
		_check_no_new_step(ctx, wf)
		new_waits = wait_ids(wf)
		if new_waits != old_waits:
			raise MigrationSkip(
				"Replay stuck",
				_("The new map waits at {0}, the old instance at {1}.").format(
					", ".join(sorted(new_waits)), ", ".join(sorted(old_waits))
				),
			)
		if progress["last_state"] != new_state:
			raise MigrationSkip(
				"State not reached",
				_("The replay last set {0}, not the mapped {1}.").format(progress["last_state"], new_state),
			)
	return wf, progress["last_state"]


def check_instance(ctx, old) -> tuple:
	"""Refuse an instance that cannot be replayed; returns its workflow, its wait points and its mapped new state."""
	old_wf = bpmn_engine.restore_workflow(json.loads(old.workflow_state))
	running = [
		t for t in old_wf.get_tasks(state=TaskState.STARTED) if isinstance(t.task_spec, CallActivityMixin)
	]
	if running:
		raise MigrationSkip(
			"Sub-process running",
			_("{0} has not finished.").format(bpmn_engine.get_task_display_name(running[0])),
		)

	old_waits = wait_ids(old_wf)
	removed = old_waits - ctx.to_ids
	if old.status == "Active" and removed:
		raise MigrationSkip(
			"Waiting at removed step",
			_("The new map has no {0}.").format(", ".join(sorted(removed))),
		)

	if frappe.db.exists(
		"BPMN Process Instance",
		{
			"process_model": ctx.plm.to_model,
			"context_doctype": old.context_doctype,
			"context_docname": old.context_docname,
			"status": "Active",
		},
	):
		raise MigrationSkip(
			"Already on new map", _("The record has an Active instance on {0}.").format(ctx.plm.to_model)
		)

	state = frappe.db.get_value(old.context_doctype, old.context_docname, ctx.state_field)
	if state not in ctx.state_map:
		raise MigrationSkip("No state mapping", _("No State Mapping row for {0}.").format(state))
	return old_wf, old_waits, ctx.state_map[state]


def _history(ctx, old, old_wf) -> list:
	"""The old instance's completed user tasks and received messages that the new map can take, oldest first."""
	rows = frappe.get_all(
		"BPMN Activity Log",
		filters={"instance": old.name, "action": ["in", ["Completed", "Message Received"]]},
		fields=["task_id", "task_name", "action", "data"],
		order_by="timestamp asc, creation asc",
	)
	steps = []
	for row in rows:
		data = json.loads(row.data) if row.data else {}
		if row.action == "Message Received":
			name = row.task_name.removeprefix("Message: ")
			if bpmn_engine.declares_message(ctx.to_wf, name):
				steps.append(frappe._dict(kind="message", name=name, data=data))
			continue

		try:
			task = old_wf.get_task_from_id(UUID(row.task_id))
		except TaskNotFoundException as e:
			raise MigrationSkip(
				"Replay stuck", _("{0} is in the history but not in the old instance.").format(row.task_name)
			) from e
		if task.task_spec.manual and task_bpmn_id(task) in ctx.to_ids:
			steps.append(frappe._dict(kind="user", bpmn_id=task_bpmn_id(task), name=row.task_name, data=data))
	return steps


def _apply(ctx, wf, step, progress) -> None:
	"""Complete one history step on the new map and run on to the next wait point."""
	if step.kind == "user":
		task = next(
			(t for t in bpmn_engine.get_ready_user_tasks(wf) if task_bpmn_id(t) == step.bpmn_id), None
		)
		if task is None:
			raise MigrationSkip(
				"Replay stuck", _("{0} is not waiting when the history completes it.").format(step.name)
			)
		task.data.update(step.data)
		task.run()
	elif not bpmn_engine.send_message(wf, step.name, step.data):
		raise MigrationSkip("Replay stuck", _("Nothing waits for message {0}.").format(step.name))
	_advance(ctx, wf, progress)


def _advance(ctx, wf, progress) -> None:
	"""Run engine steps until only waits remain: scripts do nothing, service tasks and call activities just complete."""
	while _complete_started(ctx, wf, progress) or _run_next(wf):
		progress["runs"] += 1
		if progress["runs"] > TASK_RUN_LIMIT:
			raise MigrationSkip(
				"Replay stuck", _("The new map ran {0} steps without reaching a wait.").format(TASK_RUN_LIMIT)
			)


def _complete_started(ctx, wf, progress) -> bool:
	"""Complete STARTED service tasks and call activities without dispatching them; True if any completed."""
	completed = False
	for task in wf.get_tasks(state=TaskState.STARTED):
		spec = task.task_spec
		if isinstance(spec, CallActivityMixin):
			wf.delete_subprocess(task)
		elif spec.manual or isinstance(spec, (SubWorkflowTask, MultiInstanceTask)):
			continue
		if task_bpmn_id(task) in ctx.set_states:
			progress["last_state"] = ctx.set_states[task_bpmn_id(task)]
		task.complete()
		completed = True
	return completed


def _run_next(wf) -> bool:
	"""Run the next ready engine task; True if one ran."""
	task = wf.get_next_task(state=TaskState.READY, manual=False)
	if task is None:
		wf.refresh_waiting_tasks()
		task = wf.get_next_task(state=TaskState.READY, manual=False)
	if task is None:
		return False
	task.run()
	return True


def _check_no_new_step(ctx, wf) -> None:
	new_steps = wait_ids(wf) - ctx.from_ids
	if new_steps:
		raise MigrationSkip(
			"Past a new step",
			_("The new map stops at {0}, which the old map does not have.").format(
				", ".join(sorted(new_steps))
			),
		)


def state_field(doctype: str) -> str | None:
	"""The field a record's state lives in: workflow_state, else status."""
	meta = frappe.get_meta(doctype)
	return next((f for f in ("workflow_state", "status") if meta.has_field(f)), None)


def wait_ids(wf) -> set:
	"""Element ids of the user tasks and catch events a workflow waits at."""
	user_tasks = {task_bpmn_id(t) for t in bpmn_engine.get_ready_user_tasks(wf)}
	catches = {
		task_bpmn_id(t)
		for t in wf.get_tasks(state=TaskState.WAITING)
		if isinstance(t.task_spec, CatchingEvent)
	}
	return user_tasks | catches


def _old_variables(old_wf) -> dict:
	"""The old instance's workflow variables: root data, then the last completed task, then the tasks it waits at."""
	data = dict(old_wf.task_tree.data)
	if old_wf.last_task:
		data.update(old_wf.last_task.data)
	for task in old_wf.get_tasks(state=TaskState.READY | TaskState.WAITING):
		data.update(task.data)
	data.pop("doc", None)
	return data


def _spec_workflow(spec: dict):
	return bpmn_engine.get_serializer().deserialize_json(json.dumps(spec))


def _element_ids(wf) -> set:
	"""Every element id in a compiled map, its sub-processes included."""
	return {
		ts.bpmn_id
		for spec in (wf.spec, *wf.subprocess_specs.values())
		for ts in spec.task_specs.values()
		if ts.bpmn_id
	}
