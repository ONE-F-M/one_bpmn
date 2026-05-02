# Copyright (c) 2026, one-fm and contributors
# SpiffWorkflow backend engine for one_bpmn
#
# This module is the ONLY place that imports SpiffWorkflow.
# Everything else in one_bpmn talks to this module.

import io
from datetime import datetime

from SpiffWorkflow.bpmn.parser.BpmnParser import BpmnParser
from SpiffWorkflow.bpmn.parser.ValidationException import ValidationException
from SpiffWorkflow.bpmn.serializer.workflow import BpmnWorkflowSerializer
from SpiffWorkflow.bpmn.script_engine import TaskDataEnvironment, PythonScriptEngine
from SpiffWorkflow.bpmn.workflow import BpmnWorkflow
from SpiffWorkflow.util.task import TaskState
from SpiffWorkflow.bpmn.specs.defaults import (
	UserTask,
	ScriptTask,
	ServiceTask,
	ManualTask,
	SendTask,
	ReceiveTask,
	ExclusiveGateway,
	ParallelGateway,
	InclusiveGateway,
	EventBasedGateway,
)

# ─────────────────────────────────────────────────────────────
# Singleton serializer — stateless, safe to share across calls
# ─────────────────────────────────────────────────────────────
_serializer = None


def get_serializer() -> BpmnWorkflowSerializer:
	global _serializer
	if _serializer is None:
		from SpiffWorkflow.bpmn.serializer.config import DEFAULT_CONFIG
		from SpiffWorkflow.bpmn.serializer.default.task_spec import BpmnTaskSpecConverter

		# SpiffWorkflow 3.1.2 omits ServiceTask from DEFAULT_CONFIG — patch it in.
		# ServiceTask has the same structure as UserTask/ManualTask so the generic
		# BpmnTaskSpecConverter handles it correctly.
		patched_config = dict(DEFAULT_CONFIG)
		patched_config[ServiceTask] = BpmnTaskSpecConverter

		registry = BpmnWorkflowSerializer.configure(config=patched_config)
		_serializer = BpmnWorkflowSerializer(registry=registry)
	return _serializer


# ─────────────────────────────────────────────────────────────
# FrappeScriptEngine — custom ScriptEngine with Server Script support
# ─────────────────────────────────────────────────────────────


class FrappeScriptEngine(PythonScriptEngine):
	"""
	A PythonScriptEngine that intercepts Script Task execution.

	If the task has a ``serverScript`` attribute registered in
	``script_task_extensions`` (embedded at compile time), the engine
	calls that Frappe Server Script instead of running the inline
	``<bpmn:script>`` content.

	The script receives these local variables:
	    frappe             — the Frappe module
	    doc                — the context document (if any)
	    context_doctype    — linked DocType string
	    context_docname    — linked document name string
	    result             — pre-set to {} — set values on this to pass
	                         data back into the workflow (gateway routing)
	    <all task.data>    — current workflow variables

	Gateway conditions can then check: result["action"] == "Approve"
	(but only if the script sets it on ``result``).

	Example Server Script body::

	    doc = frappe.get_doc(context_doctype, context_docname)
	    if doc.total_leave_days > 10:
	        result["action"] = "Escalate"
	    else:
	        result["action"] = "Approve"
	"""

	def __init__(self, environment, script_task_extensions=None, context_doctype=None, context_docname=None):
		super().__init__(environment)
		self._script_task_extensions = script_task_extensions or {}
		self._context_doctype = context_doctype
		self._context_docname = context_docname

	def execute(self, task, script, **kwargs):
		"""
		Override: run a Frappe Server Script for this task if one is
		configured; otherwise fall back to inline PythonScriptEngine execution.
		"""
		bpmn_id = getattr(task.task_spec, "bpmn_id", None) or ""
		task_cfg = self._script_task_extensions.get(bpmn_id, {})
		server_script_name = task_cfg.get("serverScript", "")

		if server_script_name:
			self._run_frappe_server_script(server_script_name, task)
		else:
			# No server script configured — run inline <bpmn:script> normally
			super().execute(task, script, **kwargs)

	def _run_frappe_server_script(self, script_name: str, task) -> None:
		"""
		Execute a Frappe Server Script (API type) with workflow context.

		The script's ``result`` dict is merged into ``task.data`` after
		execution, making the values available to downstream gateways
		via conditions like: action == "Approve"
		"""
		try:
			import frappe as _frappe
		except ImportError:
			return

		script_doc = _frappe.get_doc("Server Script", script_name)
		if not script_doc or script_doc.disabled:
			_frappe.log_error(
				title=f'BPMN ScriptTask: Server Script "{script_name}" not found or disabled',
				message=(
					f'Task bpmn_id "{getattr(task.task_spec, "bpmn_id", "?")} " '
					f'tried to run Server Script "{script_name}" but it is '
					f"{'disabled' if script_doc else 'missing'}."
				),
			)
			return

		# Build locals: workflow variables + framework context
		local_vars = dict(task.data)
		result_dict = {}
		local_vars.update(
			{
				"frappe": _frappe,
				"context_doctype": self._context_doctype or "",
				"context_docname": self._context_docname or "",
				"result": result_dict,
			}
		)
		if self._context_doctype and self._context_docname:
			try:
				local_vars["doc"] = _frappe.get_doc(self._context_doctype, self._context_docname)
			except Exception:
				local_vars["doc"] = _frappe._dict()
		else:
			local_vars["doc"] = _frappe._dict()

		try:
			# Use plain exec() rather than frappe.safe_exec().
			# frappe.safe_exec() is a security gate for *untrusted* browser-submitted
			# scripts — it requires server_script_enabled in common_site_config and
			# runs code in a RestrictedPython sandbox with a limited frappe namespace.
			# BPMN Server Scripts are trusted, pre-deployed code stored in the DB,
			# so they run with the real frappe module and no config gate.
			exec_globals = {"frappe": _frappe, "__builtins__": __builtins__}  # noqa: S102
			exec(script_doc.script, exec_globals, local_vars)  # noqa: S102
		except Exception:
			_frappe.log_error(
				title=f'BPMN ScriptTask: "{script_name}" execution failed',
				message=_frappe.get_traceback(),
			)
			raise

		# Merge result back into task data for downstream gateway routing
		if isinstance(result_dict, dict) and result_dict:
			task.data.update(result_dict)


