# Copyright (c) 2026, one-fm and contributors
"""Ad-hoc subprocess dispatch: one inner task at a time, with decide and audit hooks."""

from SpiffWorkflow.bpmn.specs.bpmn_process_spec import AdHocSubprocessSpec
from SpiffWorkflow.bpmn.specs.control import BpmnStartTask, SimpleBpmnTask, _EndJoin
from SpiffWorkflow.bpmn.specs.mixins.multiinstance_task import LoopTask
from SpiffWorkflow.bpmn.workflow import BpmnWorkflow
from SpiffWorkflow.util.task import TaskState

# ─────────────────────────────────────────────────────────────
# Ad-hoc subprocess dispatch loop
#
# SpiffWorkflow readies EVERY unconditional no-input inner task the moment
# an ad-hoc subprocess is entered, and AdHocSubprocessSpec.parallel is
# stored but never read anywhere in its execution logic - the library has
# no working sequential mode (its parser outright rejects
# ordering="sequential"). processa's confirmed requirement is one inner
# task at a time, so the gate below enforces it: exactly one "head" task
# (a task connected from the subprocess start) may be READY/STARTED/WAITING
# at any moment; the rest are parked in FUTURE and promoted one by one, in
# the order the tasks appear in the diagram XML. Story 2-02 later swaps
# the "next in diagram order" decision for an LLM call - same loop, a
# different decision function.
# ─────────────────────────────────────────────────────────────

_ADHOC_ACTIVE_MASK = TaskState.READY | TaskState.STARTED | TaskState.WAITING


def _adhoc_subworkflows(wf: BpmnWorkflow) -> list:
	return [
		sp
		for sp in wf.subprocesses.values()
		if isinstance(sp.spec, AdHocSubprocessSpec) and not sp.completed
	]


def adhoc_head_tasks(sp) -> list:
	"""
	Inner tasks of an ad-hoc subworkflow, in diagram-XML order.

	"Heads" are the task instances whose specs AdHocSubprocessSpec connected
	to the subprocess start - both the unconditional no-input tasks connected
	at parse time (create_paths) and conditional loop/multi-instance/gateway
	paths the spec attaches later (add_path).
	"""
	head_specs = {
		spec
		for spec in sp.spec.start.outputs
		if not isinstance(spec, (BpmnStartTask, _EndJoin, SimpleBpmnTask))
	}
	diagram_order = list(sp.spec.task_specs)
	tasks = [t for t in sp.get_tasks(skip_subprocesses=True) if t.task_spec in head_specs]
	tasks.sort(key=lambda t: diagram_order.index(t.task_spec.name))
	return tasks


def _adhoc_completion_met(sp) -> bool:
	condition = sp.spec.completion_condition
	if not condition:
		return False
	try:
		return bool(sp.script_engine.environment.evaluate(condition, sp.data))
	except Exception:
		# An unevaluable condition must never wedge the loop; treat as not met
		# (path_complete applies the same evaluation on its own schedule).
		return False


def _arm_loop_instance(task) -> bool:
	"""
	Start a conditionally re-added loop/multi-instance head properly.

	AdHocSubprocessSpec.add_path() materializes these instances directly in
	READY, bypassing _update_hook - running such a task completes it with
	zero iterations, path_complete re-adds it, and the engine spins forever
	(reproducible with stock do_engine_steps too). Routing the instance
	through _update fires _update_hook, which moves it to STARTED and spawns
	its first iteration child.
	"""
	if isinstance(task.task_spec, LoopTask) and task.state == TaskState.READY:
		# Children include predicted flow successors (e.g. the EndJoin);
		# only children instantiated from the loop's inner spec count as
		# iterations. merge_child() sets the task READY again once the loop
		# is complete - that READY must run to completion, not re-arm.
		has_iteration = any(
			child.task_spec.name == task.task_spec.task_spec for child in task.children
		)
		if not has_iteration and not task.internal_data.get("merged"):
			task.task_spec._update(task)
			return True
	return False


