# Copyright (c) 2026, one-fm and contributors
"""Task labels, context document sync and message delivery for a running workflow."""

import decimal
from datetime import date, datetime, time

import frappe

from SpiffWorkflow.bpmn.specs.defaults import (
	ExclusiveGateway,
	InclusiveGateway,
	ManualTask,
	ParallelGateway,
	ReceiveTask,
	ScriptTask,
	SendTask,
	ServiceTask,
	UserTask,
)
from SpiffWorkflow.bpmn.workflow import BpmnWorkflow
from SpiffWorkflow.spiff.specs.defaults import BusinessRuleTask as SpiffBusinessRuleTask
from SpiffWorkflow.util.task import TaskState


def json_safe_doc_fields(doc) -> dict:
	"""A document's fields in the form a BPMN condition can test.

	Task data is serialised, so only JSON-safe values may go in. The naive
	reading of that rule - keep ``str``/``int``/``float``/``bool`` and drop the
	rest - silently drops every Date, Datetime, Time and Currency field, and a
	gateway testing one of those then raises ``NameError`` and is read as False.
	Those are converted rather than dropped. Child tables and other
	non-primitives are still skipped: a condition cannot usefully test them.

	This is the single definition used by the instance snapshot, the mid-run
	refresh and the trigger's start-condition eval, so the three cannot drift.
	"""
	out = {}
	for f in doc.meta.fields:
		val = doc.get(f.fieldname)
		if isinstance(val, (str, int, float, bool)) or val is None:
			out[f.fieldname] = val
		elif isinstance(val, (datetime, date, time)):
			out[f.fieldname] = val.isoformat()
		elif isinstance(val, decimal.Decimal):
			out[f.fieldname] = float(val)
	out["docstatus"] = int(getattr(doc, "docstatus", 0) or 0)
	return out


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def get_task_display_name(task) -> str:
	"""
	Return the human-readable name for a task.

	SpiffWorkflow stores the BPMN 'name' attribute in task_spec.description.
	Falls back to task_spec.name (which is the BPMN id, e.g. 'Activity_0abc').
	"""
	return (
		getattr(task.task_spec, "bpmn_name", None)
		or getattr(task.task_spec, "description", None)
		or task.task_spec.name
	)


TASK_TYPE_LABELS = (
	(UserTask, "User Task"),
	(ScriptTask, "Script Task"),
	(ServiceTask, "Service Task"),
	(ManualTask, "Manual Task"),
	(SendTask, "Send Task"),
	(ReceiveTask, "Receive Task"),
	(SpiffBusinessRuleTask, "Business Rule Task"),
	(ExclusiveGateway, "Exclusive Gateway"),
	(ParallelGateway, "Parallel Gateway"),
	(InclusiveGateway, "Inclusive Gateway"),
)


def get_task_type_label(task) -> str:
	"""Return a display-friendly task type string for the active_tasks table."""
	spec = task.task_spec
	for spec_class, label in TASK_TYPE_LABELS:
		if isinstance(spec, spec_class):
			return label
	return type(spec).__name__


def get_ready_user_tasks(wf: BpmnWorkflow) -> list:
	"""Return all READY tasks that require human input."""
	return [t for t in wf.get_tasks(state=TaskState.READY) if t.task_spec.manual]


def refresh_context_doc(wf: BpmnWorkflow, context_doctype: str, context_docname: str):
	"""
	Reload the linked Frappe document and push its scalar field values into
	the workflow task data, and the doc object itself into the script engine
	environment (NOT into task data - Frappe Documents are not JSON-serializable
	and would crash SpiffWorkflow's serialize_workflow step).

	This ensures conditional expressions like ``docstatus == 0`` always see
	the latest field values from the database.
	"""
	try:
		import frappe

		doc = frappe.get_doc(context_doctype, context_docname)

		# ── Inject the document's fields into task data ────────────────────
		# task_tree.data is serialized by SpiffWorkflow, so the values have to be
		# JSON-safe; json_safe_doc_fields is what decides that.
		safe = json_safe_doc_fields(doc)
		safe["context_doctype"] = context_doctype
		safe["context_docname"] = context_docname
		# Remove stale 'doc' key if it was accidentally stored previously
		wf.task_tree.data.pop("doc", None)
		wf.task_tree.data.update(safe)

		# Subprocess scopes carry their own snapshot of these fields (task
		# data drains into sp.data on completion) - _adhoc_completion_met
		# evaluates against sp.data, where a stale bare-scalar (e.g. `status`)
		# would shadow anything refreshed above.
		for sp in (getattr(wf, "subprocesses", None) or {}).values():
			if isinstance(sp.data, dict):
				sp.data.pop("doc", None)
				sp.data.update({k: v for k, v in safe.items() if k in sp.data})

		# ── Inject the full doc object ONLY into the script engine env ──────
		# The script engine environment is never serialized, so Frappe
		# Document objects are safe here. TaskDataEnvironment keeps its
		# variables in `.globals` - writing anywhere else is a silent no-op
		# and leaves every `doc.<field>` condition reading the object loaded
		# at engine construction (the cause of ad-hoc subprocesses never
		# completing within the request that resolved their document).
		env = getattr(wf.script_engine, "environment", None)
		if env is not None:
			if hasattr(env, "globals") and isinstance(env.globals, dict):
				env.globals["doc"] = doc
			elif hasattr(env, "environment") and isinstance(env.environment, dict):
				env.environment["doc"] = doc
	except Exception:
		pass


