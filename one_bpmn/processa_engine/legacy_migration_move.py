# Copyright (c) 2026, one-fm and contributors
"""Move one record to the new map: a new instance from the replay, history and ToDos moved, old retired."""

import json
import re
from typing import TYPE_CHECKING
from uuid import UUID

import frappe
from frappe import _
from frappe.utils import now_datetime
from rq.timeouts import JobTimeoutException

from one_bpmn.processa_engine import engine as bpmn_engine
from one_bpmn.processa_engine.assignment import add_frappe_assignment, resolve_assignee, split_users
from one_bpmn.processa_engine.audit import apply_bpmn_workflow_state
from one_bpmn.processa_engine.legacy_migration_replay import MigrationSkip, replay
from one_bpmn.processa_engine.runtime.common import log_task, task_bpmn_id

if TYPE_CHECKING:
	from one_bpmn.processa_engine.doctype.bpmn_process_instance.bpmn_process_instance import (
		BPMNProcessInstance,
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
	extensions = ctx.to_spec.get("user_task_extensions", {})
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
			"task_actions": extensions.get(bpmn_id, {}).get("taskActions", ""),
			"target_doctype": old.context_doctype,
			"target_docname": old.context_docname,
		}
		if old_row:
			for field in ("assigned_user", "assigned_role", "reliever_user", "relieved_user"):
				row[field] = old_row.get(field)
		else:
			row["assigned_user"], relief_pairs = resolve_assignee(new, task, extensions)
			row["relieved_user"] = ",".join(p[0] for p in relief_pairs)
			row["reliever_user"] = ",".join(p[1] for p in relief_pairs)
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
