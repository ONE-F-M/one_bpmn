# Copyright (c) 2026, one-fm and contributors
"""Resume a parked AI unit inside its bpmn_ai_agent job, and list the units an instance has parked."""

import uuid

import frappe

from one_bpmn.processa_engine import engine as bpmn_engine
from one_bpmn.processa_engine.dispatch.ai_agent import dispatch_ai_agent
from one_bpmn.processa_engine.engine import SubWorkflowTask, TaskState
from one_bpmn.processa_engine.runtime.active_tasks import persist_workflow
from one_bpmn.processa_engine.runtime.common import (
	A2A_WAITING_KEY,
	AGENT_SANDBOX_WAITING_KEY,
	AI_SERVICE_TYPES,
	AI_WAITING_HUMAN_KEY,
	ai_service_type,
	load_json,
	restore_instance_workflow,
	task_bpmn_id,
	waiting_marker,
)
from one_bpmn.processa_engine.runtime.dispatch import (
	dispatch_service_task,
	on_adhoc_task_complete,
	on_engine_task_complete,
)
from one_bpmn.processa_engine.runtime.engine_loop import run_engine
from one_bpmn.processa_engine.runtime.human_tasks import on_ai_agent_suspended
from one_bpmn.processa_engine.runtime.remote_waits import apply_a2a_result, apply_agent_sandbox_result

# The marker and result function of each remote a parked task can wait on, by resume kind.
REMOTE_RESULTS = {
	"a2a_result": (A2A_WAITING_KEY, apply_a2a_result),
	"agent_sandbox_result": (AGENT_SANDBOX_WAITING_KEY, apply_agent_sandbox_result),
}


def resume_parked_ai(instance, kind: str, task_id: str):
	"""Run one parked AI unit and carry the flow on. A unit already resolved elsewhere is a no-op.

	kind is service_task or human_resume (task_id is the task UUID), a2a_result or agent_sandbox_result (a remote
	finished), or adhoc_decision (task_id is the ad-hoc subprocess; exactly one selector decision runs inline).
	"""
	if instance.status in ("Completed", "Cancelled", "Suspended"):
		return
	if not instance.workflow_state:
		return

	wf = restore_instance_workflow(instance)
	prev_assigned = {
		row.assigned_user for row in instance.active_tasks if row.status == "Waiting" and row.assigned_user
	}

	previous_flag = frappe.flags.bpmn_engine_action
	frappe.flags.bpmn_engine_action = True
	try:
		if kind in REMOTE_RESULTS or kind in ("service_task", "human_resume"):
			task = _started_task(wf, task_id)
			if task is None:
				return
			done = (
				_apply_remote_result(instance, task, kind)
				if kind in REMOTE_RESULTS
				else _run_ai_task(instance, task, kind)
			)
			if not done:
				return
		else:
			frappe.flags.bpmn_ai_resume_target = task_id

		run_engine(instance, wf)
	finally:
		frappe.flags.bpmn_engine_action = previous_flag
		frappe.flags.bpmn_ai_resume_target = None

	persist_workflow(instance, wf, prev_assigned)


def _started_task(wf, task_id: str):
	"""The workflow task with this UUID when it is still STARTED, else None."""
	try:
		task = wf.get_task_from_id(uuid.UUID(task_id))
	except Exception:
		return None
	return task if task.state == TaskState.STARTED else None


def _apply_remote_result(instance, task, kind: str) -> bool:
	"""Apply a finished delegation or sandbox run to its parked task and complete it; False while it still runs."""
	key, apply_result = REMOTE_RESULTS[kind]
	marker = waiting_marker(task, key)
	if not marker or not apply_result(instance, task, marker):
		return False
	instance.waiting_for_ai = 0
	on_engine_task_complete(instance, task)
	task.complete()
	return True


def _run_ai_task(instance, task, kind: str) -> bool:
	"""Dispatch a parked AI task, or resume its suspended agent, then complete it or open its human task.

	False when there is nothing to do: a suspended task asked to dispatch again, or a human_resume with no suspension.
	"""
	marker = waiting_marker(task, AI_WAITING_HUMAN_KEY)
	if kind == "service_task":
		# A re-kicked job or manual retry must not restart an agent that is waiting for a person.
		if marker:
			return False
		dispatch_service_task(instance, task)
	else:
		if not marker:
			return False
		bpmn_id = task_bpmn_id(task)
		task_cfg = getattr(instance, "_service_task_extensions", {}).get(bpmn_id) or {}
		# Claims the checkpoint atomically; a lost race leaves the marker and the state re-persists unchanged.
		dispatch_ai_agent(instance, task, task_cfg, bpmn_id, resume_run=marker.get("run") or None)

	if waiting_marker(task, AI_WAITING_HUMAN_KEY):
		on_ai_agent_suspended(instance, task)
		return True
	instance.waiting_for_human = ""
	on_engine_task_complete(instance, task)
	task.complete()
	if isinstance(getattr(task.workflow, "spec", None), bpmn_engine.AdHocSubprocessSpec) and getattr(
		task.task_spec, "bpmn_id", None
	):
		on_adhoc_task_complete(instance, task)
	return True


def get_parked_ai_units(instance) -> list:
	"""The AI units parked on this instance as {kind, task_id, bpmn_id, label, since}; since is epoch seconds.

	task_id is what retry_ai_task and run_parked_ai_task expect; a service_task unit also names what it waits_on.
	"""
	if not instance.workflow_state:
		return []

	spec_snap = load_json(instance.serialized_spec or "{}") or {}
	instance._service_task_extensions = spec_snap.get("service_task_extensions", {})

	wf = bpmn_engine.restore_workflow(
		workflow_state=load_json(instance.workflow_state),
		context_doctype=instance.context_doctype,
		context_docname=instance.context_docname,
	)

	units = []
	for t in wf.get_tasks(state=TaskState.STARTED):
		if getattr(t.task_spec, "manual", False):
			continue
		bpmn_id = task_bpmn_id(t)
		if isinstance(t.task_spec, SubWorkflowTask):
			cfg = instance._service_task_extensions.get(bpmn_id) or {}
			if cfg.get("serviceType") != "ai_task_selector":
				continue
			# An active inner head means the selector is mid-turn, not waiting for a decision.
			sp = getattr(wf, "subprocesses", {}).get(t.id)
			if sp is not None and sp.get_tasks(state=TaskState.READY | TaskState.STARTED):
				continue
			units.append({"kind": "adhoc_decision", "task_id": bpmn_id, **_unit(t, bpmn_id)})
		elif ai_service_type(instance, t) in AI_SERVICE_TYPES:
			# An agent suspended for a person is not waiting for an AI job.
			if waiting_marker(t, AI_WAITING_HUMAN_KEY):
				continue
			units.append(
				{
					"kind": "service_task",
					"task_id": str(t.id),
					**_unit(t, bpmn_id),
					"waits_on": parked_task_waits_on(t),
				}
			)
	return units


def _unit(task, bpmn_id: str) -> dict:
	"""The fields every parked unit carries."""
	return {
		"bpmn_id": bpmn_id,
		"label": bpmn_engine.get_task_display_name(task),
		"since": task.last_state_change,
	}


def parked_task_waits_on(task) -> str:
	"""What a parked AI task waits for: "a2a", "agent_sandbox", or "" when it waits for its own job."""
	if waiting_marker(task, A2A_WAITING_KEY):
		return "a2a"
	return "agent_sandbox" if waiting_marker(task, AGENT_SANDBOX_WAITING_KEY) else ""