def _make_script_engine(
	context_doctype=None,
	context_docname=None,
	script_task_extensions=None,
) -> FrappeScriptEngine:
	"""
	Build a FrappeScriptEngine with Frappe, datetime, and doc injected.

	Script Tasks without a configured Server Script can still call:
	    frappe.db.set_value(...)
	    frappe.get_doc(...)
	    doc.workflow_state   ← the live context document
	    datetime.now()

	Script Tasks WITH a configured Server Script will have that script
	executed by FrappeScriptEngine._run_frappe_server_script() instead.
	"""
	try:
		import frappe as _frappe
	except ImportError:
		_frappe = None

	extra = {
		"datetime": datetime,
		"frappe": _frappe,
	}

	if _frappe and context_doctype and context_docname:
		try:
			doc = _frappe.get_doc(context_doctype, context_docname)
			extra["doc"] = doc
		except Exception:
			extra["doc"] = _frappe._dict()
	elif _frappe:
		extra["doc"] = _frappe._dict()

	env = TaskDataEnvironment(extra)
	return FrappeScriptEngine(
		env,
		script_task_extensions=script_task_extensions,
		context_doctype=context_doctype,
		context_docname=context_docname,
	)


# ─────────────────────────────────────────────────────────────
# Parse  (called once at diagram-save time)
# ─────────────────────────────────────────────────────────────


