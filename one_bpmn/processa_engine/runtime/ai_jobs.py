# Copyright (c) 2026, one-fm and contributors
"""Parked AI tasks: an engine pass leaves AI work STARTED and queues one bpmn_ai_agent job per unit to run it."""

import json

import frappe
from frappe.utils.background_jobs import get_queues_timeout

from one_bpmn.processa_engine.agent_runtime import turn_signal
from one_bpmn.processa_engine.agent_runtime.executor import DEFAULT_MAX_RETRIES
from one_bpmn.processa_engine.agent_runtime.job_limits import AI_AGENT_JOB_TIMEOUT, AI_AGENT_QUEUE, ai_agent_queue
from one_bpmn.processa_engine.engine import SubWorkflowTask, TaskState
from one_bpmn.processa_engine.runtime.common import (
	AI_SERVICE_TYPES,
	AI_WAITING_HUMAN_KEY,
	ai_service_type,
	log_task,
	waiting_marker,
)

RUN_PARKED_AI_TASK = "one_bpmn.processa_engine.runtime.ai_jobs.run_parked_ai_task"

# The job id tag and resume kind of each doctype a parked task can wait on.
WAIT_RESUMES = {
	"A2A Task": ("a2a", "a2a_result"),
	"Agent Sandbox Run": ("agent-sandbox", "agent_sandbox_result"),
}


def run_parked_ai_task(
	instance_name: str, kind: str, task_id: str, run_as_user: str | None = None, attempt: int = 0
):
	"""bpmn_ai_agent job: run one parked AI unit and resume the instance.

	A job-level failure re-enqueues with attempt + 1 up to the task's aiMaxRetries, then marks the instance Errored
	and leaves the task parked for a manual retry. LLM failures are retried inside the executor, not here.
	"""
	# set_user rewrites session.sid and wipes session.data, so switch only when the identity differs.
	if run_as_user and run_as_user != frappe.session.user:
		frappe.set_user(run_as_user)

	# The row lock serializes concurrent engine passes on the same instance.
	instance = frappe.get_doc("BPMN Process Instance", instance_name, for_update=True)

	# complete_task rejects user actions while engine_in_progress is set; the finally below always clears it.
	frappe.db.set_value(
		"BPMN Process Instance", instance_name, "engine_in_progress", 1, update_modified=False
	)
	try:
		instance.resume_parked_ai(kind=kind, task_id=task_id)
	except Exception:
		_retry_or_error(instance, kind, task_id, run_as_user, attempt)
	finally:
		frappe.db.set_value(
			"BPMN Process Instance", instance_name, "engine_in_progress", 0, update_modified=False
		)
		# A failed job has to end the waiting request too; the reply itself is read from the database.
		# nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
		frappe.db.commit()
		turn_signal.publish(instance_name)
		frappe.publish_realtime(
			"bpmn_instance_updated",
			{
				"instance_name": instance_name,
				"status": frappe.db.get_value("BPMN Process Instance", instance_name, "status"),
				"waiting_for_ai": frappe.db.get_value(
					"BPMN Process Instance", instance_name, "waiting_for_ai"
				),
				"waiting_for_human": frappe.db.get_value(
					"BPMN Process Instance", instance_name, "waiting_for_human"
				),
				"context_doctype": instance.context_doctype or "",
				"context_docname": instance.context_docname or "",
			},
			after_commit=True,
			user="all",
		)


def _retry_or_error(instance, kind: str, task_id: str, run_as_user: str | None, attempt: int) -> None:
	"""Re-enqueue the failed job under its own job id, or mark the instance Errored once retries run out."""
	instance_name = instance.name
	retry_cap = job_retry_cap(instance, kind, task_id)
	frappe.log_error(
		title=f"BPMN parked AI job failed: {instance_name} (attempt {attempt + 1}/{retry_cap + 1})",
		message=frappe.get_traceback(),
	)
	if attempt < retry_cap:
		frappe.enqueue(
			RUN_PARKED_AI_TASK,
			queue=ai_job_queue_of(instance_name),
			timeout=AI_AGENT_JOB_TIMEOUT,
			enqueue_after_commit=True,
			job_id=f"bpmn-ai-{instance_name}-{task_id}-r{attempt + 1}",
			deduplicate=True,
			instance_name=instance_name,
			kind=kind,
			task_id=task_id,
			run_as_user=run_as_user,
			attempt=attempt + 1,
		)
		return

	frappe.db.set_value("BPMN Process Instance", instance_name, "status", "Errored")
	frappe.db.set_value("BPMN Process Instance", instance_name, "waiting_for_ai", 0, update_modified=False)
	log_task(
		instance,
		task_id=task_id,
		task_name=f"AI job ({kind})",
		action="Errored",
		data={"kind": kind, "attempts": attempt + 1, "error": frappe.get_traceback()[-1000:]},
	)


