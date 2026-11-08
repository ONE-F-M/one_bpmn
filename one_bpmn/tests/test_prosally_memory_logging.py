# Copyright (c) 2026, one-fm and contributors
"""A ProsAlly memory write leaves a trace of whether it was queued and what the distiller returned.

Run with:
    bench run-tests --app one_bpmn --module one_bpmn.tests.test_prosally_memory_logging
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers as helpers
from one_bpmn.agents.memory import writeback
from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers as D

TURN = {"memory_process": "Zz Process", "user_text": "yes", "memory_notes": [], "chat_history": []}
DRAWN = {"intent": "BPMN_MODIFIED", "response": "Drew it."}
DISTILLED = {"memory_write_mode": "distilled"}


def _titles(log_error):
	return [call.kwargs.get("title") for call in log_error.call_args_list]


class TestQueueLogsItsDecision(FrappeTestCase):
	def _queue(self, turn, agent_result, fields=DISTILLED):
		cfg = {"name": "CFG", "ai_model": "m", "ai_provider": "p"}
		with patch.object(helpers, "prosally_config", return_value=cfg), patch.object(
			helpers, "_memory_fields", return_value=fields
		), patch.object(D, "_enqueue_distill") as enqueue, patch.object(frappe, "log_error") as log_error:
			helpers.queue_process_memory(turn, agent_result)
		return enqueue, log_error

	def test_a_queued_write_is_logged(self):
		enqueue, log_error = self._queue(TURN, DRAWN)
		enqueue.assert_called_once()
		self.assertEqual(_titles(log_error), ["ProsAlly memory: write queued"])

	def test_a_diagram_matching_no_process_is_logged_as_skipped(self):
		enqueue, log_error = self._queue({**TURN, "memory_process": ""}, DRAWN)
		enqueue.assert_not_called()
		self.assertEqual(_titles(log_error), ["ProsAlly memory: write skipped"])

	def test_a_write_mode_that_is_not_distilled_is_logged_as_skipped(self):
		enqueue, log_error = self._queue(TURN, DRAWN, {"memory_write_mode": "off"})
		enqueue.assert_not_called()
		self.assertEqual(_titles(log_error), ["ProsAlly memory: write skipped"])

	def test_turns_that_do_not_draw_log_nothing(self):
		for intent in ("CLARIFY", "IRRELEVANT", "CONFIRM", None):
			_, log_error = self._queue(TURN, {"intent": intent, "response": "x"})
			log_error.assert_not_called()


class TestWritebackLogsAnEmptyDistillation(FrappeTestCase):
	def _write(self, facts):
		with patch.object(writeback, "_distill_with_retries", return_value=facts), patch.object(
			writeback, "_reconcile_batch", side_effect=lambda f, ctx: f
		), patch("one_bpmn.agents.memory.tools.memory_write", return_value={"name": "M"}), patch.object(
			frappe, "log_error"
		) as log_error:
			written = writeback.distill_and_write(
				agent_output="x",
				agent="prosally_agent",
				scope="Entity",
				scope_key={"reference_doctype": "Process", "reference_name": "Zz Process"},
				provider_name="p",
				backend="direct_api",
				model="m",
				source_run=None,
			)
		return written, log_error

	def test_no_facts_is_logged_with_the_agent_and_the_key(self):
		written, log_error = self._write([])
		self.assertEqual(written, [])
		self.assertEqual(_titles(log_error), ["AI Memory: distiller returned no facts"])
		self.assertIn("Zz Process", log_error.call_args.kwargs["message"])

	def test_facts_are_written_without_an_error_entry(self):
		fact = {"content": "a rule", "topic": "t", "dedup_key": "a:t"}
		written, log_error = self._write([fact])
		self.assertEqual(written, ["M"])
		log_error.assert_not_called()
