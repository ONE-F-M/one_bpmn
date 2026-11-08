# Copyright (c) 2026, one-fm and contributors
"""FrappeScriptEngine: runs BPMN Script Tasks and their Server Scripts."""

from datetime import datetime

from SpiffWorkflow.bpmn.script_engine import PythonScriptEngine, TaskDataEnvironment

# ─────────────────────────────────────────────────────────────
# Permission guard - patterns scripts must never contain
# ─────────────────────────────────────────────────────────────

def evaluate_condition(expression: str, names: dict):
	"""Evaluate a map condition with the script validator applied and the ordinary builtins."""
	_check_script_permissions(expression, "condition")
	return eval(expression, {"__builtins__": __builtins__, **names})


def check_server_script(script_doc) -> None:
	"""Validate a Server Script before it runs, opening only what its approval lists."""
	from one_bpmn.security.script_gate import approved_names

	_check_script_permissions(script_doc.script, script_doc.name, approved_names(script_doc))


def _check_script_permissions(script_text: str, label: str, allowed: frozenset = frozenset()) -> None:
	"""Run the save-time AST validator again right before exec() and throw on any violation.

	Shared by Server Script tasks, inline <bpmn:script> tasks, conditions and run_logix_test_case.
	"""
	try:
		import frappe as _f
	except ImportError:
		return

	from one_bpmn.security.script_validator import deep_inspect_script

	violations = deep_inspect_script(script_text or "", allowed=allowed)
	if violations:
		_f.log_error(
			title=f'BPMN Script "{label}": execution blocked',
			message="\n".join(violations),
		)
		_f.throw(
			_f._('BPMN Script "{0}" was blocked before it ran: {1} ({2} issue(s) in total)').format(
				label, violations[0], len(violations)
			)
		)


class _ValidatedEnvironment(TaskDataEnvironment):
	"""Task data environment that runs the script validator on every expression it evaluates."""

	def evaluate(self, expression, context, external_context=None):
		_check_script_permissions(expression, "condition")
		return super().evaluate(expression, context, external_context)


# ─────────────────────────────────────────────────────────────
# FrappeScriptEngine - custom ScriptEngine with Server Script support
# ─────────────────────────────────────────────────────────────