def clean_doc_from_wf_data(wf: BpmnWorkflow) -> None:
	"""
	Remove any non-JSON-serializable 'doc' key from all task data dicts
	before calling serialize_workflow().  Acts as a safety net in case any
	code path accidentally stored a Frappe Document in task data.
	"""
	if wf.task_tree:
		wf.task_tree.data.pop("doc", None)
	for task in wf.get_tasks():
		if hasattr(task, "data") and isinstance(task.data, dict):
			task.data.pop("doc", None)


# Messages that wait for their catch event when they arrive early. Other messages (a chat turn) are
# dropped as before, because those processes queue their own turns.
BUFFERED_MESSAGE_PREFIXES = ("github:",)


def declares_message(wf: BpmnWorkflow, message_name: str) -> bool:
	"""Whether any catch event or receive task in the process, or its sub-processes, waits for this message."""
	from SpiffWorkflow.bpmn.specs.event_definitions import MessageEventDefinition

	for spec in [wf.spec, *wf.subprocess_specs.values()]:
		for task_spec in spec.task_specs.values():
			event = getattr(task_spec, "event_definition", None)
			for definition in getattr(event, "event_definitions", None) or [event]:
				if isinstance(definition, MessageEventDefinition) and definition.name == message_name:
					return True
	return False


def send_message(wf: BpmnWorkflow, message_name: str, payload: dict = None) -> bool:
	"""
	Deliver an external message to a running workflow instance.

	Uses SpiffWorkflow's native send_event() which:
	  1. Finds WAITING tasks that catch this message name
	     (IntermediateCatchEvent, ReceiveTask, or EventBasedGateway children)
	  2. Checks message correlation if correlation properties are defined
	  3. Delivers the payload into the matching task's data
	  4. Calls refresh_waiting_tasks() to advance the flow

	Args:
	    wf:           The running BpmnWorkflow
	    message_name: BPMN message name - must match <bpmn:message name="...">
	    payload:      Optional dict of data to deliver with the message.
	                  Merged into task.data via set_data(**payload), so
	                  each key becomes a task variable usable in gateway
	                  conditions and downstream expressions.

	Returns:
	    True  - message was caught by a waiting task
	    False - no task is waiting for this message
	"""
	from SpiffWorkflow.bpmn.specs.event_definitions import MessageEventDefinition
	from SpiffWorkflow.bpmn.specs.mixins.events.event_types import CatchingEvent
	from SpiffWorkflow.bpmn.util.event import BpmnEvent
	from SpiffWorkflow.exceptions import WorkflowException

	msg_def = MessageEventDefinition(message_name)
	event = BpmnEvent(msg_def, payload=payload or {})

	try:
		wf.send_event(event)
	except WorkflowException:
		# No task is currently waiting for this message
		return False
	except Exception:
		frappe.log_error(
			title="BPMN send_message error",
			message=frappe.get_traceback(),
		)
		raise

	# ── Catch-event successor repair (SpiffWorkflow 3.1.3a) ──────────────────
	# This SpiffWorkflow build PRUNES a fired catch event's successor when the
	# event is delivered, and never rebuilds it: prediction stops at WAITING catch
	# events, and _on_complete only *updates* existing children (it never creates
	# them). Net effect - an event-based-gateway wait (e.g. the ProsAlly / Logix
	# "Waiting for User Message" loop) dead-ends right after "Message Received" and
	# the instance completes with no reply. Re-materialize each fired catch event's
	# successor(s) as LIKELY and re-predict, so the forward chain is rebuilt and the
	# engine loop can advance past the catch. Verified end-to-end: without this the
	# conversation loop produces no reply; with it, the turn runs and re-parks.
	repaired = False
	for _t in wf.get_tasks():
		if (
			isinstance(_t.task_spec, CatchingEvent)
			and _t.internal_data.get("event_fired")
			and _t.task_spec.outputs
			and not _t.children
		):
			_t._sync_children(_t.task_spec.outputs, TaskState.LIKELY)
			repaired = True
	if repaired:
		wf.task_tree.task_spec._predict(wf.task_tree, mask=TaskState.NOT_FINISHED_MASK)
	return True
