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


def execute_shape(instance, bpmn_id: str, task_cfg: dict, kwargs: dict) -> str:
	"""
	Execute a single shape as a function tool and return a JSON string result.

	The result is the set of variables the shape produced — for a Script Task
	that is its ``result`` dict; for a Service Task it is whatever the dispatch
	handler wrote to ``task.data`` — excluding the arguments the LLM supplied.

	Never raises: failures are logged and returned as a structured
	``{"error": ...}`` payload so the tool-calling loop stays alive.
	"""
	try:
		task = _synthetic_task(bpmn_id, kwargs)
		server_script = task_cfg.get("serverScript", "")
		service_type = task_cfg.get("serviceType", "")

		if server_script:
			_run_server_script(instance, server_script, task, bpmn_id)
		elif service_type:
			# WI-002007: a connector reports its own outcome. Everything below
			# reads state the dispatcher already produces — how the connector
			# runs is untouched.
			# The descriptor carries only what identifies the shape as a tool;
			# connectorId / resultVariable live in the instance's service-task
			# extensions, which is also what the dispatcher itself reads.
			connector_cfg = {
				**task_cfg,
				**((getattr(instance, "_service_task_extensions", None) or {}).get(bpmn_id) or {}),
			}
			if service_type == "connector":
				refused = _connector_not_permitted(connector_cfg)
				if refused:
					return json.dumps(refused)

			# Reuse the instance's own router — it reads
			# instance._service_task_extensions and dispatches by serviceType,
			# writing outputs onto task.data exactly as in a normal run.
			instance._dispatch_service_task(task)

			if service_type == "connector":
				return json.dumps(_connector_tool_result(task, connector_cfg, kwargs), default=str)
		else:
			return json.dumps(
				{"error": f"Shape '{bpmn_id}' has no Server Script or serviceType — not executable as a tool."}
			)

		# The tool result is what the shape produced, not the args we injected.
		produced = {k: v for k, v in task.data.items() if k not in kwargs}
		return json.dumps(produced or {"ok": True}, default=str)
	except Exception:
		frappe.log_error(
			title=f"AI Agent shape tool '{bpmn_id}' failed",
			message=frappe.get_traceback(),
		)
		return json.dumps({"error": f"Shape '{bpmn_id}' failed — see Error Log for details."})


def _connector_not_permitted(task_cfg: dict) -> dict | None:
	"""The role gate, asked BEFORE dispatch so the answer can be reported.

	``dispatch_connector`` already enforces this — it logs and returns, which is
	correct as a control but reaches the model as an ordinary empty result,
	indistinguishable from a connector that simply returned nothing. Asking the
	same question here changes no behaviour; it only lets the tool result say
	which of the two happened (WI-002007). Returns None when permitted.
	"""
	from one_bpmn.one_bpmn.connectors import manifest as _manifest

	connector_id = (task_cfg.get("connectorId") or "").strip()
	if not connector_id or _manifest.user_may_use_connector(connector_id):
		return None
	return {
		"error": "not_permitted",
		"connector": connector_id,
		"message": (
			f"You are not permitted to use the '{connector_id}' connector, so it was not called. "
			"This is a permission decision, not a failure of the integration — do not retry it, "
			"and say so rather than reporting that the data is unavailable."
		),
	}


def _connector_tool_result(task, task_cfg: dict, kwargs: dict) -> dict:
	"""What a connector tool call should tell the model.

	Read entirely from what ``dispatch_connector`` leaves behind, because it
	swallows failures unless ``failOnError`` is set and the model was therefore
	being told a failed call succeeded:

	  * no resultVariable  → the key is never written. The connector ran and its
	    side effect happened, but nothing can come back. Previously this reached
	    the model as ``{"ok": true}``.
	  * key absent         → dispatch returned early (unknown connector, or
	    connectorParams that are not a JSON object). Both are logged there.
	  * key present, None  → the handler raised and the error was swallowed.
	    ``output`` stays None and is written anyway.
	"""
	result_var = (task_cfg.get("resultVariable") or "").strip()
	connector_id = (task_cfg.get("connectorId") or "").strip()
	operation = (task_cfg.get("operation") or "").strip()
	called = f"{connector_id}/{operation}".strip("/")

	if not result_var:
		return {
			"error": "no_result_variable",
			"connector": called,
			"message": (
				f"The '{called}' connector ran, but this shape has no Result Variable set, so it "
				"cannot return anything to you. Treat its output as unknown — do not assume the "
				"call produced data, and do not retry. The process map needs fixing."
			),
		}

	if result_var not in task.data:
		return {
			"error": "call_did_not_complete",
			"connector": called,
			"message": (
				f"The '{called}' connector did not run to completion — it is unknown or disabled, "
				"or its parameters were not valid. See the Error Log. Retrying will not help."
			),
		}

	if task.data[result_var] is None:
		return {
			"error": "connector_failed",
			"connector": called,
			"message": (
				f"The '{called}' connector was called and failed; the error was logged and the "
				"process was allowed to continue. You did NOT receive its data — do not report "
				"this call as successful."
			),
		}

	return {k: v for k, v in task.data.items() if k not in kwargs}


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


def _run_server_script(instance, script_name: str, task, bpmn_id: str) -> None:
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
