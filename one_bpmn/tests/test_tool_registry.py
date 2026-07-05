# Copyright (c) 2026, one-fm and contributors
# WI-001355 (3-02): ToolSpec compiler — AI Agent Tool to ToolSpec.

from __future__ import annotations

import json
from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.llm_provider.base import ToolSpec
from one_bpmn.agents.tool_registry import compile_tool_spec

SCHEMA = {
	"summary": {"type": "string", "description": "Short summary"},
	"count": {"type": "integer", "description": "How many"},
}


def _tool_doc(**overrides):
	"""Duck-typed AI Agent Tool record — compile_tool_spec only reads fields,
	so the tests run even on branches where the doctype module is absent."""
	values = {
		"tool_name": "registry_test_tool",
		"description": "Echoes its arguments back.",
		"input_schema": json.dumps(SCHEMA),
		"required_params": "summary",
		"handler_type": "server_script",
		"handler_reference": "Registry Echo Script",
		"is_active": 1,
	}
	values.update(overrides)
	return SimpleNamespace(**values)


def _make_server_script(name, script, disabled=0):
	if frappe.db.exists("Server Script", name):
		frappe.delete_doc("Server Script", name, force=True)
	doc = frappe.get_doc(
		{
			"doctype": "Server Script",
			"name": name,
			"script_type": "API",
			"api_method": name.lower().replace(" ", "_"),
			"script": script,
			"disabled": disabled,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


class TestCompileToolSpec(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_make_server_script(
			"Registry Echo Script",
			"frappe.response['message'] = {'echo': frappe.form_dict.get('summary')}",
		)
		_make_server_script(
			"Registry Broken Script",
			"raise Exception('kaboom')",
		)

	# ── Scenario 1: fields copied, fn wraps the Server Script ──

	def test_compiles_to_toolspec_with_copied_fields(self):
		spec = compile_tool_spec(_tool_doc())
		self.assertIsInstance(spec, ToolSpec)
		self.assertEqual(spec.name, "registry_test_tool")
		self.assertEqual(spec.description, "Echoes its arguments back.")
		self.assertEqual(spec.parameters, SCHEMA)
		self.assertEqual(spec.required, ["summary"])
		self.assertTrue(callable(spec.fn))

	def test_fn_passes_llm_arguments_via_form_dict(self):
		spec = compile_tool_spec(_tool_doc())
		result = json.loads(spec.fn(summary="hello world"))
		self.assertEqual(result, {"echo": "hello world"})

	def test_fn_restores_form_dict_and_response(self):
		original_form_dict = frappe.local.form_dict
		frappe.local.response["message"] = "sentinel"
		spec = compile_tool_spec(_tool_doc())
		spec.fn(summary="x")
		self.assertIs(frappe.local.form_dict, original_form_dict)
		self.assertEqual(frappe.local.response.get("message"), "sentinel")
		frappe.local.response.pop("message", None)

	# ── Scenario 2: handler exceptions caught, logged, structured ──

	def test_fn_exception_returns_structured_error(self):
		spec = compile_tool_spec(_tool_doc(handler_reference="Registry Broken Script"))
		result = json.loads(spec.fn(summary="x"))
		self.assertIn("error", result)

	def test_fn_missing_script_returns_structured_error(self):
		spec = compile_tool_spec(_tool_doc(handler_reference="No Such Script 404"))
		result = json.loads(spec.fn(summary="x"))
		self.assertIn("error", result)

	def test_fn_disabled_script_returns_structured_error(self):
		_make_server_script("Registry Disabled Script", "pass", disabled=1)
		spec = compile_tool_spec(_tool_doc(handler_reference="Registry Disabled Script"))
		result = json.loads(spec.fn(summary="x"))
		self.assertIn("error", result)

	def test_call_activity_handler_not_executable_yet(self):
		spec = compile_tool_spec(
			_tool_doc(handler_type="call_activity", handler_reference="Anything")
		)
		result = json.loads(spec.fn())
		self.assertIn("error", result)
		self.assertIn("not executable", result["error"])

	# ── Scenario 3: results JSON-serialized like tool_for_server_scripts ──

	def test_fn_returns_json_string(self):
		spec = compile_tool_spec(_tool_doc())
		raw = spec.fn(summary="json check")
		self.assertIsInstance(raw, str)
		json.loads(raw)  # must parse

	# ── Scenario 4: deterministic compilation ──

	def test_double_compile_is_deterministic(self):
		doc = _tool_doc()
		first = compile_tool_spec(doc)
		second = compile_tool_spec(doc)
		self.assertEqual(first.name, second.name)
		self.assertEqual(first.description, second.description)
		self.assertEqual(first.parameters, second.parameters)
		self.assertEqual(first.required, second.required)
		self.assertIsNot(first.fn, second.fn)  # only the closure identity differs
