# Copyright (c) 2026, one-fm and contributors
"""One engine pass: run automated tasks, dispatch Service Tasks, park AI work and deliver buffered messages."""

import json

import frappe

from processa.processa_engine import engine as bpmn_engine
from processa.processa_engine.engine import MultiInstanceTask, SubWorkflowTask, TaskState
from processa.processa_engine.runtime.ai_jobs import (
	ai_parking_active,
	enqueue_parked_ai_jobs,
	has_parked_ai_tasks,
	queue_parked_ai_job,
)
from processa.processa_engine.runtime.common import (
	A2A_WAITING_KEY,
	AGENT_SANDBOX_WAITING_KEY,
	AI_WAITING_HUMAN_KEY,
	ai_service_type,
	load_json,
	log_task,
	waiting_marker,
)
from processa.processa_engine.runtime.dispatch import (
	dispatch_service_task,
	log_adhoc_activation,
	on_adhoc_task_complete,
	on_engine_task_complete,
)
from processa.processa_engine.runtime.human_tasks import on_ai_agent_suspended

ENGINE_PASS_CAP = 20
BUFFERED_MESSAGE_TTL_HOURS = 24
BUFFERED_MESSAGES_KEPT = 20


def run_engine(instance, wf):
	"""Run automated tasks until only User Tasks, waits and parked work remain, then queue the parked AI jobs.

	The caller saves the instance right after; the jobs fire after commit, so they always see the parked state.
	"""
	from processa.processa_engine.task_selector import make_adhoc_decider

	# Process-global engine hooks: the AI Task Selector decider and the ad-hoc activation audit.
	bpmn_engine.adhoc.adhoc_next_task_decider = make_adhoc_decider(instance, wf)
	bpmn_engine.adhoc.adhoc_task_activated_logger = lambda sp, task: log_adhoc_activation(instance, sp, task)
	instance._pending_ai_jobs = []
	try:
		run_engine_inner(instance, wf)
		deliver_buffered_messages(instance, wf)
	finally:
		bpmn_engine.adhoc.adhoc_next_task_decider = None
		bpmn_engine.adhoc.adhoc_task_activated_logger = None

	instance.waiting_for_ai = 1 if (instance._pending_ai_jobs or has_parked_ai_tasks(instance, wf)) else 0
	enqueue_parked_ai_jobs(instance)


def run_engine_inner(instance, wf):
	"""Step the engine and dispatch every STARTED Service Task, for up to ENGINE_PASS_CAP passes."""
	wf.refresh_waiting_tasks()

	cap_hit = True
	for _ in range(ENGINE_PASS_CAP):
		bpmn_engine.do_engine_steps_gated(
			wf,
			did_complete_task=lambda task: on_engine_task_complete(instance, task),
			did_complete_adhoc_task=lambda task: on_adhoc_task_complete(instance, task),
		)

		started_tasks = _dispatchable_tasks(wf)

		# AI service tasks stay STARTED and only their LLM work is queued; non-AI siblings still dispatch inline.
		if ai_parking_active():
			parked = [t for t in started_tasks if ai_service_type(instance, t) == "ai_agent"]
			for t in parked:
				queue_parked_ai_job(instance, "service_task", str(t.id))
			started_tasks = [t for t in started_tasks if t not in parked]

		if not started_tasks:
			cap_hit = False
			break

		for task in started_tasks:
			_dispatch_and_complete(instance, task)

	if cap_hit:
		# Not raised: the state serializes and the next advance() carries on from here.
		pending_adhoc = bpmn_engine.adhoc_pending_head_tasks(wf)
		frappe.log_error(
			title="BPMN _run_engine pass cap reached",
			message=(
				f"Instance {instance.name}: 20-pass cap hit with work remaining. "
				f"Parked ad-hoc heads: {[t.task_spec.name for t in pending_adhoc]}. "
				"Execution resumes on the next advance() call."
			),
		)

	# Catches conditional events that became true during the passes above.
	wf.refresh_waiting_tasks()


def _dispatchable_tasks(wf) -> list:
	"""STARTED tasks the loop must dispatch: not manual, not a container, not waiting on a person or a remote.

	Sub-process and Multi-Instance parents sit in STARTED while their children run and complete on their own.
	"""
	return [
		t
		for t in wf.get_tasks(state=TaskState.STARTED)
		if not getattr(t.task_spec, "manual", False)
		and not isinstance(t.task_spec, SubWorkflowTask)
		and not isinstance(t.task_spec, MultiInstanceTask)
		and not waiting_marker(t, AI_WAITING_HUMAN_KEY)
		and not waiting_marker(t, A2A_WAITING_KEY)
		and not waiting_marker(t, AGENT_SANDBOX_WAITING_KEY)
	]


def _dispatch_and_complete(instance, task) -> None:
	"""Dispatch one Service Task and complete it, unless the dispatch left it waiting on a person or a remote."""
	dispatch_service_task(instance, task)
	if waiting_marker(task, AI_WAITING_HUMAN_KEY):
		on_ai_agent_suspended(instance, task)
		return
	# A delegation or sandbox run resumes this task later through its a2a_result or agent_sandbox_result job.
	if waiting_marker(task, A2A_WAITING_KEY) or waiting_marker(task, AGENT_SANDBOX_WAITING_KEY):
		instance.waiting_for_ai = 1
		return
	on_engine_task_complete(instance, task)
	task.complete()
	# Ad-hoc inner tasks: refresh and record after the dispatch's writes, since completion conditions run next.
	if isinstance(getattr(task.workflow, "spec", None), bpmn_engine.AdHocSubprocessSpec) and getattr(
		task.task_spec, "bpmn_id", None
	):
		on_adhoc_task_complete(instance, task)


def live_buffered_messages(instance) -> list:
	"""Buffered messages still inside their time limit, oldest first."""
	return [
		m
		for m in load_json(instance.buffered_messages) or []
		if frappe.utils.time_diff_in_hours(frappe.utils.now(), m["received_at"]) < BUFFERED_MESSAGE_TTL_HOURS
	]


def deliver_buffered_messages(instance, wf):
	"""Hand each buffered message to the wait that now catches it, until no more are taken."""
	pending = live_buffered_messages(instance)
	delivered = True
	while delivered and pending:
		delivered = False
		for message in list(pending):
			if bpmn_engine.send_message(wf, message["name"], message["payload"]):
				pending.remove(message)
				log_task(
					instance,
					f"buffered:{message['received_at']}:{message['name']}",
					f"Message: {message['name']}",
					"Message Received",
					message["payload"],
				)
				run_engine_inner(instance, wf)
				delivered = True
	instance.buffered_messages = json.dumps(pending) if pending else None