def _gate_adhoc_subworkflow(sp) -> bool:
	"""
	Enforce the one-task-at-a-time invariant on a single ad-hoc subworkflow.

	Returns True when a task state was changed (the engine sweep must rerun).
	"""
	# Upstream path_complete()/add_path() unconditionally pop "data_objects"
	# from task data after merging workflow.data in - diagrams without any
	# <bpmn:dataObject> would crash there, so make sure the key exists.
	sp.data.setdefault("data_objects", {})

	heads = adhoc_head_tasks(sp)
	active = [t for t in heads if t.state & _ADHOC_ACTIVE_MASK]

	if len(active) > 1:
		if all(t.state == TaskState.READY for t in active):
			# Subprocess entry: SpiffWorkflow readied every head at once.
			# Park them ALL and let the promotion step below choose the
			# first task - the AI Task Selector decider gets to pick even
			# the FIRST task (user decision 2026-07-04); plain ad-hoc
			# subprocesses fall through to diagram order in
			# select_next_adhoc_task, identical to the previous behavior.
			for task in active:
				task._set_state(TaskState.FUTURE)
			return True
		# Mixed states - an in-flight head plus conditionally re-added
		# READY heads: keep the first in diagram order, park the rest.
		changed = False
		for extra in active[1:]:
			if extra.state == TaskState.READY:
				extra._set_state(TaskState.FUTURE)
				changed = True
		if changed:
			notify_adhoc_activation(sp, active[0])  # audit hook
		return _arm_loop_instance(active[0]) or changed

	if len(active) == 1:
		return _arm_loop_instance(active[0])

	pending = [t for t in heads if t.state == TaskState.FUTURE]
	if not pending:
		return False
	if _adhoc_completion_met(sp):
		# Condition already true: never-started tasks must not start.
		# cancel_remaining only governs tasks that are already running
		# (path_complete handles those); parked heads are cancelled here
		# so the subprocess EndJoin can complete.
		for task in pending:
			task.cancel()
		# Joins don't re-evaluate on their own when a sibling branch is
		# cancelled after the fact - poke them so completion propagates.
		for task in sp.get_tasks(spec_class=_EndJoin):
			if task.state & TaskState.NOT_FINISHED_MASK:
				task.task_spec._update(task)
	else:
		# Continuation work still awaiting dispatch - a chained service task
		# (e.g. "set status after escalation") sits in STARTED until
		# run_engine_inner's dispatch loop executes it. Consulting the
		# selector before that write lands feeds it STALE document state
		# (UAT: a decision saw "Pending Support Confirmation" after the
		# agent had already resolved). Heads can't be STARTED here (the
		# active-head checks above returned), so any STARTED non-manual
		# task is a pending continuation: hold promotion, let the dispatch
		# loop finish, and decide on the next sweep with fresh evidence.
		if any(
			not getattr(t.task_spec, "manual", False)
			for t in sp.get_tasks(state=TaskState.READY | TaskState.STARTED)
		):
			# READY = the gated loop will run it this sweep; STARTED = the
			# dispatch loop will complete it. Either way: not yet landed.
			# (Heads can't appear here - active heads returned above. Manual
			# continuation tasks are excluded: a chained user task can wait
			# days and must not gag the selector.)
			return False

		# an installed AI Task Selector decider replaces the
		# default "next in diagram order" decision. No decider (or a
		# declined decision) falls through to pending[0].
		promoted = select_next_adhoc_task(sp, pending)
		if promoted is None:
			return False
		promoted._set_state(TaskState.READY)
		_arm_loop_instance(promoted)
		notify_adhoc_activation(sp, promoted)  # audit hook
	return True


