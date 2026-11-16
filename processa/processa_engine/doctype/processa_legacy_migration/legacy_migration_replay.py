# Copyright (c) 2026, one-fm and contributors
"""Replay an old instance's history on a new process map without side effects. Writes nothing."""

import datetime
import json
from typing import TYPE_CHECKING
from uuid import UUID

import frappe
from frappe import _

from processa.processa_engine import engine as bpmn_engine
from processa.processa_engine.engine import (
	BpmnWorkflow,
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
from processa.processa_engine.runtime.common import task_bpmn_id

if TYPE_CHECKING:
	from processa.processa_engine.doctype.bpmn_process_instance.bpmn_process_instance import (
		BPMNProcessInstance,
	)
	from processa.processa_engine.doctype.processa_legacy_migration.processa_legacy_migration import (
		ProcessaLegacyMigration,
	)

# Engine steps one replay may run; a loop the history cannot leave hits it.
TASK_RUN_LIMIT = 500
OPEN_INSTANCE_STATUSES = ("Active", "Errored")


class MigrationSkip(Exception):
	"""A record that cannot move; reason is one of the Legacy Migration Error Log reasons."""

	def __init__(self, reason: str, detail: str):
		super().__init__(detail)
		self.reason = reason
		self.detail = detail


class ReplayScriptEngine(FrappeScriptEngine):
	def execute(self, task, script, **kwargs):
		"""Script tasks do not run during a replay; gateway conditions still evaluate."""


def build_context(plm: "ProcessaLegacyMigration") -> frappe._dict:
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


def replay(ctx: frappe._dict, old: "BPMNProcessInstance") -> frappe._dict:
	"""Replay one old instance on the new map. Writes nothing.
	Returns wf (the new workflow), old_wf, new_state (the mapped state) and last_state (the last set)."""
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
	return frappe._dict(wf=wf, old_wf=old_wf, new_state=new_state, last_state=progress["last_state"])


def check_instance(ctx: frappe._dict, old: "BPMNProcessInstance") -> tuple[BpmnWorkflow, set[str], str]:
	"""Refuse an instance that cannot be replayed; returns its workflow, wait points and mapped new state."""
	if old.status not in OPEN_INSTANCE_STATUSES:
		raise MigrationSkip("No longer open", _("The instance is {0}.").format(old.status))
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


def _history(ctx: frappe._dict, old: "BPMNProcessInstance", old_wf: BpmnWorkflow) -> list[frappe._dict]:
	"""The old instance's completed user tasks and received messages that the new map can take, oldest first.

	Rows copied in by an earlier migration name tasks of the instance it came from, so they are read there."""
	rows = frappe.get_all(
		"BPMN Activity Log",
		filters={"instance": old.name, "action": ["in", ["Completed", "Message Received", "Migrated"]]},
		fields=["task_id", "task_name", "action", "data"],
		order_by="timestamp asc, creation asc",
	)
	steps = []
	if old.migrated_from:
		source = frappe.get_doc("BPMN Process Instance", old.migrated_from)
		steps = _history(ctx, source, bpmn_engine.restore_workflow(json.loads(source.workflow_state)))
		# Its own "Migrated" row is the last one; earlier ones were copied with the history.
		own_migrated = max(i for i, row in enumerate(rows) if row.action == "Migrated")
		rows = rows[own_migrated + 1 :]

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
	"""Run engine steps until only waits remain.

	Scripts do nothing; service tasks and call activities complete without running."""
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


def wait_ids(wf: BpmnWorkflow) -> set[str]:
	"""Element ids of the user tasks and catch events a workflow waits at."""
	user_tasks = {task_bpmn_id(t) for t in bpmn_engine.get_ready_user_tasks(wf)}
	catches = {
		task_bpmn_id(t)
		for t in wf.get_tasks(state=TaskState.WAITING)
		if isinstance(t.task_spec, CatchingEvent)
	}
	return user_tasks | catches


def _old_variables(old_wf) -> dict:
	"""The old instance's workflow variables: root data, the last completed task, then its waiting tasks."""
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
