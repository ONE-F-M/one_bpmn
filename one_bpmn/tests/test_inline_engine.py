# Copyright (c) 2026, one-fm and contributors
# WI-001494: inline engine execution for non-AI passes.
#
# Engine passes triggered by a doc event or a user action run inline in the
# request unless the model contains AI tasks (serviceType ai_agent /
# ai_task_selector) — those keep the whole-pass enqueue on bpmn_ai_agent
# until the park-and-enqueue seam (WI-001495/WI-001496) narrows it to just
# the AI task.

from __future__ import annotations

import re

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.trigger import model_requires_ai_worker, should_run_engine_inline

test_ignore = ["BPMN Process Model"]

_PLAIN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="defs_plain">
  <bpmn:process id="proc_plain" isExecutable="true">
    <bpmn:startEvent id="start_1" />
    <bpmn:scriptTask id="script_1" name="Plain Script" />
    <bpmn:serviceTask id="svc_1" spiffworkflow:serviceType="update_field" />
    <bpmn:endEvent id="end_1" />
  </bpmn:process>
</bpmn:definitions>"""

_AGENT_XML = _PLAIN_XML.replace(
	'spiffworkflow:serviceType="update_field"',
	'spiffworkflow:serviceType="ai_agent"',
).replace("defs_plain", "defs_agent").replace("proc_plain", "proc_agent")

_SELECTOR_XML = _PLAIN_XML.replace(
	'spiffworkflow:serviceType="update_field"',
	'spiffworkflow:serviceType="ai_task_selector"',
).replace("defs_plain", "defs_selector").replace("proc_plain", "proc_selector")


class TestInlineEngineDecision(FrappeTestCase):
	"""model_requires_ai_worker / should_run_engine_inline behaviour."""

	def _make_model(self, title: str, xml: str) -> str:
		model = frappe.new_doc("BPMN Process Model")
		model.title = title
		model.bpmn_xml = xml
		model.insert(ignore_permissions=True)
		return model.name

	# ── Scenario: model without AI tasks runs inline ──

	def test_plain_model_does_not_require_ai_worker(self):
		name = self._make_model("WI-001494 plain", _PLAIN_XML)
		self.assertFalse(model_requires_ai_worker(name))
		self.assertTrue(should_run_engine_inline(name))

	# ── Scenario: models with AI tasks keep the background pass ──

	def test_ai_agent_model_requires_ai_worker(self):
		name = self._make_model("WI-001494 agent", _AGENT_XML)
		self.assertTrue(model_requires_ai_worker(name))

	def test_ai_task_selector_model_requires_ai_worker(self):
		name = self._make_model("WI-001494 selector", _SELECTOR_XML)
		self.assertTrue(model_requires_ai_worker(name))

	def test_ai_model_runs_inline_only_because_in_test(self):
		# in_test forces inline even for AI models (no worker, auto-rollback).
		# Outside tests the same model must NOT run inline.
		name = self._make_model("WI-001494 agent inline", _AGENT_XML)
		self.assertTrue(should_run_engine_inline(name))  # in_test is set

		frappe.flags.in_test = False
		try:
			self.assertFalse(should_run_engine_inline(name))
		finally:
			frappe.flags.in_test = True

	def test_plain_model_runs_inline_outside_tests(self):
		name = self._make_model("WI-001494 plain inline", _PLAIN_XML)
		frappe.flags.in_test = False
		try:
			self.assertTrue(should_run_engine_inline(name))
		finally:
			frappe.flags.in_test = True

	def test_missing_xml_defaults_to_inline(self):
		model = frappe.new_doc("BPMN Process Model")
		model.title = "WI-001494 empty"
		model.process_id = "proc_wi001494_empty"
		model.insert(ignore_permissions=True)
		self.assertFalse(model_requires_ai_worker(model.name))


class TestInlineEngineWiring(FrappeTestCase):
	"""Both engine entry points consult should_run_engine_inline before
	enqueuing (source-level checks, same style as test_ai_agent_queue)."""

	def _source(self, module) -> str:
		return open(module.__file__.replace(".pyc", ".py")).read()

	def test_trigger_start_consults_inline_decision(self):
		from one_bpmn.one_bpmn import trigger

		source = self._source(trigger)
		start = source[source.index("def _maybe_start_instance") :]
		start = start[: start.index("\ndef ")]
		# The inline branch must come before the enqueue and call
		# start_queued_instance directly.
		self.assertIn("if should_run_engine_inline(model_name):", start)
		self.assertLess(
			start.index("should_run_engine_inline"),
			start.index("frappe.enqueue"),
		)
		inline_branch = start[
			start.index("should_run_engine_inline") : start.index("frappe.enqueue")
		]
		self.assertIn("start_queued_instance(instance.name", inline_branch)

	def test_complete_task_consults_inline_decision(self):
		from one_bpmn.api import instance_api

		source = self._source(instance_api)
		body = source[source.index("def complete_task") :]
		body = body[: body.index("\ndef ")]
		self.assertIn("if should_run_engine_inline(instance.process_model):", body)
		self.assertLess(
			body.index("should_run_engine_inline"),
			body.index("frappe.enqueue"),
		)
		inline_branch = body[
			body.index("should_run_engine_inline") : body.index("frappe.enqueue")
		]
		self.assertIn("_complete_task_job(", inline_branch)

	def test_no_bare_in_test_branch_remains_at_entry_points(self):
		# The in_test escape hatch is folded into should_run_engine_inline —
		# neither entry point should branch on frappe.flags.in_test directly.
		from one_bpmn.api import instance_api
		from one_bpmn.one_bpmn import trigger

		for module, func in ((trigger, "_maybe_start_instance"), (instance_api, "def complete_task")):
			source = self._source(module)
			body = source[source.index(func) :]
			body = body[: body.index("\ndef ")]
			self.assertNotIn(
				"frappe.flags.in_test",
				body,
				f"{func} still branches on in_test directly",
			)

	def test_doc_event_advance_still_inline(self):
		# _advance_instance_on_doc_event has always been inline — it must not
		# grow an enqueue as part of this change.
		from one_bpmn.one_bpmn import trigger

		source = self._source(trigger)
		body = source[source.index("def _advance_instance_on_doc_event") :]
		body = body[: body.index("\ndef ")]
		self.assertNotIn("frappe.enqueue", body)
		self.assertIn("instance.advance(", body)
