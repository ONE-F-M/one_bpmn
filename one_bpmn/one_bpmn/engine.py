# Copyright (c) 2026, one-fm and contributors
# SpiffWorkflow backend engine for one_bpmn
#
# This module is the ONLY place that imports SpiffWorkflow.
# Everything else in one_bpmn talks to this module.

import copy
import io
from datetime import datetime

from SpiffWorkflow.dmn.parser import BpmnDmnParser
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
from SpiffWorkflow.bpmn.specs.bpmn_process_spec import AdHocSubprocessSpec
from SpiffWorkflow.bpmn.specs.control import BpmnStartTask, SimpleBpmnTask, _EndJoin
from SpiffWorkflow.bpmn.specs.mixins.multiinstance_task import LoopTask

# ── DMN (Business Rule Task) support ─────────────────────────
# bpmn-js-spiffworkflow writes <spiffworkflow:calledDecisionId> so we
# use the spiff parser variant (not camunda) for the businessRuleTask.
from SpiffWorkflow.spiff.parser.task_spec import (
	BusinessRuleTaskParser as SpiffBusinessRuleTaskParser,
)
from SpiffWorkflow.spiff.specs.defaults import (
	BusinessRuleTask as SpiffBusinessRuleTask,
)
from SpiffWorkflow.dmn.serializer.task_spec import (
	BaseBusinessRuleTaskConverter,
)

_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
_BRT_TAG = f"{{{_BPMN_NS}}}businessRuleTask"

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

		# Register BusinessRuleTask ↔ BaseBusinessRuleTaskConverter so the
		# serializer can persist/restore DMN decision table data embedded in
		# the spec by the BpmnDmnParser.
		patched_config[SpiffBusinessRuleTask] = BaseBusinessRuleTaskConverter

		registry = BpmnWorkflowSerializer.configure(config=patched_config)
		_serializer = BpmnWorkflowSerializer(registry=registry)
	return _serializer


# ─────────────────────────────────────────────────────────────
# Permission guard — patterns scripts must never contain
# ─────────────────────────────────────────────────────────────

_FORBIDDEN_SCRIPT_PATTERNS = (
	"frappe.set_user",
	"frappe.flags.ignore_permissions",
)


def _check_script_permissions(script_text: str, label: str) -> None:
	"""
	Reject scripts that attempt to bypass Frappe permission controls.

	Called before exec() for both Server Script tasks and inline <bpmn:script>
	tasks.  Raises frappe.ValidationError if a forbidden pattern is found.
	"""
	try:
		import frappe as _f
	except ImportError:
		return
	for pattern in _FORBIDDEN_SCRIPT_PATTERNS:
		if pattern in (script_text or ""):
			_f.throw(
				f'BPMN Script "{label}": scripts may not use `{pattern}`. '
				f"Tasks must run under the user's permission context."
			)


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

	def __init__(self, environment, script_task_extensions=None, context_doctype=None, context_docname=None, initiated_by=None):
		super().__init__(environment)
		self._script_task_extensions = script_task_extensions or {}
		self._context_doctype = context_doctype
		self._context_docname = context_docname
		self._initiated_by = initiated_by or "Administrator"

	def execute(self, task, script, **kwargs):
		"""
		Override: enforce user permission context for all script execution.

		Before running any script (Server Script or inline), this method:
		  1. Validates the script content for forbidden permission-bypass patterns
		  2. Switches frappe.session.user to self._initiated_by so the script
		     runs with that user's permission context (ignore_permissions=False)
		  3. Restores the original session user after execution

		For timer-triggered instances _initiated_by is "Administrator".
		For user-triggered instances it is the user who started the process.
		"""
		try:
			import frappe as _frappe
		except ImportError:
			super().execute(task, script, **kwargs)
			return

		bpmn_id = getattr(task.task_spec, "bpmn_id", None) or ""
		task_cfg = self._script_task_extensions.get(bpmn_id, {})
		server_script_name = task_cfg.get("serverScript", "")

		# Validate inline scripts before switching users (fail fast)
		if not server_script_name:
			_check_script_permissions(script, f"bpmn:{bpmn_id}")

		original_user = _frappe.session.user
		try:
			_frappe.set_user(self._initiated_by)
			_frappe.flags.ignore_permissions = False

			if server_script_name:
				self._run_frappe_server_script(server_script_name, task)
			else:
				super().execute(task, script, **kwargs)
		finally:
			_frappe.set_user(original_user)
			_frappe.flags.ignore_permissions = False

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

		# Reject scripts that attempt to bypass permission controls
		_check_script_permissions(script_doc.script, script_name)

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
	initiated_by=None,
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
		initiated_by=initiated_by,
	)


