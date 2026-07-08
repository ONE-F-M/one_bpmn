# Copyright (c) 2026, one-fm and contributors
# WI-001499: "Waiting for AI execution" indicator — backend surface.
#
# The frontend banner/chip/diagram highlight read:
# - BPMN Process Instance.waiting_for_ai (set/cleared by the engine seam)
# - instance_api.get_parked_ai_tasks — names the parked units (kind,
#   task_id, bpmn_id, label) for the banner text, the diagram's pulsing
#   purple outline, and the manual retry button's targets
# - instance_api.list_process_instances — includes waiting_for_ai for the
#   list chip

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


class TestParkedAiUnits(JobHarness):
	def test_parked_agent_reported_with_bpmn_id(self):
		from one_bpmn.api.instance_api import get_parked_ai_tasks

		task_id = self._park_linear_with_tools()
		units = get_parked_ai_tasks(self.instance.name)
		self.assertEqual(len(units), 1)
		self.assertEqual(units[0]["kind"], "service_task")
		self.assertEqual(units[0]["task_id"], task_id)
		self.assertEqual(units[0]["bpmn_id"], "Agent_1")

	def test_no_units_after_completion(self):
		from one_bpmn.api.instance_api import get_parked_ai_tasks

		task_id = self._park_linear_with_tools()
		with patch(
			"one_bpmn.agents.executor.direct_api.DirectApiExecutor.run",
			return_value=_executor_with_tools(),
		):
			with patch.object(frappe, "enqueue"):
				run_parked_ai_task(self.instance.name, "service_task", task_id)
		self.instance.reload()
		self.assertEqual(self.instance.get_parked_ai_units(), [])
		self.assertEqual(self.instance.waiting_for_ai, 0)

	def test_units_survive_exhausted_failure_for_retry_button(self):
		from one_bpmn.api.instance_api import get_parked_ai_tasks

		task_id = self._park_linear_with_tools()
		with patch.object(
			BPMNProcessInstance, "resume_parked_ai", side_effect=RuntimeError("boom")
		):
			with patch.object(frappe, "enqueue"):
				run_parked_ai_task(self.instance.name, "service_task", task_id, attempt=2)
		# Errored — but the unit is still reported so the retry button has
		# its target.
		units = get_parked_ai_tasks(self.instance.name)
		self.assertEqual([u["task_id"] for u in units], [task_id])

	def test_permission_failure(self):
		from one_bpmn.api.instance_api import get_parked_ai_tasks

		self._park_linear_with_tools()
		with self.set_user("Guest"):
			with self.assertRaises(frappe.PermissionError):
				get_parked_ai_tasks(self.instance.name)

	def test_list_api_exposes_waiting_for_ai(self):
		from one_bpmn.api.instance_api import list_process_instances

		self._park_linear_with_tools()
		self.instance.db_update()
		rows = list_process_instances(
			filters={"name": self.instance.name}, limit_page_length=1
		)
		self.assertEqual(len(rows), 1)
		self.assertIn("waiting_for_ai", rows[0])
		self.assertEqual(rows[0]["waiting_for_ai"], 1)
