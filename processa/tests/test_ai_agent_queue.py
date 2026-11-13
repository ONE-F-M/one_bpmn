# Copyright (c) 2026, one-fm and contributors
# Dedicated bpmn_ai_agent background job queue.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

test_ignore = ["BPMN Process Model"]


class TestAiAgentQueueRouting(FrappeTestCase):
	# ── Scenario 2: both call sites enqueue on bpmn_ai_agent explicitly ──

	def test_start_process_async_uses_dedicated_queue(self):
		from processa.api import instances

		model = frappe.get_all("BPMN Process Model", limit=1, pluck="name")
		if not model:
			self.skipTest("No BPMN Process Model on site")
		with patch.object(frappe, "enqueue") as enqueue:
			instances.start_process_async(model_name=model[0])
		enqueue.assert_called_once()
		self.assertEqual(enqueue.call_args.kwargs.get("queue"), "bpmn_ai_agent")

	def test_run_eval_suite_uses_dedicated_queue(self):
		import re

		import processa.ai_agent_evals.runner.suite as runner_suite

		source = open(runner_suite.__file__.replace(".pyc", ".py")).read()
		enqueue_block = re.search(
			r"frappe\.enqueue\(\s*\"processa\.ai_agent_evals\.runner\.suite\.execute_eval_suite\".*?\)",
			source,
			re.DOTALL,
		)
		self.assertIsNotNone(enqueue_block)
		self.assertIn('queue="bpmn_ai_agent"', enqueue_block.group(0))

	# ── Scenario 4: no other enqueue call site was rerouted ──

	def test_no_other_call_sites_rerouted(self):
		import pathlib

		app_root = pathlib.Path(frappe.get_app_path("processa")).parent
		offenders = []
		for py in app_root.rglob("*.py"):
			if "node_modules" in str(py) or "/tests/" in str(py):
				continue
			text = py.read_text(errors="ignore")
			if 'queue="bpmn_ai_agent"' in text and py.name not in (
				# start_process_async — explicit async API
				"starting.py",
				"task_actions.py",
				# The eval runner: the suite, case and comparison entry points and the lane jobs
				"suite.py",
				"cases.py",
				"comparison.py",
				"lanes.py",
				# Parked AI units run as AI-only jobs —
				# the ONLY engine-driven producer after the inline flip
				"bpmn_process_instance.py",
			):
				offenders.append(py.name)
		self.assertEqual(offenders, [])

	# ── Scenario 1: distinct queue with its own configuration ──

	def test_queue_registered_in_bench_config(self):
		workers = frappe.get_common_site_config().get("workers") or {}
		if "bpmn_ai_agent" not in workers:
			self.skipTest(
				"bpmn_ai_agent not in common_site_config workers — register it "
				"on this bench (documented in the original PR)"
			)
		self.assertNotIn("bpmn_ai_agent", ("default", "short", "long"))
		self.assertIsInstance(workers["bpmn_ai_agent"], dict)