# ─────────────────────────────────────────────────────────────
# Parse  (called once at diagram-save time)
# ─────────────────────────────────────────────────────────────


def parse_bpmn(bpmn_xml: str, process_id: str, dmn_xml_list: list = None) -> tuple:
	"""
	Parse a BPMN XML string into serialised spec dicts.

	Called ONCE when a diagram is saved/imported — never at runtime.
	Returns two plain dicts that are JSON-safe and ready to store in
	BPMN Process Model.serialized_spec / subprocess_specs.

	When the BPMN diagram contains Business Rule Tasks, the corresponding
	DMN XML strings must be passed via ``dmn_xml_list`` so the parser can
	build DMNEngine instances for each referenced decision table.

	Args:
	    bpmn_xml:      Raw BPMN 2.0 XML string (may contain <?xml …?> declaration)
	    process_id:    The <bpmn:process id="…"> value to use as the entry point
	    dmn_xml_list:  Optional list of DMN XML strings. Each string is a
	                   complete DMN 1.3 document whose <decision id="…"> must
	                   match a calledDecisionId in the BPMN.

	Returns:
	    (spec_dict, sp_specs_dict)

	Raises:
	    ValidationException: if the BPMN or DMN XML is invalid
	    frappe.ValidationError: if process_id not found
	"""
	# Use BpmnDmnParser instead of plain BpmnParser — it extends the base
	# parser with DMN loading/correlation and businessRuleTask support.
	parser = BpmnDmnParser()

	# Register the businessRuleTask parser+spec so SpiffWorkflow knows how
	# to parse <bpmn:businessRuleTask> elements.  Uses the spiff variant
	# because bpmn-js-spiffworkflow writes <spiffworkflow:calledDecisionId>.
	parser.PARSER_CLASSES[_BRT_TAG] = (
		SpiffBusinessRuleTaskParser,
		SpiffBusinessRuleTask,
	)

	# lxml cannot parse a *string* that contains an encoding declaration,
	# but it can parse *bytes*.  Using add_bpmn_io(BytesIO) is the safe path.
	bpmn_bytes = bpmn_xml.strip().encode("utf-8")
	parser.add_bpmn_io(io.BytesIO(bpmn_bytes), filename="diagram.bpmn")

	# Feed each DMN XML string into the parser.  The parser registers each
	# DMN document by its <decision id="…"> attribute, which must match the
	# calledDecisionId written in the BPMN's <spiffworkflow:calledDecisionId>.
	for idx, dmn_xml in enumerate(dmn_xml_list or []):
		dmn_str = dmn_xml.strip() if isinstance(dmn_xml, str) else ""
		if dmn_str:
			parser.add_dmn_str(dmn_str.encode("utf-8"), filename=f"decision_{idx}.dmn")

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
	initiated_by: str = None,
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
		initiated_by=initiated_by,
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
	# values with live objects) — restore from a copy so the caller's dict
	# stays JSON-safe and reusable.
	wf = serializer.from_dict(copy.deepcopy(workflow_state))

	# Re-attach script engine (not serialised)
	wf.script_engine = _make_script_engine(
		context_doctype=context_doctype,
		context_docname=context_docname,
		script_task_extensions=script_task_extensions,
		initiated_by=initiated_by,
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
	if isinstance(spec, ReceiveTask):
		return "Receive Task"
	if isinstance(spec, SpiffBusinessRuleTask):
		return "Business Rule Task"
	if isinstance(spec, ExclusiveGateway):
		return "Exclusive Gateway"
	if isinstance(spec, ParallelGateway):
		return "Parallel Gateway"
	if isinstance(spec, InclusiveGateway):
		return "Inclusive Gateway"
	return type(spec).__name__


# ─────────────────────────────────────────────────────────────
# Ad-hoc subprocess dispatch loop (WI-001350)
#
# SpiffWorkflow readies EVERY unconditional no-input inner task the moment
# an ad-hoc subprocess is entered, and AdHocSubprocessSpec.parallel is
# stored but never read anywhere in its execution logic — the library has
# no working sequential mode (its parser outright rejects
# ordering="sequential"). one_bpmn's confirmed requirement is one inner
# task at a time, so the gate below enforces it: exactly one "head" task
# (a task connected from the subprocess start) may be READY/STARTED/WAITING
# at any moment; the rest are parked in FUTURE and promoted one by one, in
# the order the tasks appear in the diagram XML. Story 2-02 later swaps
# the "next in diagram order" decision for an LLM call — same loop, a
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
	to the subprocess start — both the unconditional no-input tasks connected
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
	READY, bypassing _update_hook — running such a task completes it with
	zero iterations, path_complete re-adds it, and the engine spins forever
	(reproducible with stock do_engine_steps too). Routing the instance
	through _update fires _update_hook, which moves it to STARTED and spawns
	its first iteration child.
	"""
	if isinstance(task.task_spec, LoopTask) and task.state == TaskState.READY:
		# Children include predicted flow successors (e.g. the EndJoin);
		# only children instantiated from the loop's inner spec count as
		# iterations. merge_child() sets the task READY again once the loop
		# is complete — that READY must run to completion, not re-arm.
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
	# from task data after merging workflow.data in — diagrams without any
	# <bpmn:dataObject> would crash there, so make sure the key exists.
	sp.data.setdefault("data_objects", {})

	heads = adhoc_head_tasks(sp)
	active = [t for t in heads if t.state & _ADHOC_ACTIVE_MASK]

	if len(active) > 1:
		# Subprocess entry (or a conditional re-add) readied several heads at
		# once — keep the first in diagram order, park the rest.
		changed = False
		for extra in active[1:]:
			if extra.state == TaskState.READY:
				extra._set_state(TaskState.FUTURE)
				changed = True
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
		# cancelled after the fact — poke them so completion propagates.
		for task in sp.get_tasks(spec_class=_EndJoin):
			if task.state & TaskState.NOT_FINISHED_MASK:
				task.task_spec._update(task)
	else:
		promoted = pending[0]
		promoted._set_state(TaskState.READY)
		_arm_loop_instance(promoted)
	return True


def do_engine_steps_gated(wf: BpmnWorkflow, did_complete_task=None, did_complete_adhoc_task=None):
	"""
	do_engine_steps() with the ad-hoc one-task-at-a-time gate.

	Stock do_engine_steps() sweeps ALL ready engine tasks per pass, so two
	ad-hoc heads readied together would both run before one_bpmn could
	intervene. This variant runs ONE ready engine task per iteration and
	re-applies the gate between runs, making it impossible for a second
	head to slip through. Subprocess-completion propagation (the parent
	task _update stock code does after each subprocess sweep) is preserved.

	Args:
	    wf:                       the running BpmnWorkflow
	    did_complete_task:        callback fired after every engine task run
	    did_complete_adhoc_task:  callback fired after an ad-hoc inner task
	                              completes (WI-001350 Scenario 7 uses this to
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
		):
			# Only for real BPMN inner tasks — engine-internal Start/EndJoin/End
			# tasks carry no bpmn_id and don't warrant a context-doc refresh.
			did_complete_adhoc_task(task)

		# Completion propagation (the reason stock do_engine_steps pokes
		# subprocess parents): when a subworkflow finishes, its parent task
		# only advances on the next _update. Poke ONLY completed subprocesses —
		# poking an in-flight one re-arms StandardLoopTask iterations and
		# spins the loop.
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
