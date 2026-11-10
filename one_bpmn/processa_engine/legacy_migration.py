# Copyright (c) 2026, one-fm and contributors
"""Processa Legacy Migration runs: background batches, the hourly check, finish and moving one record."""

import json
import re
from typing import TYPE_CHECKING
from uuid import UUID

import frappe
from frappe import _
from frappe.utils import create_batch, now_datetime
from frappe.utils.background_jobs import is_job_enqueued
from rq.timeouts import JobTimeoutException

from one_bpmn.processa_engine import engine as bpmn_engine
from one_bpmn.processa_engine.assignment import add_frappe_assignment, resolve_assignment, split_users
from one_bpmn.processa_engine.audit import apply_bpmn_workflow_state
from one_bpmn.processa_engine.legacy_migration_replay import (
	OPEN_INSTANCE_STATUSES,
	MigrationSkip,
	build_context,
	replay,
)
from one_bpmn.processa_engine.runtime.common import log_task, task_bpmn_id
from one_bpmn.processa_engine.runtime.messages import receive_message

if TYPE_CHECKING:
	from one_bpmn.processa_engine.doctype.bpmn_process_instance.bpmn_process_instance import (
		BPMNProcessInstance,
	)

BATCH_SIZE = 25
FINISHED_MESSAGE = "processa:legacy_migration:finished"


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
		log_error_row(migration_name, frappe._dict(), "Error", str(e), idx=1)
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
			first_idx=(n - 1) * BATCH_SIZE + 1,
		)


def run_batch(migration_name: str, instance_names: list[str], first_idx: int = 1) -> None:
	"""Move one batch, committing after each record; a timeout or failure logs every record it did not move.
	A record's Error Log row gets idx first_idx plus its place in the batch, so batches never share one."""
	moved = failed = reached = 0
	try:
		ctx = build_context(frappe.get_doc("Processa Legacy Migration", migration_name))
		frappe.only_for(["System Manager", "Process Owner"])
		for name in instance_names:
			if _migrate_by_name(ctx, name, first_idx + reached):
				moved += 1
			else:
				failed += 1
			reached += 1
			frappe.db.commit()
	except Exception as e:
		frappe.db.rollback()
		if isinstance(e, JobTimeoutException):
			reason, detail = "Timed out", _("The batch ran out of time.")
		else:
			reason, detail = "Error", frappe.get_traceback(with_context=False)
		failed += _log_unmoved(migration_name, instance_names[reached:], reason, detail, first_idx + reached)
		_count_batch(migration_name, moved, failed)
		raise
	_count_batch(migration_name, moved, failed)


def _migrate_by_name(ctx: frappe._dict, name: str, idx: int) -> bool:
	"""migrate_record for one instance name; an instance deleted since start gets an Error Log row instead."""
	if not frappe.db.exists("BPMN Process Instance", name):
		detail = _("The instance was deleted before its batch ran.")
		log_error_row(ctx.plm.name, frappe._dict(name=name), "No longer open", detail, idx)
		return False
	return migrate_record(ctx, frappe.get_doc("BPMN Process Instance", name), idx)


def fail_stalled_migrations() -> None:
	"""Hourly: end Queued or Running runs whose jobs are all gone, logging the records they never reached.

	A migration whose check fails is rolled back and logged, so the others are still checked."""
	for name in frappe.get_all(
		"Processa Legacy Migration", filters={"status": ["in", ["Queued", "Running"]]}, pluck="name"
	):
		try:
			_fail_if_stalled(name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				title=_("Processa Legacy Migration stalled-run check failed"),
				reference_doctype="Processa Legacy Migration",
				reference_name=name,
			)
			frappe.db.commit()


def _fail_if_stalled(name: str) -> None:
	plm = frappe.get_doc("Processa Legacy Migration", name)
	job_ids = [f"plm::{name}::start", *(f"plm::{name}::{n}" for n in range(1, plm.total_batches + 1))]
	if any(is_job_enqueued(job_id) for job_id in job_ids):
		return

	logged = {row.old_instance for row in plm.error_logs}
	unhandled = [
		instance
		for instance in frappe.get_all(
			"BPMN Process Instance",
			filters={
				"process_model": plm.from_model,
				"context_doctype": plm.target_doctype,
				"status": ["in", OPEN_INSTANCE_STATUSES],
			},
			pluck="name",
		)
		if instance not in logged
	]
	detail = _("The run's background job stopped before this record moved.")
	next_idx = max((row.idx for row in plm.error_logs), default=0) + 1
	failed = _log_unmoved(name, unhandled, "Timed out", detail, next_idx)
	frappe.db.set_value("Processa Legacy Migration", name, "failed_count", plm.failed_count + failed)
	finish(name)


