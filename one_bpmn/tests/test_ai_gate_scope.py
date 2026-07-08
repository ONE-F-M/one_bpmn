# Copyright (c) 2026, one-fm and contributors
# WI-001498: concurrency gate scoped to ACTIVE AI execution.
#
# engine_in_progress is held only while an AI job (or a concurrent
# complete_task pass) is actually running:
# - held  → complete_task rejects with "instance is processing"
# - clear → any wait state (parked AI job queued, human task, catch event)
#           accepts user actions — human tasks stay completable even when
#           spawned by AI (prerequisite for User-tasks-via-AI-Agent / HITL)
# - a crashed AI job ALWAYS releases the gate (finally) — never wedged

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.doctype.bpmn_process_instance.bpmn_process_instance import (
	BPMNProcessInstance,
	run_parked_ai_task,
)
from one_bpmn.tests.test_ai_job_executor import JobHarness, _executor_with_tools

test_ignore = ["BPMN Process Model"]


class TestGateScope(JobHarness):
	def _gate(self):
		return frappe.db.get_value(
			"BPMN Process Instance", self.instance.name, "engine_in_progress"
		)

	def test_gate_held_only_while_ai_job_executes(self):
		task_id = self._park_linear_with_tools()
		# Parked and waiting: the gate is CLEAR (actions allowed).
		self.assertFalse(self._gate())

		observed = {}

		def observe(instance, kind, task_id):
			observed["during"] = frappe.db.get_value(
				"BPMN Process Instance", instance.name, "engine_in_progress"
			)

		with patch.object(BPMNProcessInstance, "resume_parked_ai", new=observe):
			with patch.object(frappe, "enqueue"):
				run_parked_ai_task(self.instance.name, "service_task", task_id)

		self.assertEqual(observed["during"], 1)  # held while executing
		self.assertEqual(self._gate(), 0)  # released after

	def test_complete_task_rejected_while_gate_held(self):
		from one_bpmn.api.instance_api import complete_task

		self._park_linear_with_tools()
		frappe.db.set_value(
			"BPMN Process Instance",
			self.instance.name,
			"engine_in_progress",
			1,
			update_modified=False,
		)
		with self.assertRaises(frappe.ValidationError) as ctx:
			complete_task(self.instance.name, "any-task-id")
		self.assertIn("processing", str(ctx.exception).lower())

	def test_complete_task_accepted_at_wait_state(self):
		from one_bpmn.api.instance_api import complete_task

		self._park_linear_with_tools()
		self.assertFalse(self._gate())  # waiting on AI job — gate clear
		# The gate check passes; the request fails later on task lookup —
		# proving a WAITING instance is not locked.
		with self.assertRaises(frappe.ValidationError) as ctx:
			complete_task(self.instance.name, "no-such-task")
		self.assertNotIn("processing", str(ctx.exception).lower())
		self.assertIn("not found", str(ctx.exception).lower())

	def test_crashed_job_releases_gate(self):
		task_id = self._park_linear_with_tools()
		with patch.object(
			BPMNProcessInstance, "resume_parked_ai", side_effect=RuntimeError("boom")
		):
			with patch.object(frappe, "enqueue"):
				# below the retry cap → retry scheduled
				run_parked_ai_task(self.instance.name, "service_task", task_id, attempt=0)
		self.assertEqual(self._gate(), 0)

		with patch.object(
			BPMNProcessInstance, "resume_parked_ai", side_effect=RuntimeError("boom")
		):
			with patch.object(frappe, "enqueue"):
				# exhausted → Errored, gate still released
				run_parked_ai_task(self.instance.name, "service_task", task_id, attempt=2)
		self.assertEqual(self._gate(), 0)

	def test_successful_job_releases_gate(self):
		task_id = self._park_linear_with_tools()
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=_executor_with_tools(),
		):
			with patch.object(frappe, "enqueue"):
				run_parked_ai_task(self.instance.name, "service_task", task_id)
		self.assertEqual(self._gate(), 0)
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self.instance.name, "status"),
			"Completed",
		)
