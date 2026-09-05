# Copyright (c) 2026, one-fm and contributors
"""A queued agent job must outlive the model calls it is allowed to make.

An agent turn is a model call plus tool execution. At the shape's default
aiTimeout of 180s with aiMaxRetries 2, three attempts reach 540s — so the old
600s job ceiling could kill a run before its first turn returned. Observed as
an AI Agent Run with status Error, 0 tokens, 0 cost and
"Task exceeded maximum timeout value (600 seconds)", while the A2A Task
reported "ran out of turns" for a run that never took one.
"""

from __future__ import annotations

import re
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.job_limits import AI_AGENT_JOB_TIMEOUT

APP = Path(__file__).resolve().parents[1]

# Every module that queues work onto the AI agent queue.
ENQUEUE_SITES = [
	"tasks.py",
	"api/instance_api.py",
	"api/agent_callback.py",
	"one_bpmn/doctype/bpmn_process_instance/bpmn_process_instance.py",
]


class TestAIAgentJobTimeout(FrappeTestCase):
	def test_outlives_one_model_call_with_its_retries(self):
		"""540s of attempts must fit, with room for tool execution."""
		worst_case_one_turn = 180 * (1 + 2)
		self.assertGreater(
			AI_AGENT_JOB_TIMEOUT,
			worst_case_one_turn,
			"the job is killed before a single turn can finish its retries",
		)

	def test_no_ai_queue_enqueue_still_hardcodes_600(self):
		"""The ceiling lives in one constant, not scattered literals."""
		offenders = []
		for rel in ENQUEUE_SITES:
			text = (APP / rel).read_text()
			lines = text.split("\n")
			for i, line in enumerate(lines):
				if not re.match(r"^\s*timeout=600,\s*$", line):
					continue
				window = "\n".join(lines[max(0, i - 8) : i + 8])
				if 'queue="bpmn_ai_agent"' in window:
					offenders.append(f"{rel}:{i + 1}")
		self.assertFalse(
			offenders,
			"AI queue enqueues still hardcode 600s: " + ", ".join(offenders),
		)

	def test_every_ai_queue_enqueue_imports_the_constant(self):
		for rel in ENQUEUE_SITES:
			text = (APP / rel).read_text()
			if 'queue="bpmn_ai_agent"' not in text:
				continue
			self.assertIn(
				"AI_AGENT_JOB_TIMEOUT",
				text,
				f"{rel} queues AI work without using the shared ceiling",
			)
