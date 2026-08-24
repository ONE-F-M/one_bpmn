# Copyright (c) 2026, one-fm and contributors
# WI-001418 (AI Agent Task, Camunda-aligned): compile the shapes of an AI Agent
# Task's referenced ad-hoc sub-process into callable tools the agent invokes as
# functions.
#
# This is the "tools are the shapes" model (Camunda AI Agent Task connector):
# there is NO registry. The eligible leaf shapes of the agent's ad-hoc
# sub-process are resolved at COMPILE time (WI-001421) into tool descriptors and
# embedded in the agent's config; at runtime each descriptor becomes a tool
# whose function EXECUTES the shape inline and returns its result to the LLM.
# Contrast with the AI Task Selector, which ACTIVATES a shape as a process step.

import json

import frappe

from one_bpmn.agents.llm_provider.base import ToolSpec


def compile_shape_tools(tool_shapes, instance) -> list:
	"""
	Compile an AI Agent Task's tool-shape descriptors into callable ``ToolSpec``s.

	``tool_shapes`` is the list WI-001421 extracts from the referenced ad-hoc
	sub-process and embeds in the agent's config. Each descriptor carries::

	    {"bpmn_id": str, "description": str,
	     "serverScript": str (Script Task) | "serviceType": str (Service/Send)}

	Eligibility (executable leaf shapes only; human/container shapes excluded)
	is already enforced at extraction, so here we simply build one tool per
	descriptor: name = bpmn_id, description = the shape's documentation (Camunda
	uses an activity's documentation as its tool description). ``parameters``/
	``required`` (from the shape's aiToolParams, if any) are passed through so
	the LLM sees the tool's real argument schema instead of a zero-arg function.

	Args:
	    tool_shapes: list[dict] tool descriptors (may be a JSON string).
	    instance:    the BPMN Process Instance controller — provides context and,
	                 for service-task shapes, the dispatch router.

	Returns:
	    list[ToolSpec] — ready for ExecutorConfig.tools / the adapter tool loop.
	"""
	if isinstance(tool_shapes, str):
		try:
			tool_shapes = json.loads(tool_shapes or "[]")
		except Exception:
			tool_shapes = []

	tools = []
	for shape in tool_shapes or []:
		if not isinstance(shape, dict):
			continue
		bpmn_id = shape.get("bpmn_id")
		if not bpmn_id:
			continue
		if shape.get("human"):
			# Durable HITL: a User/Manual shape is a HUMAN tool. The step
			# loop never calls fn — selecting it suspends the agent until a
			# person completes the spawned task; the stub only exists to make
			# a mis-routed call loud instead of silent.
			description = (shape.get("description") or "").strip() or (
				f"Ask a person to handle: {shape.get('label') or bpmn_id}"
			)
			tools.append(
				ToolSpec(
					fn=_make_human_stub(bpmn_id),
					name=bpmn_id,
					description=description,
					parameters=shape.get("parameters") or {},
					required=shape.get("required") or [],
					human=True,
				)
			)
			continue
		# Executable-inline only: a shape is a callable tool when it runs a
		# Server Script or dispatches a service/send action.
		if not (shape.get("serverScript") or shape.get("serviceType")):
			continue
		description = (shape.get("description") or "").strip() or bpmn_id
		tools.append(
			ToolSpec(
				fn=_make_shape_fn(instance, bpmn_id, shape),
				name=bpmn_id,
				description=description,
				parameters=shape.get("parameters") or {},
				required=shape.get("required") or [],
			)
		)
	return tools


# Set on frappe.flags while a turn already holds a pause, so a tool that WOULD
# park can refuse to start rather than being abandoned. It lives here beside
# ToolDeferred because the two are halves of one rule: the loop tracks one pause
# per turn, so a second one must never begin work. Written by
# agents/executor/step_loop.py, read by
# connectors/a2a_client_ops.delegate_to_local_agent — kept in this module so
# neither of those has to import the other.
PAUSE_HELD_FLAG = "a2a_pause_held_this_turn"