def _log_unmoved(
	migration_name: str, instance_names: list[str], reason: str, detail: str, first_idx: int
) -> int:
	"""An Error Log row for each instance a batch did not move, deleted ones included; returns how many."""
	instances = {
		d.name: d
		for d in frappe.get_all(
			"BPMN Process Instance",
			filters={"name": ["in", instance_names]},
			fields=["name", "context_doctype", "context_docname"],
		)
	}
	for i, name in enumerate(instance_names):
		old = instances.get(name, frappe._dict(name=name))
		log_error_row(migration_name, old, reason, detail, first_idx + i)
	return len(instance_names)


def _count_batch(migration_name: str, moved: int, failed: int) -> None:
	"""Add one batch's counts in a single update and commit them; the batch that ends the run calls finish.

	The counts commit before finish, so a finish that fails leaves the run for the hourly check to finish."""
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
	frappe.db.commit()
	if plm.batches_done == plm.total_batches:
		finish(migration_name)
		frappe.db.commit()


def finish(migration_name: str) -> None:
	"""Close a run: Completed when a record moved or there was nothing to move, else Failed.

	Tells the PLM's own process through the finish message."""
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


def migrate_record(ctx: frappe._dict, old: "BPMNProcessInstance", idx: int) -> bool:
	"""Move one record fully or not at all; one that cannot move gets Error Log row idx. True when it moved.

	Commits nothing: the batch job commits after each record, so a refused record's row is kept with it."""
	frappe.db.savepoint("plm_record")
	try:
		result = replay(ctx, old)
		new = _insert_new_instance(ctx, old, result)
		_copy_history(ctx, old, new)
		_repoint_todos(old, new)
		_retire(old, new)
		previous_flag = frappe.flags.bpmn_engine_action
		frappe.flags.bpmn_engine_action = True
		try:
			apply_bpmn_workflow_state(
				old.context_doctype,
				old.context_docname,
				result.new_state,
				triggered_by=frappe.session.user,
			)
		finally:
			frappe.flags.bpmn_engine_action = previous_flag
	except MigrationSkip as skip:
		frappe.db.rollback(save_point="plm_record")
		log_error_row(ctx.plm.name, old, skip.reason, skip.detail, idx)
		return False
	except JobTimeoutException:
		# run_batch logs the timed-out record together with the ones its batch did not reach.
		raise
	except Exception:
		frappe.db.rollback(save_point="plm_record")
		log_error_row(ctx.plm.name, old, "Error", frappe.get_traceback(with_context=False), idx)
		return False
	return True


def log_error_row(
	plm_name: str, old: "BPMNProcessInstance | frappe._dict", reason: str, detail: str, idx: int
) -> None:
	"""Add Legacy Migration Error Log row idx for a record that did not move."""
	frappe.get_doc(
		{
			"doctype": "Legacy Migration Error Log",
			"parent": plm_name,
			"parenttype": "Processa Legacy Migration",
			"parentfield": "error_logs",
			"idx": idx,
			"document_doctype": old.context_doctype,
			"document_name": old.context_docname,
			"old_instance": old.name,
			"reason": reason,
			"error_message": detail,
			"timestamp": now_datetime(),
		}
	).db_insert()


def _insert_new_instance(
	ctx: frappe._dict, old: "BPMNProcessInstance", result: frappe._dict
) -> "BPMNProcessInstance":
	"""The new instance, waiting where the replay stopped, with tasks assigned like the old ones. No email."""
	wf = result.wf
	old_rows = {}
	for row in old.active_tasks:
		if row.status == "Waiting":
			old_rows[task_bpmn_id(result.old_wf.get_task_from_id(UUID(row.task_id)))] = row

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


def _copy_history(ctx: frappe._dict, old: "BPMNProcessInstance", new: "BPMNProcessInstance") -> None:
	"""Copy the old instance's Activity Log to the new one with original users and times; log the move."""
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
	# Its own task id: a "Migrated" row copied from an earlier move must not stop log_task writing this one.
	log_task(
		new,
		f"migrated::{old.name}",
		_("Migrated"),
		"Migrated",
		{"migrated_from": old.name, "migration": ctx.plm.name},
	)


def _repoint_todos(old: "BPMNProcessInstance", new: "BPMNProcessInstance") -> None:
	"""Open process ToDos on the record that name the old instance now name the new one."""
	old_name = re.compile(rf"(?<![\w-]){re.escape(old.name)}(?![\w-])")
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
		if old_name.search(todo.description):
			frappe.db.set_value("ToDo", todo.name, "description", old_name.sub(new.name, todo.description))


def _retire(old: "BPMNProcessInstance", new: "BPMNProcessInstance") -> None:
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