class FrappeScriptEngine(PythonScriptEngine):
	"""
	A PythonScriptEngine that intercepts Script Task execution.

	If the task has a ``serverScript`` attribute registered in
	``script_task_extensions`` (embedded at compile time), the engine
	calls that Frappe Server Script instead of running the inline
	``<bpmn:script>`` content.

	The script receives these local variables:
	    frappe             - the Frappe module
	    doc                - the context document (if any)
	    context_doctype    - linked DocType string
	    context_docname    - linked document name string
	    result             - pre-set to {} - set values on this to pass
	                         data back into the workflow (gateway routing)
	    <all task.data>    - current workflow variables

	Gateway conditions can then check: result["action"] == "Approve"
	(but only if the script sets it on ``result``).

	Example Server Script body::

	    doc = frappe.get_doc(context_doctype, context_docname)
	    if doc.total_leave_days > 10:
	        result["action"] = "Escalate"
	    else:
	        result["action"] = "Approve"
	"""

	def __init__(self, environment, script_task_extensions=None, context_doctype=None, context_docname=None, initiated_by=None, instance=None):
		super().__init__(environment)
		self._script_task_extensions = script_task_extensions or {}
		self._context_doctype = context_doctype
		self._context_docname = context_docname
		self._initiated_by = initiated_by or "Administrator"
		# Lets a Script Task call execute_shape(instance, ...) for its own tracked AI Agent Run.
		self._instance = instance

	def execute(self, task, script, **kwargs):
		"""
		Override: enforce user permission context for all script execution.

		Before running any script (Server Script or inline), this method:
		  1. Validates the script content for forbidden permission-bypass patterns
		  2. Switches frappe.session.user to self._initiated_by so the script
		     runs with that user's permission context (ignore_permissions=False)
		     - but only when it actually differs from the current user, and it
		     snapshots/restores the full session so an inline (web-request) run
		     never corrupts the caller's browser session
		  3. Restores the original session user (and sid/data) after execution

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

		# frappe.set_user() rewrites session.sid and WIPES session.data. When a
		# script task runs INLINE inside a web request (user submits/approves a
		# BPMN-driven document), that guts the caller's browser session and the
		# next request fails with "User None is disabled". So:
		#   - skip the switch entirely when we already run as the target user
		#     (the common inline case - session is never touched), and
		#   - for a genuine switch, snapshot sid+data and restore them in the
		#     finally so end-of-request persistence keeps the real session.
		# Same hazard the triggers.py inline-start path guards against.
		original_user = _frappe.session.user
		need_switch = bool(self._initiated_by) and self._initiated_by != original_user
		saved_sid = _frappe.session.sid
		saved_data = _frappe.session.data
		saved_in_script = _frappe.flags.in_processa_script
		try:
			if need_switch:
				_frappe.set_user(self._initiated_by)
			_frappe.flags.ignore_permissions = False
			_frappe.flags.in_processa_script = True

			if server_script_name:
				self._run_frappe_server_script(server_script_name, task)
			else:
				super().execute(task, script, **kwargs)
		finally:
			if need_switch:
				_frappe.set_user(original_user)
				# set_user() gutted session.sid/.data above - put the real
				# browser session back so it is not persisted as userless.
				_frappe.session.sid = saved_sid
				_frappe.session.data = saved_data
			_frappe.flags.ignore_permissions = False
			_frappe.flags.in_processa_script = saved_in_script

	def _agent_for_script(self, script_name: str) -> str:
		"""The agent whose map runs this Server Script, or "" for an ordinary process.

		Keyed on the SCRIPT, not on the shape and not on the workflow, because only
		the script is unique. Two routes were tried and both were wrong:

		- ``task.workflow.spec.name`` hands back the TOP-LEVEL process even for a
		  task inside a called map, so a script in the orchestrator's own map
		  reported "Software Development" and resolved to no agent.
		- the shape's bpmn_id is not unique either - "answer" is declared by three
		  different agent maps on this site, so a shape id would have attributed
		  the orchestrator's report to a test agent.

		A Server Script belongs to one map. Cached briefly because this runs once
		per script task and the answer rarely changes.
		"""
		if not script_name:
			return ""
		# Imported here, like everywhere else in this module: frappe and json are
		# function-local throughout, and using them at method scope without the
		# import raised a NameError that the except below swallowed into "no
		# agent" - which looked exactly like an ordinary process.
		import json as _json

		import frappe as _frappe

		try:
			owners = _frappe.cache.get_value("bpmn_script_owning_agent")
			if owners is None:
				owners = {}
				for row in _frappe.get_all(
					"AI Agent Configuration",
					filters={"process_model": ["is", "set"]},
					fields=["name", "process_model"],
				):
					spec = _frappe.db.get_value(
						"BPMN Process Model", row.process_model, "serialized_spec"
					)
					if not spec:
						continue
					try:
						parsed = _json.loads(spec)
					except Exception:
						continue
					for cfg in (parsed.get("script_task_extensions") or {}).values():
						named = (cfg or {}).get("serverScript")
						if named:
							owners.setdefault(named, row.name)
				_frappe.cache.set_value("bpmn_script_owning_agent", owners, expires_in_sec=300)
			return owners.get(script_name, "")
		except Exception:
			# Attribution is worth having and not worth failing a task for.
			return ""

	def _run_frappe_server_script(self, script_name: str, task) -> None:
		"""
		Execute a Frappe Server Script (API type) with workflow context.

		The script's ``result`` dict is merged into ``task.data`` after
		execution, making the values available to downstream gateways
		via conditions like: action == "Approve"
		"""
		try:
			import frappe as _frappe

			# Guarantee the sanctioned outbound-HTTP helpers are reachable via
			# their fully-qualified path. Server Scripts run through plain exec()
			# with the real `frappe` module (not safe_exec, which pre-binds the
			# bare make_get_request names), so scripts must call
			# `frappe.integrations.utils.make_get_request(...)` etc. A bare
			# `import frappe` does NOT auto-load that submodule, so without this
			# eager import the qualified access raises AttributeError in a worker
			# that has not imported it yet. Cheap after the first load (cached in
			# sys.modules); Logix is taught to emit exactly this qualified form.
			import frappe.integrations.utils  # noqa: F401
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

		check_server_script(script_doc)

		# Build locals: workflow variables + framework context
		#
		# Workflow variables are exposed two ways so either script convention works:
		#   1. spread as top-level names (e.g. `user_text`) - the legacy style, and
		#   2. bundled under `task_data` (e.g. `task_data.get("user_text", "")`) -
		#      the style the chat-agent scripts (ProsAlly/Logix/Docu) use so they can
		#      safely `.get()` keys that don't exist on every turn without NameError.
		# `task_data` is a copy: scripts only read from it and write outputs to
		# `result`, so mutations can't leak back into engine state unexpectedly.
		task_data = dict(task.data)
		local_vars = dict(task_data)
		result_dict = {}
		local_vars.update(
			{
				"frappe": _frappe,
				# which agent this script belongs to, if any.
				#
				# A script task inside an agent's own map IS the agent acting, and
				# its writes should say so. The tool path already runs as the
				# agent; this path still runs as the person who started the run,
				# which is right for a process's own script tasks and wrong for an
				# agent's. Changing who the whole path runs as would alter
				# attribution AND permissions for every agent map at once, so the
				# name is injected instead and a script that cares - one that
				# writes a comment a person will read - opts in.
				"agent_configuration": self._agent_for_script(script_name),
				"context_doctype": self._context_doctype or "",
				"context_docname": self._context_docname or "",
				"result": result_dict,
				# For execute_shape(instance, ...) - see FrappeScriptEngine.__init__.
				"instance": self._instance,
				# This shape's own id, same as shape_tools.py injects for tool leaves.
				"bpmn_id": getattr(task.task_spec, "bpmn_id", None) or "",
				# Snapshot of the workflow variables as a plain dict, so scripts
				# can safely read OPTIONAL vars - e.g. task_data.get("x", default)
				# - without resorting to locals()/globals() (blocked by the
				# script-security validator).
				"task_data": dict(task.data),
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
			# scripts - it requires server_script_enabled in common_site_config and
			# runs code in a RestrictedPython sandbox with a limited frappe namespace.
			# BPMN Server Scripts are trusted, pre-deployed code stored in the DB,
			# so they run with the real frappe module and no config gate.
			# ONE namespace for globals AND locals. With separate dicts,
			# top-level `def`s land in locals but each function's __globals__
			# is exec_globals - so a script where one function calls another
			# (or reads a top-level variable) dies with NameError at runtime.
			exec_ns = {"frappe": _frappe, "__builtins__": __builtins__}
			exec_ns.update(local_vars)
			exec(script_doc.script, exec_ns)  # noqa: S102
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
	instance=None,
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

	env = _ValidatedEnvironment(extra)
	return FrappeScriptEngine(
		env,
		script_task_extensions=script_task_extensions,
		context_doctype=context_doctype,
		context_docname=context_docname,
		initiated_by=initiated_by,
		instance=instance,
	)
