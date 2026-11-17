# Copyright (c) 2026, one-fm and contributors
"""A connector tool's templates read the calling task's variables, and what the model passed still wins."""

import unittest
from unittest.mock import patch

import frappe
import jinja2

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
