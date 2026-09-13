"""Take the timer off compiled start events so timer-started processes can run.

A Timer Start Event is scheduled by ``process_timer_start_events``: the sweep
matches the cycle written into ``<bpmn:timeCycle>`` and creates the instance.
The compiled spec, though, also carried that cycle as a SpiffWorkflow timer, and
SpiffWorkflow evaluates a cycle expression as Python — so a map scheduled with
``*/5 * * * *`` errored on its first step, every time, and the sweep started
nothing. Compilation no longer hands the timer to the parser; already-deployed
maps still hold it in ``serialized_spec``, and are repaired here rather than
recompiled, which would re-run every deploy-time gate and re-announce the deploy.

Idempotent: only start events whose event definition is still a timer are
touched, so a second run finds nothing to do.
"""

import json

import frappe

TIMER_EVENT_DEFINITIONS = {
	"CycleTimerEventDefinition",
	"DurationTimerEventDefinition",
	"TimeDateEventDefinition",
}

NONE_EVENT_DEFINITION = {"description": "Default", "name": None, "typename": "NoneEventDefinition"}


def _detach(spec: dict) -> bool:
	task_specs = ((spec.get("spec") or {}).get("task_specs")) or {}
	detached = False
	for task in task_specs.values():
		if task.get("typename") != "StartEvent":
			continue
		if (task.get("event_definition") or {}).get("typename") in TIMER_EVENT_DEFINITIONS:
			task["event_definition"] = dict(NONE_EVENT_DEFINITION)
			detached = True
	return detached


def execute():
	models = frappe.get_all(
		"BPMN Process Model",
		filters={"serialized_spec": ["like", "%TimerEventDefinition%"]},
		fields=["name", "serialized_spec"],
	)

	for model in models:
		try:
			spec = json.loads(model.serialized_spec)
		except Exception:
			continue

		if not _detach(spec):
			continue

		frappe.db.set_value(
			"BPMN Process Model", model.name, "serialized_spec", json.dumps(spec), update_modified=False
		)

	frappe.db.commit()
