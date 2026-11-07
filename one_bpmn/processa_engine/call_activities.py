# Copyright (c) 2026, one-fm and contributors
"""Keep a visible Process Instance for each Call Activity a process runs.
Each row is a projection of the caller's serialized subworkflow state, refreshed whenever the caller persists."""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

# Keys a top-level workflow state has that a serialized subprocess does not.
_TOP_LEVEL_ONLY = ("serializer_version", "subprocess_specs", "subprocesses", "bpmn_events")

# The key a subprocess carries that a standalone state must not.
_SUBPROCESS_ONLY = "parent_task_id"


def project_subworkflow_state(parent_state: dict, task_id: str) -> dict | None:
	"""Promote one serialized subprocess, with the subprocesses nested below it, to a standalone workflow state.
	Returns None when its inner workflow is not instantiated yet or its spec is missing."""
	subprocesses = parent_state.get("subprocesses") or {}
	sub = subprocesses.get(task_id)
	if not sub:
		return None

	projected = {k: v for k, v in sub.items() if k != _SUBPROCESS_ONLY}

	# A subprocess is nested below when its parent task belongs to a workflow already in the set.
	descendants: dict = {}
	frontier = {task_id}
	while frontier:
		owned_tasks = set()
		for tid in frontier:
			owned_tasks |= set((subprocesses.get(tid, {}).get("tasks") or {}).keys())
		nxt = set()
		for other_id, other in subprocesses.items():
			if other_id in descendants or other_id == task_id:
				continue
			if other.get(_SUBPROCESS_ONLY) in owned_tasks:
				descendants[other_id] = other
				nxt.add(other_id)
		frontier = nxt

	projected["subprocesses"] = descendants
	projected["subprocess_specs"] = parent_state.get("subprocess_specs") or {}
	projected["serializer_version"] = parent_state.get("serializer_version")
	projected["bpmn_events"] = parent_state.get("bpmn_events") or []
	# A BpmnSubWorkflow typename needs a parent to deserialize, so use the top-level type.
	projected["typename"] = parent_state.get("typename") or "BpmnWorkflow"

	# A subprocess stores only its spec name; a standalone state needs the spec inline.
	spec_name = sub.get("spec")
	if isinstance(spec_name, str):
		resolved = (parent_state.get("subprocess_specs") or {}).get(spec_name)
		if not resolved:
			return None  # spec missing: a row we cannot render is worse than none
		projected["spec"] = resolved

	return projected


def _called_process_models(wf) -> dict:
	"""Map each Call Activity task id to (called process id, BPMN Process Model name).
	Sub-Processes, ad-hoc subprocesses and Transactions are skipped; they belong to the caller's own diagram."""
	from one_bpmn.processa_engine.engine import CallActivityMixin

	found = {}
	for task in wf.get_tasks():
		spec = task.task_spec
		if not isinstance(spec, CallActivityMixin):
			continue
		called = getattr(spec, "spec", None)
		if not called:
			continue
		model = frappe.db.get_value(
			"BPMN Process Model", {"process_id": called, "is_active": 1}, "name"
		) or frappe.db.get_value("BPMN Process Model", {"process_id": called}, "name")
		if model:
			found[str(task.id)] = (called, model)
	return found


def sync_call_activity_instances(instance, wf) -> None:
	"""Create or refresh one child instance row per Call Activity call in *wf*, keyed on parent instance and task id.
	Never raises: a missing row is a reporting gap, but an exception would fail the caller's run."""
	try:
		if not instance.name or not getattr(wf, "subprocesses", None):
			return

		called = _called_process_models(wf)
		if not called:
			return

		parent_state = json.loads(instance.workflow_state or "{}")

		for task_id, (_process_id, model) in called.items():
			projected = project_subworkflow_state(parent_state, task_id)
			if projected is None:
				continue  # inner workflow not instantiated yet

			done = bool(projected.get("completed"))
			status = "Completed" if done else "Active"

			child = frappe.db.get_value(
				"BPMN Process Instance",
				{"parent_instance": instance.name, "parent_task_id": task_id},
				"name",
			)
			state_json = json.dumps(projected)

			if child:
				was = frappe.db.get_value(
					"BPMN Process Instance", child, ["status", "completed_at"], as_dict=True
				)
				update = {"workflow_state": state_json, "status": status}
				if done and not was.completed_at:
					update["completed_at"] = now_datetime()
				# Bump modified only when the status changes, so Last Updated tracks real transitions.
				changed = status != was.status
				frappe.db.set_value(
					"BPMN Process Instance", child, update, update_modified=changed
				)
				continue

			row = frappe.new_doc("BPMN Process Instance")
			row.process_model = model
			row.parent_instance = instance.name
			row.parent_task_id = task_id
			row.status = status
			row.context_doctype = instance.context_doctype
			row.context_docname = instance.context_docname
			row.initiated_by = instance.initiated_by
			# When this sync first saw the subworkflow, not the caller's start, which can be hours earlier.
			row.started_at = now_datetime()
			row.workflow_state = state_json
			# The caller's spec snapshot already includes the called process.
			row.serialized_spec = instance.serialized_spec
			if done:
				row.completed_at = now_datetime()
			row.flags.ignore_permissions = True  # engine-owned child instance row
			row.insert(ignore_permissions=True)  # engine-owned child instance row
	except Exception:
		frappe.log_error(
			title="Call Activity instance sync failed",
			message=frappe.get_traceback(),
		)
