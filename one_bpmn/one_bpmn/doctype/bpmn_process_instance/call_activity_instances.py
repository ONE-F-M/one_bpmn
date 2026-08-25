# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A visible Process Instance for each Call Activity a process runs.

A Call Activity names another process, and SpiffWorkflow resolves that name only
against processes the SAME parser has parsed — so ``compile_process_model``
registers the called model's XML alongside the caller's and the called process
becomes a SUBWORKFLOW of the caller. One instance row, one spec, one
``workflow_state``.

That is the right execution model and this module does not change it. What it
changes is what you can SEE. Software Development calls the Orchestrator Agent
that way, and the consequence was that 1,913 Software Development runs had
produced exactly ONE Orchestrator Agent instance — a standalone test from weeks
earlier. The orchestrator's work was happening, and was even visible inside the
caller's own diagram, but it had no run of its own to open, no duration, no
status, and nothing to point at when asking "what did the orchestrator do on this
work item".

It also flattened the delegation chain. When the orchestrator delegates to a
specialist over A2A, the A2A path stamps the child's ``parent_instance`` with
whatever instance is running — which was the CALLER's, not the orchestrator's. So
Software Development appeared to have delegated to the Connector Agent directly,
and the orchestrator that actually made the call was missing from the middle of
its own chain.

HOW
---
The caller's serialized state already contains everything. A serialized
subprocess carries nine of the ten keys a top-level workflow state has — tasks,
root, spec, data, correlations, last_task, completed, success, typename — and
adds ``parent_task_id``. Promoting one to a standalone state therefore means
adding the four keys that only live at the top (``serializer_version``,
``subprocess_specs``, ``subprocesses``, ``bpmn_events``) and dropping the one
that only makes sense inside a parent.

So no extra execution and no second source of truth: the row is a projection of
state the caller already persisted, refreshed whenever the caller persists it.

WHY A PROJECTION AND NOT A REAL SECOND RUN
------------------------------------------
The alternative is to stop calling the orchestrator with a Call Activity and
delegate to it over A2A instead, which would give it a genuinely independent
instance. That is a bigger change than it looks: A2A delegation is
ASYNCHRONOUS. The caller parks and is woken by ``poll_a2a_tasks``, so an inline
call becomes a wait on the reconciler — measured on production at more than six
minutes behind a one-minute schedule, and not firing at all across a 75-second
window. Turning a synchronous call into that, on the main development process,
would trade one missing row for a visible stall.

This keeps execution exactly as it is and adds the row.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

# Keys a top-level workflow state has that a serialized subprocess does not.
_TOP_LEVEL_ONLY = ("serializer_version", "subprocess_specs", "subprocesses", "bpmn_events")

# The key a subprocess carries that a standalone state must not.
_SUBPROCESS_ONLY = "parent_task_id"


def project_subworkflow_state(parent_state: dict, task_id: str) -> dict | None:
	"""Promote one serialized subprocess to a state that stands on its own.

	Returns None when the subprocess is not in the parent's state — a Call
	Activity that has been reached but whose inner workflow has not been
	instantiated yet. That is a normal moment, not an error.

	Nested subprocesses are carried across too, and by ancestry rather than by
	name: an ad-hoc toolbox inside the called process is its own entry in the
	caller's ``subprocesses`` map, and dropping it would leave the projected
	state referring to a subprocess that is not there.
	"""
	subprocesses = parent_state.get("subprocesses") or {}
	sub = subprocesses.get(task_id)
	if not sub:
		return None

	projected = {k: v for k, v in sub.items() if k != _SUBPROCESS_ONLY}

	# Everything nested below this subworkflow, transitively. A subprocess is
	# "below" it when its parent task belongs to a workflow already in the set.
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
	# Specs are shared and cheap; carrying all of them is safer than working out
	# the reachable subset, and a spec the projection never uses costs nothing.
	projected["subprocess_specs"] = parent_state.get("subprocess_specs") or {}
	projected["serializer_version"] = parent_state.get("serializer_version")
	projected["bpmn_events"] = parent_state.get("bpmn_events") or []
	# A subprocess serializes as BpmnSubWorkflow, and that converter takes the
	# parent task and top workflow as arguments — so a state left with that
	# typename cannot be deserialized on its own, however complete it looks. The
	# promotion has to include the type, or restoring the row raises
	# "from_dict() missing 2 required positional arguments".
	projected["typename"] = parent_state.get("typename") or "BpmnWorkflow"

	# ``spec`` is the last difference, and the subtlest: a top-level workflow
	# carries its spec INLINE, while a subprocess carries only the spec's NAME and
	# looks it up in ``subprocess_specs``. Leaving the name in place deserializes
	# far enough to look successful and then fails on first use with
	# "'str' object has no attribute 'data_objects'".
	spec_name = sub.get("spec")
	if isinstance(spec_name, str):
		resolved = (parent_state.get("subprocess_specs") or {}).get(spec_name)
		if not resolved:
			return None  # spec missing: a row we cannot render is worse than none
		projected["spec"] = resolved

	return projected


def _called_process_models(wf) -> dict:
	"""``{parent task id: (called process id, BPMN Process Model name)}``.

	Only Call Activities. A Sub-Process, an ad-hoc subprocess and a Transaction
	are all ``SubWorkflowTask`` subclasses too, and none of them is a call to
	another PROCESS MODEL — they are part of the diagram you are already looking
	at, so giving them their own instance row would be noise.
	"""
	try:
		from SpiffWorkflow.bpmn.specs.mixins.call_activity import CallActivityMixin
	except Exception:  # pragma: no cover - import path differs across versions
		CallActivityMixin = None

	found = {}
	for task in wf.get_tasks():
		spec = task.task_spec
		is_call = (
			isinstance(spec, CallActivityMixin)
			if CallActivityMixin is not None
			else type(spec).__name__ == "CallActivity"
		)
		if not is_call:
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
	"""Create or refresh the child row for every Call Activity in *wf*.

	Idempotent, and keyed on (parent instance, parent task id) so a process that
	calls the same sub-process twice gets a row per call instead of one row
	overwritten by the next.

	Never raises. A missing row is a reporting gap; an exception here would be a
	failed process, and the caller's own run must not depend on its bookkeeping.
	"""
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
				update = {"workflow_state": state_json, "status": status}
				if done and not frappe.db.get_value(
					"BPMN Process Instance", child, "completed_at"
				):
					update["completed_at"] = now_datetime()
				frappe.db.set_value(
					"BPMN Process Instance", child, update, update_modified=False
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
			row.started_at = instance.started_at or now_datetime()
			row.workflow_state = state_json
			# The caller's spec snapshot carries the called process too, because
			# both were parsed together — so the row can render its own diagram
			# without compiling anything a second time.
			row.serialized_spec = instance.serialized_spec
			if done:
				row.completed_at = now_datetime()
			row.flags.ignore_permissions = True
			row.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="Call Activity instance sync failed",
			message=frappe.get_traceback(),
		)
