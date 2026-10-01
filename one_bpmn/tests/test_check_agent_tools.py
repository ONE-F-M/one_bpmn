# Copyright (c) 2026, one-fm and contributors
"""``bench check-agent-tools`` smoke-checks every compiled agent tool.

A tool whose Server Script has a broken import must fail, loudly, before a
person asks the agent to use it. A tool whose script merely throws on an
empty, synthetic input (no doc, no real arguments) must still pass - that is
not an import problem, it is this check's own placeholder input meeting code
that expects something real.

Nothing the command runs is allowed to leave a trace: no Server Script,
AI Agent Run, BPMN Process Instance, Error Log or Communication count may
change, and frappe.enqueue must never be called.

``run_check()`` is exercised directly (the piece that does the actual work)
rather than the click command, which only adds ``frappe.init``/``connect``/
``destroy`` around it - a test process is already connected to a site.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.commands.agent_tools import _is_real_failure, run_check

BAD_IMPORT_SCRIPT = "import this_module_does_not_exist_anywhere\nresult['x'] = 1\n"
THROWS_SCRIPT = "raise ValueError('deliberately broken input')\n"
FINE_SCRIPT = "result['ok'] = True\n"


def _counts():
	return {
		"Server Script": frappe.db.count("Server Script"),
		"AI Agent Run": frappe.db.count("AI Agent Run"),
		"BPMN Process Instance": frappe.db.count("BPMN Process Instance"),
		"Error Log": frappe.db.count("Error Log"),
		"Communication": frappe.db.count("Communication"),
	}


def _make_script(name, body):
	if frappe.db.exists("Server Script", name):
		frappe.delete_doc("Server Script", name, force=True, ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Server Script",
			"name": name,
			"script_type": "API",
			"api_method": name.lower().replace(" ", "_"),
			"script": body,
		}
	).insert(ignore_permissions=True)


def _failures_for(failures, model_title):
	return [line for line in failures if line.startswith(f"FAIL {model_title} / ")]


def _make_model(title, process_id, tool_shapes, is_active=1, shape_configs=None):
	if frappe.db.exists("BPMN Process Model", title):
		frappe.delete_doc("BPMN Process Model", title, force=True, ignore_permissions=True)
	extensions = {"Agent_1": {"serviceType": "ai_agent", "aiToolShapes": json.dumps(tool_shapes)}}
	extensions.update(shape_configs or {})
	serialized_spec = json.dumps({"service_task_extensions": extensions})
	doc = frappe.get_doc(
		{
			"doctype": "BPMN Process Model",
			"title": title,
			"process_id": process_id,
			"version": 1,
			"is_active": is_active,
			"serialized_spec": serialized_spec,
		}
	)
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	return doc


class TestCheckAgentToolsDetection(FrappeTestCase):
	"""Unit-level: the failure classifier itself."""

	def test_import_error_is_a_real_failure(self):
		self.assertTrue(_is_real_failure(ModuleNotFoundError("No module named 'missing'")))

	def test_value_error_is_not_a_real_failure(self):
		self.assertFalse(_is_real_failure(ValueError("empty input")))

	def test_nonetype_attribute_error_is_not_a_real_failure(self):
		exc = AttributeError("'NoneType' object has no attribute 'whatever'")
		self.assertFalse(_is_real_failure(exc))

	def test_other_attribute_error_is_a_real_failure(self):
		exc = AttributeError("module 'foo' has no attribute 'bar'")
		self.assertTrue(_is_real_failure(exc))


class TestCheckAgentToolsCommand(FrappeTestCase):
	"""End-to-end: run_check() against real fixtures."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._scripts = {
			"ZZ Check Agent Tools Bad Import": BAD_IMPORT_SCRIPT,
			"ZZ Check Agent Tools Throws": THROWS_SCRIPT,
			"ZZ Check Agent Tools Fine": FINE_SCRIPT,
		}
		for name, body in cls._scripts.items():
			_make_script(name, body)

		cls.model_name = "ZZ Check Agent Tools Model"
		cls.isolated_model_name = "ZZ Check Agent Tools Isolated Model"
		cls.connector_model_name = "ZZ Check Agent Tools Connector Model"

		_make_model(
			cls.model_name,
			"zz_check_agent_tools",
			[
				{
					"bpmn_id": "bad_import_tool",
					"description": "Has a broken import.",
					"serverScript": "ZZ Check Agent Tools Bad Import",
				},
				{
					"bpmn_id": "throws_tool",
					"description": "Throws on empty input.",
					"serverScript": "ZZ Check Agent Tools Throws",
				},
				{
					"bpmn_id": "fine_tool",
					"description": "Runs cleanly.",
					"serverScript": "ZZ Check Agent Tools Fine",
				},
			],
		)

	@classmethod
	def tearDownClass(cls):
		for title in (cls.model_name, cls.isolated_model_name, cls.connector_model_name):
			if frappe.db.exists("BPMN Process Model", title):
				frappe.delete_doc("BPMN Process Model", title, force=True, ignore_permissions=True)
		for name in cls._scripts:
			if frappe.db.exists("Server Script", name):
				frappe.delete_doc("Server Script", name, force=True, ignore_permissions=True)
		super().tearDownClass()

	def test_bad_import_tool_fails(self):
		before = _counts()
		with patch("frappe.enqueue") as enqueue_mock:
			failures, _checked, _skipped = run_check()
		self.assertEqual(before, _counts())
		enqueue_mock.assert_not_called()
		ours = _failures_for(failures, self.model_name)
		self.assertEqual(len(ours), 1)
		self.assertIn("Agent_1 / bad_import_tool", ours[0])
		self.assertIn("ModuleNotFoundError", ours[0])

	def test_throwing_script_passes_when_checked_alone(self):
		"""A ValueError from an empty, synthetic call is not an import
		problem. Checked in isolation so a pass here proves the throwing
		tool specifically did not fail (not just that something else did)."""
		_make_model(
			self.isolated_model_name,
			"zz_check_agent_tools_isolated",
			[
				{
					"bpmn_id": "throws_tool",
					"description": "Throws on empty input.",
					"serverScript": "ZZ Check Agent Tools Throws",
				},
			],
		)
		try:
			frappe.db.set_value("BPMN Process Model", self.model_name, "is_active", 0)
			before = _counts()
			with patch("frappe.enqueue") as enqueue_mock:
				failures, _checked, _skipped = run_check()
			self.assertEqual(before, _counts())
			enqueue_mock.assert_not_called()
			self.assertEqual(_failures_for(failures, self.isolated_model_name), [])
		finally:
			frappe.db.set_value("BPMN Process Model", self.model_name, "is_active", 1)
			frappe.delete_doc(
				"BPMN Process Model", self.isolated_model_name, force=True, ignore_permissions=True
			)

	def test_no_side_effects_from_the_full_run(self):
		"""Server Script, AI Agent Run, BPMN Process Instance, Error Log and
		Communication counts must be unchanged whether a tool passed or failed."""
		before = _counts()
		with patch("frappe.enqueue") as enqueue_mock:
			run_check()
		self.assertEqual(before, _counts())
		enqueue_mock.assert_not_called()

	def test_connector_with_missing_handler_fails_when_wiring_is_only_on_the_shape(self):
		"""Older compiled specs carry connectorId/operation on the shape config, not the tool entry."""
		_make_model(
			self.connector_model_name,
			"zz_check_agent_tools_connector",
			[{"bpmn_id": "legacy_connector_tool", "description": "Old spec.", "serviceType": "connector"}],
			shape_configs={
				"legacy_connector_tool": {
					"serviceType": "connector",
					"connectorId": "zz_sandbox",
					"operation": "write_file",
				}
			},
		)
		spec = frappe._dict(handler_path="one_bpmn.this_module_does_not_exist.dispatch_action")
		try:
			with patch(
				"one_bpmn.commands.agent_tools.manifest.get_execution_spec", return_value=spec
			) as spec_mock:
				failures, _checked, _skipped = run_check()
			spec_mock.assert_any_call("zz_sandbox", "write_file")
			ours = _failures_for(failures, self.connector_model_name)
			self.assertEqual(len(ours), 1)
			self.assertIn("Agent_1 / legacy_connector_tool", ours[0])
			self.assertIn("ModuleNotFoundError", ours[0])
		finally:
			frappe.delete_doc(
				"BPMN Process Model", self.connector_model_name, force=True, ignore_permissions=True
			)