class ToolDeferred(Exception):
	"""A tool started work that finishes later, so it has no result yet.

	Raised instead of returning, because there is no answer to return: the
	shape handed work to something outside this turn (today, an agent on this
	site that parks on a person) and the model must not be told anything until
	that work reports back.

	It carries the waiting marker the dispatch left on the task, which names
	what to wait for. The step loop turns this into the same suspension a
	human tool produces — the only difference is who supplies the answer.
	"""

	def __init__(self, marker: dict):
		super().__init__("tool deferred — waiting on work outside this turn")
		self.marker = marker or {}


def _make_human_stub(bpmn_id: str):
	def fn(**kwargs):
		raise RuntimeError(
			f"Human tool '{bpmn_id}' must suspend the agent, never execute inline."
		)

	return fn


def _make_shape_fn(instance, bpmn_id: str, task_cfg: dict):
	def fn(**kwargs):
		return execute_shape(instance, bpmn_id, task_cfg, kwargs)

	return fn


def execute_shape(instance, bpmn_id: str, task_cfg: dict | None, kwargs: dict) -> str:
	"""
	Execute a single shape as a function tool and return a JSON string result.

	``task_cfg=None`` means "look up the real shape's own compiled config" —
	for a Script Task (review_script, finalize) calling a REAL nested AI Agent
	Task shape it doesn't otherwise reference, rather than an outer agent's own
	tool-calling loop, which always has the shape's descriptor in hand already
	(from aiToolShapes) and passes it explicitly. An empty dict ``{}`` is a
	real (if empty) override, not a signal to look anything up — only ``None``
	triggers the lookup.

	The result is the set of variables the shape produced — for a Script Task
	that is its ``result`` dict; for a Service Task it is whatever the dispatch
	handler wrote to ``task.data`` — excluding the arguments the LLM supplied.

	Never raises, with one exception: ``ToolDeferred``, which is not a failure
	but "no answer yet" and must reach the loop so it can suspend. Ordinary
	failures are logged and returned as a structured ``{"error": ...}`` payload
	so the tool-calling loop stays alive.
	"""
	try:
		if task_cfg is None:
			task_cfg = (getattr(instance, "_service_task_extensions", {}) or {}).get(bpmn_id, {})
		task = _synthetic_task(bpmn_id, kwargs)
		server_script = task_cfg.get("serverScript", "")
		service_type = task_cfg.get("serviceType", "")

		if server_script:
			_run_server_script(instance, server_script, task, bpmn_id, task_cfg)
		elif service_type:
			# task_cfg is this shape's own compiled descriptor, passed through
			# as an explicit override rather than re-derived from bpmn_id.
			instance._dispatch_service_task(task, task_cfg)
		else:
			return json.dumps(
				{"error": f"Shape '{bpmn_id}' has no Server Script or serviceType — not executable as a tool."}
			)

		# A shape that parked did not answer. Returning its waiting marker as if
		# it were a result is how a slow delegation used to be lost: the model
		# read "still working" as the outcome, said so, and the process finished
		# while the other agent was still going.
		waiting = _waiting_marker(task)
		if waiting:
			raise ToolDeferred(waiting)

		# The tool result is what the shape produced, not the args we injected.
		produced = {k: v for k, v in task.data.items() if k not in kwargs}

		# Persist the result so a downstream tool can read it back via the
		# get_turn Jinja global (hooks.py).
		if service_type == "ai_agent" and getattr(instance, "context_docname", None):
			try:
				from one_bpmn.agents.turn_state import update_turn

				update_turn(instance.context_docname, **{f"{bpmn_id}_result": produced})
			except Exception:
				frappe.log_error(
					title=f"AI Agent shape tool '{bpmn_id}' turn-state persist failed",
					message=frappe.get_traceback(),
				)

		return json.dumps(produced or {"ok": True}, default=str)
	except ToolDeferred:
		raise
	except Exception:
		frappe.log_error(
			title=f"AI Agent shape tool '{bpmn_id}' failed",
			message=frappe.get_traceback(),
		)
		return json.dumps({"error": f"Shape '{bpmn_id}' failed — see Error Log for details."})


