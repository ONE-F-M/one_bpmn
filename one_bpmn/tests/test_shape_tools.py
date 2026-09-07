# Copyright (c) 2026, one-fm and contributors
# WI-001418: compile ad-hoc sub-process shape descriptors into callable AI Agent
# tools, and execute a shape as a function tool.

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.shape_tools import compile_shape_tools, execute_shape


def _fake_instance():
	return frappe._dict(
		_service_task_extensions={},
		context_doctype="",
		context_docname="",
		initiated_by="Administrator",
	)


class TestCompileShapeTools(FrappeTestCase):
	def test_descriptors_become_tools(self):
		shapes = [
			{"bpmn_id": "lookup_customer", "description": "Look up a customer.", "serverScript": "S1"},
			{"bpmn_id": "create_order", "description": "Create an order.", "serviceType": "update_field"},
		]
		tools = compile_shape_tools(shapes, _fake_instance())
		self.assertEqual(sorted(t.name for t in tools), ["create_order", "lookup_customer"])
		by_name = {t.name: t for t in tools}
		# Description comes from the shape's documentation (Camunda convention).
		self.assertEqual(by_name["lookup_customer"].description, "Look up a customer.")
		self.assertTrue(callable(by_name["create_order"].fn))

	def test_unconfigured_or_bad_descriptors_skipped(self):
		shapes = [
			{"bpmn_id": "human_task", "description": "A user task"},  # no serverScript/serviceType
			{"description": "no id"},  # missing bpmn_id
			"not a dict",
		]
		self.assertEqual(compile_shape_tools(shapes, _fake_instance()), [])

	def test_accepts_json_string(self):
		shapes = json.dumps([{"bpmn_id": "t1", "serverScript": "S"}])
		self.assertEqual([t.name for t in compile_shape_tools(shapes, _fake_instance())], ["t1"])

	def test_empty_or_none(self):
		self.assertEqual(compile_shape_tools(None, _fake_instance()), [])
		self.assertEqual(compile_shape_tools([], _fake_instance()), [])

	def test_parameters_and_required_are_threaded_through(self):
		shapes = [
			{
				"bpmn_id": "search",
				"description": "Search records.",
				"serverScript": "S1",
				"parameters": {"query": {"type": "string", "description": "Search text"}},
				"required": ["query"],
			},
			{"bpmn_id": "no_args", "description": "No-arg tool.", "serverScript": "S2"},
		]
		tools = compile_shape_tools(shapes, _fake_instance())
		by_name = {t.name: t for t in tools}
		self.assertEqual(by_name["search"].parameters, {"query": {"type": "string", "description": "Search text"}})
		self.assertEqual(by_name["search"].required, ["query"])
		# A descriptor with no parameters/required still gets a zero-arg tool.
		self.assertEqual(by_name["no_args"].parameters, {})
		self.assertEqual(by_name["no_args"].required, [])


class TestExecuteShape(FrappeTestCase):
	def _script(self, name, body):
		if not frappe.db.exists("Server Script", name):
			frappe.get_doc(
				{
					"doctype": "Server Script",
					"name": name,
					"script_type": "API",
					"api_method": name.lower().replace(" ", "_"),
					"script": body,
				}
			).insert(ignore_permissions=True)
		return name

	def test_script_shape_runs_and_returns_result(self):
		# A Script Task shape's server script sets `result` (engine convention),
		# which becomes the tool's returned payload; LLM args are locals.
		name = self._script("Shape Greeter Script", 'result["greeting"] = "hi " + name')
		out = execute_shape(_fake_instance(), "task_x", {"serverScript": name}, {"name": "World"})
		payload = json.loads(out)
		self.assertEqual(payload["greeting"], "hi World")
		# The injected argument is not echoed back as a produced result.
		self.assertNotIn("name", payload)

	def test_unconfigured_shape_returns_structured_error(self):
		out = execute_shape(_fake_instance(), "task_y", {}, {})
		self.assertIn("error", json.loads(out))

	def test_failing_script_is_caught_not_raised(self):
		name = self._script("Shape Boom Script", 'raise ValueError("boom")')
		out = execute_shape(_fake_instance(), "task_z", {"serverScript": name}, {})
		self.assertIn("error", json.loads(out))

	def test_top_level_def_can_call_another_top_level_def_and_use_a_top_level_import(self):
		"""_run_server_script used to exec() with separate globals/locals dicts —
		a top-level `def`'s own __globals__ was the (near-empty) globals dict, so
		it could not see another top-level function or a top-level import in the
		SAME script, and died with NameError the instant one was actually called.
		One merged namespace (mirrors engine.py's own exec()) fixes this."""
		name = self._script(
			"Shape Namespace Script",
			"import json as _json\n"
			"def _format(value):\n"
			"    return _json.dumps({'value': value})\n"
			"def _build():\n"
			"    return _format(name)\n"
			"result['out'] = _build()\n",
		)
		out = execute_shape(_fake_instance(), "task_ns", {"serverScript": name}, {"name": "World"})
		payload = json.loads(out)
		self.assertEqual(payload["out"], '{"value": "World"}')