def do_engine_steps_gated(wf: BpmnWorkflow, did_complete_task=None, did_complete_adhoc_task=None):
	"""
	do_engine_steps() with the ad-hoc one-task-at-a-time gate.

	Stock do_engine_steps() sweeps ALL ready engine tasks per pass, so two
	ad-hoc heads readied together would both run before processa could
	intervene. This variant runs ONE ready engine task per iteration and
	re-applies the gate between runs, making it impossible for a second
	head to slip through. Subprocess-completion propagation (the parent
	task _update stock code does after each subprocess sweep) is preserved.

	Args:
	    wf:                       the running BpmnWorkflow
	    did_complete_task:        callback fired after every engine task run
	    did_complete_adhoc_task:  callback fired after an ad-hoc inner task
	                              completes (used to
	                              refresh the context doc between inline
	                              <bpmn:script> tasks)
	"""
	# Generous safety valve: strictly more iterations than any real diagram
	# has task runs; prevents an engine regression from looping forever.
	for _ in range(10000):
		gate_changed = False
		for sp in _adhoc_subworkflows(wf):
			gate_changed = _gate_adhoc_subworkflow(sp) or gate_changed

		task = wf.get_next_task(state=TaskState.READY, manual=False)
		if task is None:
			if gate_changed:
				continue
			break

		task.run()
		if did_complete_task is not None:
			did_complete_task(task)
		if (
			did_complete_adhoc_task is not None
			and isinstance(getattr(task.workflow, "spec", None), AdHocSubprocessSpec)
			and getattr(task.task_spec, "bpmn_id", None)
			and task.state & TaskState.COMPLETED
		):
			# Only for real BPMN inner tasks - engine-internal Start/EndJoin/End
			# tasks carry no bpmn_id and don't warrant a context-doc refresh.
			# And only on actual COMPLETION: a service task's run() leaves it
			# STARTED (its real work happens in the caller's dispatch loop,
			# which fires this hook itself after task.complete()) - firing
			# here refreshed the context doc BEFORE the task's write landed,
			# so doc-based completion conditions saw stale state.
			did_complete_adhoc_task(task)

		# Completion propagation (the reason stock do_engine_steps pokes
		# subprocess parents): when a subworkflow finishes, its parent task
		# only advances on the next _update. Poke ONLY completed subprocesses -
		# poking an in-flight one re-arms StandardLoopTask iterations and
		# spins the loop. A subprocess can only complete when a task INSIDE
		# it ran (its EndJoin), so main-flow task runs skip the sweep - keeps
		# the per-iteration cost O(1) for diagrams with many subprocesses
		# instead of O(subprocesses) per engine step.
		if task.workflow is not wf:
			for sp in wf.subprocesses.values():
				if sp.completed and sp.parent_task_id is not None:
					parent = wf.get_task_from_id(sp.parent_task_id)
					if parent is not None and parent.state & TaskState.NOT_FINISHED_MASK:
						parent.task_spec._update(parent)

	wf.refresh_timers()


def adhoc_pending_head_tasks(wf: BpmnWorkflow) -> list:
	"""Parked (gate-suppressed) ad-hoc heads across the whole instance."""
	pending = []
	for sp in _adhoc_subworkflows(wf):
		pending.extend(t for t in adhoc_head_tasks(sp) if t.state == TaskState.FUTURE)
	return pending


# ─────────────────────────────────────────────────────────────
# Ad-hoc subprocess "decide" hook
#
# The ad-hoc dispatch loop promotes the next inner task in
# diagram-XML order by default. When an AI Task Selector is configured,
# bpmn_process_instance installs a decider here for the duration of one
# run_engine() call, and the gate's promotion step routes its choice
# through select_next_adhoc_task() - the same loop, a different decision
# function.
# ─────────────────────────────────────────────────────────────

# Sentinel a decider returns when it made a decision but nothing should be
# activated (registry-only actions, invalid tool name, executor failure).
NO_ACTIVATION = object()

# callable(subworkflow, pending_tasks) -> Task | NO_ACTIVATION | None.
# None means "no selector here" and falls through to diagram order.
adhoc_next_task_decider = None


def select_next_adhoc_task(sp, pending):
	"""
	Choose which pending ad-hoc head to promote next.

	Returns a task from ``pending`` or None (promote nothing this round -
	fail-safe: the completion condition governs and the loop resumes on the
	next advance() call).
	"""
	if not pending:
		return None
	if adhoc_next_task_decider is not None:
		try:
			chosen = adhoc_next_task_decider(sp, pending)
		except Exception:
			try:
				import frappe

				frappe.log_error(
					title="AI Task Selector decider failed",
					message=frappe.get_traceback(),
				)
			except Exception:
				pass
			chosen = NO_ACTIVATION  # fail-safe: never fall back to silent auto-run
		if chosen is NO_ACTIVATION:
			return None
		if chosen is not None:
			return chosen
	return pending[0]


# ─────────────────────────────────────────────────────────────
# Ad-hoc activation audit hook
#
# The ad-hoc dispatch loop activates inner tasks one at a
# time. bpmn_process_instance installs a logger here for the duration of
# one run_engine() call so every activation lands in BPMN Activity Log
# ("Ad-Hoc Task Activated") regardless of whether the decision came from
# diagram order or the AI Task Selector.
# ─────────────────────────────────────────────────────────────

# callable(subworkflow, task) - must never raise into the engine.
adhoc_task_activated_logger = None


def notify_adhoc_activation(sp, task) -> None:
	if adhoc_task_activated_logger is None:
		return
	try:
		adhoc_task_activated_logger(sp, task)
	except Exception:
		try:
			import frappe

			frappe.log_error(
				title="BPMN: ad-hoc activation logger failed",
				message=frappe.get_traceback(),
			)
		except Exception:
			pass