def parse_bpmn(bpmn_xml: str, process_id: str, dmn_xml: str = None) -> tuple:
	"""
	Parse a BPMN XML string into serialised spec dicts.

	Called ONCE when a diagram is saved/imported — never at runtime.
	Returns two plain dicts that are JSON-safe and ready to store in
	BPMN Process Model.serialized_spec / subprocess_specs.

	Args:
	    bpmn_xml:   Raw BPMN 2.0 XML string (may contain <?xml …?> declaration)
	    process_id: The <bpmn:process id="…"> value to use as the entry point
	    dmn_xml:    Optional DMN XML string (reserved for future use)

	Returns:
	    (spec_dict, sp_specs_dict)

	Raises:
	    ValidationException: if the BPMN XML is invalid
	    frappe.ValidationError: if process_id not found
	"""
	parser = BpmnParser()

	# lxml cannot parse a *string* that contains an encoding declaration,
	# but it can parse *bytes*.  Using add_bpmn_io(BytesIO) is the safe path.
	bpmn_bytes = bpmn_xml.strip().encode("utf-8")
	parser.add_bpmn_io(io.BytesIO(bpmn_bytes), filename="diagram.bpmn")

	if dmn_xml and dmn_xml.strip():
		# DMN support hook — extend here when needed
		pass

	try:
		spec = parser.get_spec(process_id)
		sp_specs = parser.get_subprocess_specs(process_id)
	except ValidationException as exc:
		# Reset parser state so it can be reused without contamination
		parser.process_parsers = {}
		raise exc

	# BpmnWorkflowSerializer.to_dict() in SpiffWorkflow 3.x returns an
	# intermediate representation that still contains raw Python objects
	# (e.g. ServiceTask, UserTask) — json.dumps() fails on those.
	#
	# The correct pattern for 3.x is:
	#   serialize_json()  — uses the serializer's custom json_encoder_cls
	#                       to produce a fully encoded JSON *string*
	#   json.loads()      — converts that string back to a plain Python dict
	#                       so it can be stored safely with json.dumps() later
	import json as _json

	serializer = get_serializer()
	wf = BpmnWorkflow(spec, sp_specs)
	wf_dict = _json.loads(serializer.serialize_json(wf))  # clean, JSON-safe dict

	return wf_dict, {}


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
) -> BpmnWorkflow:
	"""
	Create a brand-new BpmnWorkflow from a stored serialised spec.

	No XML parsing happens here — the spec was already parsed and stored
	when the diagram was saved.

	serialized_spec now stores a full workflow dict (from parse_bpmn which
	wraps the spec in a BpmnWorkflow before serialising so that all task
	types are properly JSON-serialised).  subprocess_specs is kept for
	backward-compat but is no longer used — subprocesses are embedded in
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
	# In SpiffWorkflow 3.x, from_dict() alone is not enough — we need to go
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
	wf = serializer.from_dict(workflow_state)

	# Re-attach script engine (not serialised)
	wf.script_engine = _make_script_engine(
		context_doctype=context_doctype,
		context_docname=context_docname,
		script_task_extensions=script_task_extensions,
	)

	return wf


# ─────────────────────────────────────────────────────────────
# Serialize  (called after every state change)
# ─────────────────────────────────────────────────────────────


def serialize_workflow(wf: BpmnWorkflow) -> dict:
	"""
	Serialise a running workflow to a JSON-safe dict for DB storage.

	Args:
	    wf: the running BpmnWorkflow

	Returns:
	    dict suitable for json.dumps() and storage in workflow_state field
	"""
	return get_serializer().to_dict(wf)


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


def get_task_type_label(task) -> str:
	"""Return a display-friendly task type string for the active_tasks table."""
	spec = task.task_spec
	if isinstance(spec, UserTask):
		return "User Task"
	if isinstance(spec, ScriptTask):
		return "Script Task"
	if isinstance(spec, ServiceTask):
		return "Service Task"
	if isinstance(spec, ManualTask):
		return "Manual Task"
	if isinstance(spec, SendTask):
		return "Send Task"
	if isinstance(spec, ExclusiveGateway):
		return "Exclusive Gateway"
	if isinstance(spec, ParallelGateway):
		return "Parallel Gateway"
	if isinstance(spec, InclusiveGateway):
		return "Inclusive Gateway"
	return type(spec).__name__


def get_ready_user_tasks(wf: BpmnWorkflow) -> list:
	"""Return all READY tasks that require human input."""
	return [t for t in wf.get_tasks(state=TaskState.READY) if t.task_spec.manual]


def refresh_context_doc(wf: BpmnWorkflow, context_doctype: str, context_docname: str):
	"""
	Reload the linked Frappe document and push its scalar field values into
	the workflow task data, and the doc object itself into the script engine
	environment (NOT into task data — Frappe Documents are not JSON-serializable
	and would crash SpiffWorkflow's serialize_workflow step).

	This ensures conditional expressions like ``docstatus == 0`` always see
	the latest field values from the database.
	"""
	try:
		import frappe

		doc = frappe.get_doc(context_doctype, context_docname)

		# ── Inject JSON-safe scalar fields only into task data ─────────────
		# task_tree.data is serialized by SpiffWorkflow — only primitives allowed.
		safe = {
			f.fieldname: doc.get(f.fieldname)
			for f in doc.meta.fields
			if isinstance(doc.get(f.fieldname), (str, int, float, bool, type(None)))
		}
		safe["docstatus"] = int(doc.docstatus or 0)
		safe["context_doctype"] = context_doctype
		safe["context_docname"] = context_docname
		# Remove stale 'doc' key if it was accidentally stored previously
		wf.task_tree.data.pop("doc", None)
		wf.task_tree.data.update(safe)

		# ── Inject the full doc object ONLY into the script engine env ──────
		# The script engine environment is never serialized, so Frappe
		# Document objects are safe here.
		env = getattr(wf.script_engine, "environment", None)
		if env and hasattr(env, "environment"):
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
	    message_name: BPMN message name — must match <bpmn:message name="...">
	    payload:      Optional dict of data to deliver with the message.
	                  Merged into task.data via set_data(**payload), so
	                  each key becomes a task variable usable in gateway
	                  conditions and downstream expressions.

	Returns:
	    True  — message was caught by a waiting task
	    False — no task is waiting for this message
	"""
	from SpiffWorkflow.bpmn.specs.event_definitions import MessageEventDefinition
	from SpiffWorkflow.bpmn.util.event import BpmnEvent
	from SpiffWorkflow.exceptions import WorkflowException

	msg_def = MessageEventDefinition(message_name)
	event = BpmnEvent(msg_def, payload=payload or {})

	try:
		wf.send_event(event)
		return True
	except WorkflowException:
		# No task is currently waiting for this message
		return False
	except Exception:
		frappe.log_error(
			title="BPMN send_message error",
			message=frappe.get_traceback(),
		)
		raise