def _waiting_marker(task) -> dict | None:
	"""The marker a dispatch leaves when it parked instead of answering."""
	from one_bpmn.one_bpmn.connectors.a2a_client_ops import A2A_WAITING_KEY

	data = getattr(task, "data", None)
	if not isinstance(data, dict):
		return None
	marker = data.get(A2A_WAITING_KEY)
	return marker if isinstance(marker, dict) else None


def _synthetic_task(bpmn_id: str, kwargs: dict):
	"""A minimal task-like object the script/dispatch paths accept: carries the
	LLM arguments in ``data`` and the bpmn_id on ``task_spec``. A ``workflow``
	stub with its own ``data`` satisfies handlers (e.g. send tasks) that peek at
	the containing scope."""
	return frappe._dict(
		data=dict(kwargs),
		task_spec=frappe._dict(bpmn_id=bpmn_id, name=bpmn_id, description=bpmn_id),
		workflow=frappe._dict(data={}),
	)


def _run_server_script(instance, script_name: str, task, bpmn_id: str, task_cfg: dict | None = None) -> None:
	"""
	Run a Script Task's Server Script the way the engine's FrappeScriptEngine
	does (trusted, pre-deployed code; ``result`` dict merged into task.data),
	but invoked directly so the agent can call it as a tool. LLM-supplied
	arguments are visible to the script as locals.
	"""
	from one_bpmn.one_bpmn.engine import _check_script_permissions

	script_doc = frappe.get_doc("Server Script", script_name)
	if not script_doc or script_doc.disabled:
		frappe.throw(f"Server Script '{script_name}' not found or disabled (shape {bpmn_id}).")

	_check_script_permissions(script_doc.script, script_name)

	result_dict = {}
	local_vars = dict(task.data)
	local_vars.update(
		{
			"frappe": frappe,
			"context_doctype": getattr(instance, "context_doctype", "") or "",
			"context_docname": getattr(instance, "context_docname", "") or "",
			"result": result_dict,
			# Lets the script call execute_shape(instance, ...) for its own tracked AI Agent Run.
			"instance": instance,
			# Diagram-set spiffworkflow:aiAgentConfig override; empty when unset.
			"ai_agent_config": (task_cfg or {}).get("aiAgentConfig", ""),
			# Same convention as the engine's FrappeScriptEngine: scripts may
			# read their inputs bundled under `task_data` (the LLM-supplied
			# arguments, here) instead of as bare locals.
			"task_data": dict(task.data),
			# WHICH shape is running. The tool name the LLM called IS the shape's
			# bpmn_id, so a family of same-shaped tools can share ONE Server
			# Script and dispatch on this instead of duplicating a body per tool
			# (Lumina General Chat fans 32 MCP tools out of a single script).
			"bpmn_id": bpmn_id,
		}
	)
	if getattr(instance, "context_doctype", None) and getattr(instance, "context_docname", None):
		try:
			local_vars["doc"] = frappe.get_doc(instance.context_doctype, instance.context_docname)
		except Exception:
			local_vars["doc"] = frappe._dict()
	else:
		local_vars["doc"] = frappe._dict()

	# Trusted, pre-deployed BPMN code — plain exec (mirrors engine.py), not
	# safe_exec (which is for untrusted browser-submitted scripts).
	exec_globals = {"frappe": frappe, "__builtins__": __builtins__}  # noqa: S102
	exec(script_doc.script, exec_globals, local_vars)  # noqa: S102

	if isinstance(result_dict, dict) and result_dict:
		task.data.update(result_dict)
