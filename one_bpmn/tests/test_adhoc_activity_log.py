# Copyright (c) 2026, one-fm and contributors
# WI-001359 (4-02): bpmn_activity_log entries for ad-hoc subprocess and
# selector decisions.

from __future__ import annotations

import json
from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn import engine

test_ignore = ["BPMN Process Instance", "BPMN Process Model"]


def _instance():
	doc = frappe.get_doc(
		{
			"doctype": "BPMN Process Instance",
			"process_id": f"log-{frappe.generate_hash(length=6)}",
			"status": "Active",
		}
	)
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	return doc


def _fake_task(bpmn_id="task_b", task_id="0a1b2c3d-uuid"):
	spec = SimpleNamespace(name=bpmn_id, bpmn_id=bpmn_id, description="Task B")
	return SimpleNamespace(id=task_id, task_spec=spec)


def _fake_sp(name="AdhocSub_1"):
	return SimpleNamespace(spec=SimpleNamespace(name=name))


class TestAdhocActivityLog(FrappeTestCase):
	# ── Scenario 4: new action values are selectable filters ──

	def test_action_options_include_new_types(self):
		options = frappe.get_meta("BPMN Activity Log").get_field("action").options.split("\n")
		self.assertIn("Ad-Hoc Task Activated", options)
		self.assertIn("AI Task Selected", options)

	# ── Scenario 1: activation logged with parent subprocess in data ──

	def test_adhoc_activation_logged(self):
		instance = _instance()
		instance._log_adhoc_activation(_fake_sp(), _fake_task())

		rows = frappe.get_all(
			"BPMN Activity Log",
			filters={"instance": instance.name, "action": "Ad-Hoc Task Activated"},
			fields=["task_id", "data"],
		)
		self.assertEqual(len(rows), 1)
		data = json.loads(rows[0].data)
		self.assertEqual(data["bpmn_id"], "task_b")
		self.assertEqual(data["parent_subprocess"], "AdhocSub_1")

	# ── Scenario 3: dedup on re-processing the same state ──

	def test_duplicate_activation_deduplicated(self):
		instance = _instance()
		instance._log_adhoc_activation(_fake_sp(), _fake_task())
		instance._log_adhoc_activation(_fake_sp(), _fake_task())  # engine restart replay

		count = frappe.db.count(
			"BPMN Activity Log",
			{"instance": instance.name, "action": "Ad-Hoc Task Activated"},
		)
		self.assertEqual(count, 1)

	# ── Scenario 2: selector decision logged with tools + truncated args ──

	def test_ai_task_selected_logged_with_summary(self):
		instance = _instance()
		instance.log_ai_task_selected("AdhocSub_1", ["task_b"], {"note": "x" * 600})

		rows = frappe.get_all(
			"BPMN Activity Log",
			filters={"instance": instance.name, "action": "AI Task Selected"},
			fields=["data"],
		)
		self.assertEqual(len(rows), 1)
		data = json.loads(rows[0].data)
		self.assertEqual(data["chosen_tools"], ["task_b"])
		self.assertLessEqual(len(data["arguments_summary"]), 501)
		self.assertTrue(data["arguments_summary"].endswith("…"))

	# ── Engine hook: never raises into the engine, active only when set ──

	def test_notify_hook_is_safe_and_scoped(self):
		calls = []
		engine.adhoc_task_activated_logger = lambda sp, task: calls.append(task.task_spec.name)
		try:
			engine.notify_adhoc_activation(_fake_sp(), _fake_task("task_a"))
		finally:
			engine.adhoc_task_activated_logger = None
		self.assertEqual(calls, ["task_a"])

		# Unset hook: no-op. Broken hook: swallowed.
		engine.notify_adhoc_activation(_fake_sp(), _fake_task())
		engine.adhoc_task_activated_logger = lambda sp, task: 1 / 0
		try:
			engine.notify_adhoc_activation(_fake_sp(), _fake_task())  # must not raise
		finally:
			engine.adhoc_task_activated_logger = None