def job_retry_cap(instance, kind: str, task_id: str) -> int:
	"""Job-level retries for a parked unit: its aiMaxRetries, else the executor's default.

	A service_task id is a runtime UUID, so its config is known only when the model has exactly one ai_agent task.
	"""
	try:
		spec = json.loads(instance.serialized_spec or "{}") or {}
		exts = spec.get("service_task_extensions", {}) or {}
		if kind == "adhoc_decision":
			cfg = exts.get(task_id) or {}
		else:
			ai_cfgs = [c for c in exts.values() if (c or {}).get("serviceType") == "ai_agent"]
			cfg = ai_cfgs[0] if len(ai_cfgs) == 1 else {}
		return int(cfg.get("aiMaxRetries", DEFAULT_MAX_RETRIES) or DEFAULT_MAX_RETRIES)
	except Exception:
		return DEFAULT_MAX_RETRIES


def ai_job_queue(process_model: str | None) -> str:
	"""The queue an AI job for an instance of this process model runs on: its agent's own, else the shared one.

	Frappe refuses a queue the site has not registered under "workers", so until it is the shared queue is used.
	"""
	agent_id = None
	if process_model:
		agent_id = frappe.db.get_value("AI Agent Configuration", {"process_model": process_model}, "agent_id")
	queue = ai_agent_queue(agent_id)
	if queue not in get_queues_timeout():
		frappe.log_error(
			title="AI queue not registered, using the shared queue",
			message=f"Queue {queue} is not under workers in the site config; using {AI_AGENT_QUEUE}",
		)
		return AI_AGENT_QUEUE
	return queue


def ai_job_queue_of(instance_name: str) -> str:
	"""The queue an AI job for this instance runs on."""
	return ai_job_queue(frappe.db.get_value("BPMN Process Instance", instance_name, "process_model"))


def enqueue_wait_resume(instance_name: str, wf_task_id: str, row_name: str, doctype: str) -> None:
	"""Resume a task parked on an A2A Task or Agent Sandbox Run through the parked AI job path.

	resume_enqueued on the row lets the reconciler tell a woken task from one that finished between two checks.
	"""
	if not (instance_name and wf_task_id):
		return
	tag, kind = WAIT_RESUMES[doctype]
	if row_name and frappe.db.exists(doctype, row_name):
		frappe.db.set_value(doctype, row_name, "resume_enqueued", 1, update_modified=False)
	frappe.enqueue(
		RUN_PARKED_AI_TASK,
		queue=ai_job_queue_of(instance_name),
		timeout=AI_AGENT_JOB_TIMEOUT,
		enqueue_after_commit=True,
		job_id=f"bpmn-ai-{instance_name}-{tag}-{row_name}",
		deduplicate=True,
		instance_name=instance_name,
		kind=kind,
		task_id=wf_task_id,
		run_as_user=frappe.session.user,
	)


def ai_parking_active() -> bool:
	"""Whether an engine pass parks its AI work for the bpmn_ai_agent worker instead of running it inline.

	Off in tests unless bpmn_force_ai_parking is set, and off for chat delegation, which waits for the reply in the request.
	"""
	if getattr(frappe.flags, "bpmn_disable_ai_parking", False):
		return False
	if frappe.flags.bpmn_force_ai_parking:
		return True
	return not frappe.flags.in_test


def queue_parked_ai_job(instance, kind: str, ident: str):
	"""Record one parked AI unit to enqueue after this engine pass, once per unit."""
	jobs = getattr(instance, "_pending_ai_jobs", None)
	if jobs is None:
		jobs = instance._pending_ai_jobs = []
	if any(i == ident for _, i in jobs):
		return
	jobs.append((kind, ident))


def has_parked_ai_tasks(instance, wf) -> bool:
	"""Whether an AI service task is still parked in STARTED. A task suspended for a person does not count."""
	for t in wf.get_tasks(state=TaskState.STARTED):
		if getattr(t.task_spec, "manual", False) or isinstance(t.task_spec, SubWorkflowTask):
			continue
		if waiting_marker(t, AI_WAITING_HUMAN_KEY):
			continue
		if ai_service_type(instance, t) in AI_SERVICE_TYPES:
			return True
	return False


def enqueue_parked_ai_jobs(instance):
	"""One AI job per parked AI unit, deduplicated by job_id, on the queue of the instance's agent."""
	jobs, instance._pending_ai_jobs = getattr(instance, "_pending_ai_jobs", []), []
	queue = ai_job_queue(instance.process_model) if jobs else AI_AGENT_QUEUE
	for kind, ident in jobs:
		frappe.enqueue(
			RUN_PARKED_AI_TASK,
			queue=queue,
			timeout=AI_AGENT_JOB_TIMEOUT,
			enqueue_after_commit=True,
			job_id=f"bpmn-ai-{instance.name}-{ident}",
			deduplicate=True,
			instance_name=instance.name,
			kind=kind,
			task_id=ident,
			run_as_user=frappe.session.user,
		)
