# Copyright (c) 2026, one-fm and contributors
"""Workflow serializer and the create, restore and serialize round trip."""

import copy

from SpiffWorkflow.bpmn.serializer.default import AdHocSubprocessSpecConverter
from SpiffWorkflow.bpmn.serializer.workflow import BpmnWorkflowSerializer
from SpiffWorkflow.bpmn.specs.bpmn_process_spec import AdHocSubprocessSpec
from SpiffWorkflow.bpmn.specs.defaults import ServiceTask
from SpiffWorkflow.bpmn.workflow import BpmnWorkflow
from SpiffWorkflow.dmn.serializer.task_spec import BaseBusinessRuleTaskConverter
from SpiffWorkflow.spiff.specs.defaults import BusinessRuleTask as SpiffBusinessRuleTask

from one_bpmn.processa_engine.engine.script_engine import _make_script_engine


class _AdHocSubprocessSpecConverter(AdHocSubprocessSpecConverter):
	"""
	Upstream to_dict() hardcodes parallel/cancel_remaining to True
	(SpiffWorkflow 3.1.x, serializer/default/process_spec.py:95-96), so the
	parsed cancelRemainingInstances value is lost on every serialize.
	Read the actual spec values instead; from_dict() already restores them.
	"""

	def to_dict(self, spec):
		dct = super().to_dict(spec)
		dct["parallel"] = spec.parallel
		dct["cancel_remaining"] = spec.cancel_remaining
		return dct

# ─────────────────────────────────────────────────────────────
# Singleton serializer - stateless, safe to share across calls
# ─────────────────────────────────────────────────────────────
_serializer = None


def get_serializer() -> BpmnWorkflowSerializer:
	global _serializer
	if _serializer is None:
		from SpiffWorkflow.bpmn.serializer.config import DEFAULT_CONFIG
		from SpiffWorkflow.bpmn.serializer.default.task_spec import BpmnTaskSpecConverter

		# SpiffWorkflow 3.1.2 omits ServiceTask from DEFAULT_CONFIG - patch it in.
		# ServiceTask has the same structure as UserTask/ManualTask so the generic
		# BpmnTaskSpecConverter handles it correctly.
		patched_config = dict(DEFAULT_CONFIG)
		patched_config[ServiceTask] = BpmnTaskSpecConverter

		# Register BusinessRuleTask ↔ BaseBusinessRuleTaskConverter so the
		# serializer can persist/restore DMN decision table data embedded in
		# the spec by the BpmnDmnParser.
		patched_config[SpiffBusinessRuleTask] = BaseBusinessRuleTaskConverter

		# Ad-hoc subprocesses: upstream converter discards the parsed
		# parallel/cancel_remaining values (see _AdHocSubprocessSpecConverter).
		patched_config[AdHocSubprocessSpec] = _AdHocSubprocessSpecConverter

		registry = BpmnWorkflowSerializer.configure(config=patched_config)
		_serializer = BpmnWorkflowSerializer(registry=registry)
	return _serializer


# ─────────────────────────────────────────────────────────────
# Create  (called when a new Process Instance starts)
# ─────────────────────────────────────────────────────────────


def create_workflow(
	serialized_spec: dict,
	subprocess_specs: dict,
	initial_data: dict = None,
	context_doctype: str = None,
	context_docname: str = None,
	script_task_extensions: dict = None,
	initiated_by: str = None,
	instance=None,
) -> BpmnWorkflow:
	"""
	Create a brand-new BpmnWorkflow from a stored serialised spec.

	No XML parsing happens here - the spec was already parsed and stored
	when the diagram was saved.

	serialized_spec now stores a full workflow dict (from parse_bpmn which
	wraps the spec in a BpmnWorkflow before serialising so that all task
	types are properly JSON-serialised).  subprocess_specs is kept for
	backward-compat but is no longer used - subprocesses are embedded in
	the serialized_spec workflow dict.

	Args:
	    serialized_spec:   dict from BPMN Process Model.serialized_spec
	    subprocess_specs:  unused (kept for API backward-compat)
	    initial_data:      optional data to inject at the root task level
	    context_doctype:   linked Frappe DocType (e.g. 'Work Item')
	    context_docname:   linked Frappe document name

	Returns:
	    A live, ready-to-run BpmnWorkflow instance
	"""
	serializer = get_serializer()
	# serialized_spec is a plain Python dict (loaded from the JSON field).
	# In SpiffWorkflow 3.x, from_dict() alone is not enough - we need to go
	# through deserialize_json() which uses the custom json_decoder_cls to
	# restore SpiffWorkflow-specific types (enums, UUIDs, task state, etc.).
	import json as _json

	json_str = _json.dumps(serialized_spec)  # re-encode the clean dict to string
	wf = serializer.deserialize_json(json_str)  # proper type-aware decoding

	# Re-attach the script engine (never serialised)
	wf.script_engine = _make_script_engine(
		context_doctype=context_doctype,
		context_docname=context_docname,
		script_task_extensions=script_task_extensions,
		initiated_by=initiated_by,
		instance=instance,
	)

	if initial_data:
		wf.task_tree.data.update(initial_data)

	return wf


# ─────────────────────────────────────────────────────────────
# Restore  (called on every subsequent API call)
# ─────────────────────────────────────────────────────────────


def restore_workflow(
	workflow_state: dict,
	context_doctype: str = None,
	context_docname: str = None,
	script_task_extensions: dict = None,
	initiated_by: str = None,
	instance=None,
) -> BpmnWorkflow:
	"""
	Restore a mid-flight workflow from its serialised state (stored in DB).

	The script engine is NOT stored in the serialisation, so we
	re-attach it here with fresh Frappe context.

	Args:
	    workflow_state:  dict from BPMN Process Instance.workflow_state
	    context_doctype: linked Frappe DocType
	    context_docname: linked Frappe document name

	Returns:
	    A restored BpmnWorkflow ready to continue execution
	"""
	serializer = get_serializer()
	# from_dict() consumes the dict destructively (pops keys, replaces nested
	# values with live objects) - restore from a copy so the caller's dict
	# stays JSON-safe and reusable.
	wf = serializer.from_dict(copy.deepcopy(workflow_state))

	# Re-attach script engine (not serialised)
	wf.script_engine = _make_script_engine(
		context_doctype=context_doctype,
		context_docname=context_docname,
		script_task_extensions=script_task_extensions,
		initiated_by=initiated_by,
		instance=instance,
	)

	return wf


# ─────────────────────────────────────────────────────────────
# Serialize  (called after every state change)
# ─────────────────────────────────────────────────────────────


def serialize_workflow(wf: BpmnWorkflow) -> dict:
	"""
	Serialise a running workflow to a JSON-safe dict for DB storage.

	Uses serialize_json() + json.loads() rather than to_dict(): in
	SpiffWorkflow 3.x to_dict() returns an intermediate representation that
	can still contain raw Python objects (observed with ad-hoc subprocess
	states holding conditionally re-added loop/multi-instance instances),
	while serialize_json()'s custom encoder converts every registered type.
	Same pattern parse_bpmn() already uses for the compiled spec.

	Args:
	    wf: the running BpmnWorkflow

	Returns:
	    dict suitable for json.dumps() and storage in workflow_state field
	"""
	import json as _json

	return _json.loads(get_serializer().serialize_json(wf))
