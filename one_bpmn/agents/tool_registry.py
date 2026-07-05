# Copyright (c) 2026, one-fm and contributors
# WI-001355 (3-02): compile an AI Agent Tool record into a callable ToolSpec.

import json

import frappe

from one_bpmn.agents.llm_provider.base import ToolSpec


def compile_tool_spec(doc) -> ToolSpec:
	"""
	Turn an AI Agent Tool document into a ToolSpec whose ``fn`` invokes the
	configured handler inside proper Frappe permission context.

	The returned ToolSpec is compatible with the tool-calling loops in
	agents/llm_provider — those loops never learn that a tool came from the
	database. Compilation is deterministic: name/description/parameters/
	required are plain copies of the record; only the fn closure identity
	differs between calls.

	Only handler_type="server_script" is executable (WI-001354 note);
	call_activity handlers compile to a structured not-implemented error so
	a mis-selected tool degrades gracefully instead of crashing the loop.
	"""
	name = doc.tool_name
	description = doc.description or ""
	parameters = _parsed_input_schema(doc)
	required = _required_param_list(doc)
	handler_type = doc.handler_type
	handler_reference = doc.handler_reference

	def fn(**kwargs):
		return _invoke_handler(name, handler_type, handler_reference, kwargs)

	return ToolSpec(
		fn=fn,
		name=name,
		description=description,
		parameters=parameters,
		required=required,
	)


def _parsed_input_schema(doc) -> dict:
	# The controller helper exists when the AI Agent Tool doctype module is
	# installed; fall back to parsing the raw field for duck-typed inputs.
	if hasattr(doc, "get_parsed_input_schema"):
		return dict(doc.get_parsed_input_schema())
	if isinstance(doc.input_schema, dict):
		return dict(doc.input_schema)
	return json.loads(doc.input_schema or "{}")


def _required_param_list(doc) -> list:
	if hasattr(doc, "get_required_param_list"):
		return list(doc.get_required_param_list())
	return [p.strip() for p in (doc.required_params or "").split(",") if p.strip()]


def _invoke_handler(tool_name: str, handler_type: str, handler_reference: str, kwargs: dict) -> str:
	"""
	Execute the tool handler and return a JSON string, matching the result
	shape of the existing tool_for_server_scripts.py functions so downstream
	tool_result handling is identical regardless of tool source.

	Never raises: failures are logged via frappe.log_error and returned as a
	structured {"error": ...} payload so the tool-calling loop stays alive.
	"""
	try:
		if handler_type != "server_script":
			return json.dumps(
				{"error": f"Tool '{tool_name}': handler type '{handler_type}' is not executable yet."}
			)

		script = frappe.get_doc("Server Script", handler_reference)
		if script.disabled:
			return json.dumps(
				{"error": f"Tool '{tool_name}': Server Script '{handler_reference}' is disabled."}
			)

		# API Server Scripts read their arguments from frappe.form_dict
		# (execute_method takes no parameters) and conventionally write their
		# output to frappe.response["message"]. Swap both around the call so
		# LLM-supplied arguments are visible and no state leaks into any
		# surrounding HTTP response.
		original_form_dict = frappe.local.form_dict
		original_message = frappe.local.response.get("message")
		frappe.local.form_dict = frappe._dict(kwargs)
		try:
			flags = script.execute_method()
			result = frappe.local.response.get("message")
		finally:
			frappe.local.form_dict = original_form_dict
			frappe.local.response["message"] = original_message

		if result is None:
			result = {
				key: value
				for key, value in dict(flags or {}).items()
				if not key.startswith("_") and _json_safe(value)
			}
		return json.dumps(result, default=str)

	except Exception:
		frappe.log_error(
			title=f"AI Agent Tool '{tool_name}' handler failed",
			message=frappe.get_traceback(),
		)
		return json.dumps({"error": f"Tool '{tool_name}' failed — see Error Log for details."})


def _json_safe(value) -> bool:
	try:
		json.dumps(value)
		return True
	except (TypeError, ValueError):
		return False
