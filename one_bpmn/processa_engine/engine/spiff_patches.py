# Copyright (c) 2026, one-fm and contributors
"""SpiffWorkflow class-level patches, applied when the engine package is imported."""

from SpiffWorkflow.bpmn.specs.bpmn_process_spec import AdHocSubprocessSpec
from SpiffWorkflow.bpmn.specs.mixins.events.intermediate_event import (
	EventBasedGateway as _EventBasedGateway,
)
from SpiffWorkflow.util.task import TaskState

# ── Ad-hoc Subprocess support ────────────────────────────────
# Upstream path_complete() fires after EVERY inner task completion and
# evaluates the completion condition with a raw eval. A condition that
# references a variable no task has set yet (e.g. `done` before the
# wrap-up script task runs `done = True`) raises NameError, which fails
# the user's task completion. Camunda treats an unresolvable condition
# as not met - mirror that: pre-evaluate against the merged data view
# (path_complete merges task.data into workflow.data before evaluating)
# and hand upstream a literal. Class-level patch so previously
# serialized instances are covered too. Only NameError is absorbed;
# genuine expression errors still surface.
_upstream_path_complete = AdHocSubprocessSpec.path_complete


def _safe_path_complete(self, workflow, task):
	original = self.completion_condition
	if original:
		try:
			met = bool(
				workflow.script_engine.environment.evaluate(
					original, {**workflow.data, **task.data}
				)
			)
		except NameError:
			met = False
		self.completion_condition = "True" if met else "False"
	try:
		return _upstream_path_complete(self, workflow, task)
	finally:
		self.completion_condition = original


AdHocSubprocessSpec.path_complete = _safe_path_complete


# ── Event-based gateway prediction fix ───────────────────────
# SpiffWorkflow 3.1.x EventBasedGateway._predict_hook unconditionally forces
# its child tasks into WAITING state:
#     my_task._sync_children(self.outputs, state=TaskState.WAITING)
# During the whole-tree prediction pass (BpmnWorkflow.__init__), a gateway that
# sits inside a LOOP is re-reached via look-ahead as a *predicted* task. Adding a
# WAITING (non-predicted) child to a predicted parent violates the invariant in
# Task._add_child and raises "Attempt to add non-predicted child to predicted
# task" - so any model with an event-based gateway in a loop (e.g. the ProsAlly /
# Logix conversation loops) fails to (re)compile. Mirror the base
# TaskSpec._predict_hook: only force WAITING once the gateway is DEFINITE
# (actually entered); during predicted look-ahead, copy the predicted state.
# Class-level patch so previously serialized instances are covered too.


def _safe_eventgateway_predict_hook(self, my_task):
	if my_task.has_state(TaskState.DEFINITE_MASK):
		my_task._sync_children(self.outputs, state=TaskState.WAITING)
	else:
		my_task._sync_children(self.outputs, my_task.state)


_EventBasedGateway._predict_hook = _safe_eventgateway_predict_hook
