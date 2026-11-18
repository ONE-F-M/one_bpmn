# Copyright (c) 2026, one-fm and contributors
"""A connector or script tool reads the calling task's variables, and what the model passed still wins."""

import unittest
from unittest.mock import patch

import frappe
import jinja2

from processa.ai_agent_skills.tools import shape_tools
from processa.processa_engine.dispatch.connector import dispatch_connector

CFG = {
	"connectorId": "agent_sandbox",
	"operation": "prepare_site",
	"connectorParams": '{"target_app": "{{ task_data.target_app }}", "roles": "{{ task_data.roles }}"}',
}


def _dispatch(task):
	seen = {}

	def handler(params, ctx):
		seen["params"], seen["task_data"] = params, ctx["task_data"]

	with (
		patch("processa.processa_connectors.manifest.user_may_use_connector", return_value=True),
		patch("processa.processa_connectors.manifest.field_specs", return_value={}),
		patch("processa.processa_connectors.manifest.field_transforms", return_value={}),
		patch("processa.processa_engine.dispatch.connector._resolve_connector_handler", return_value=handler),
		patch("frappe.render_template", side_effect=lambda t, c: jinja2.Template(t).render(**c)),
	):
		dispatch_connector(frappe._dict(context_doctype="", context_docname=""), task, CFG, "prepare_site")
	return seen


class TestToolCallTaskData(unittest.TestCase):
	def test_the_calling_tasks_variables_fill_in_what_the_model_did_not_pass(self):
		task = frappe._dict(data={"roles": "System Manager"}, process_data={"target_app": "frappe_agile"})
		self.assertEqual(_dispatch(task)["params"], {"target_app": "frappe_agile", "roles": "System Manager"})

	def test_what_the_model_passed_wins_over_the_variables(self):
		task = frappe._dict(data={"roles": "A"}, process_data={"target_app": "frappe_agile", "roles": "B"})
		self.assertEqual(_dispatch(task)["params"]["roles"], "A")

	def test_a_step_with_no_process_data_reads_its_own_data_as_before(self):
		task = frappe._dict(data={"target_app": "processa", "roles": "A"})
		seen = _dispatch(task)
		self.assertEqual(seen["params"], {"target_app": "processa", "roles": "A"})
		self.assertNotIn("process_data", task.data)

	def test_the_tool_result_does_not_pick_up_the_process_variables(self):
		task = frappe._dict(data={"roles": "A"}, process_data={"target_app": "frappe_agile"})
		_dispatch(task)
		self.assertEqual(set(task.data) - {"_bpmn_connector_outcome"}, {"roles"})


SCRIPT = """
result["task_data"] = dict(task_data)
result["criteria_is_a_bare_local"] = "criteria" in dir()
"""


def _run_script(task):
	"""Runs a Server Script tool whose body records what it was given; returns what it put in `result`."""
	import contextlib

	script = frappe._dict(disabled=0, script=SCRIPT)
	instance = frappe._dict(context_doctype="", context_docname="")
	with (
		patch.object(shape_tools.frappe, "get_doc", return_value=script),
		patch.object(shape_tools.frappe, "session", frappe._dict(user="Administrator", sid="sid", data={})),
		patch.object(shape_tools.frappe, "flags", frappe._dict()),
		patch("processa.processa_engine.engine.check_server_script"),
		patch("processa.ai_agent_security.identity.user_for", return_value=None),
		patch.object(shape_tools.observability, "current_run_name", return_value=None),
		patch.object(shape_tools.observability, "sub_call_scope", side_effect=lambda *a: contextlib.nullcontext()),
	):
		shape_tools._run_server_script(instance, "Some Script", task, "submit_assertions")
	return task.data


class TestScriptToolTaskData(unittest.TestCase):
	def test_a_script_tool_sees_the_calling_tasks_variables_in_task_data(self):
		task = frappe._dict(data={"assertions": "x"}, process_data={"criteria": ["AC1"]})
		self.assertEqual(_run_script(task)["task_data"], {"criteria": ["AC1"], "assertions": "x"})

	def test_what_the_model_passed_wins_over_the_variables(self):
		task = frappe._dict(data={"criteria": ["from model"]}, process_data={"criteria": ["from process"]})
		self.assertEqual(_run_script(task)["task_data"]["criteria"], ["from model"])

	def test_the_bare_locals_stay_the_models_arguments_only(self):
		task = frappe._dict(data={"assertions": "x"}, process_data={"criteria": ["AC1"]})
		self.assertFalse(_run_script(task)["criteria_is_a_bare_local"])

	def test_no_process_data_behaves_as_before(self):
		task = frappe._dict(data={"assertions": "x"})
		self.assertEqual(_run_script(task)["task_data"], {"assertions": "x"})


class TestEmptyArgumentsDoNotHideVariables(unittest.TestCase):
	def test_an_empty_argument_keeps_the_process_value(self):
		from processa.processa_engine.dispatch.common import merge_task_data

		merged = merge_task_data({"criteria": ["AC1"], "run_id": "r1"}, {"criteria": "", "run_id": None, "file": "a.js"})
		self.assertEqual(merged, {"criteria": ["AC1"], "run_id": "r1", "file": "a.js"})

	def test_a_real_argument_still_wins_and_false_or_zero_count_as_real(self):
		from processa.processa_engine.dispatch.common import merge_task_data

		merged = merge_task_data({"a": 1, "b": True}, {"a": 0, "b": False})
		self.assertEqual(merged, {"a": 0, "b": False})

	def test_an_empty_argument_with_no_process_value_is_kept(self):
		from processa.processa_engine.dispatch.common import merge_task_data

		self.assertEqual(merge_task_data(None, {"x": ""}), {"x": ""})

	def test_a_connector_step_ignores_an_empty_model_value(self):
		task = frappe._dict(data={"target_app": ""}, process_data={"target_app": "frappe_agile"})
		self.assertEqual(_dispatch(task)["task_data"]["target_app"], "frappe_agile")
