# Copyright (c) 2026, one-fm and contributors
# WI-001494 + WI-001496: inline engine execution.
#
# Engine passes triggered by a doc event or a user action run inline in the
# request — the whole-pass enqueue of WI-001365 is gone. The ONLY background
# work is the AI-only job produced by the WI-001495 park-and-enqueue seam
# (see test_ai_park_enqueue).

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

test_ignore = ["BPMN Process Model"]


class TestInlineEngineWiring(FrappeTestCase):
	"""Both engine entry points run inline with no whole-pass enqueue
	(source-level checks, same style as test_ai_agent_queue)."""

	def _source(self, module) -> str:
		return open(module.__file__.replace(".pyc", ".py")).read()

	def _func_body(self, module, func_def: str) -> str:
		source = self._source(module)
		body = source[source.index(func_def) :]
		return body[: body.index("\ndef ")]

	def test_trigger_start_runs_inline(self):
		from one_bpmn.one_bpmn import trigger

		body = self._func_body(trigger, "def _maybe_start_instance")
		# The first engine pass runs inline in the save request…
		self.assertIn("start_queued_instance(instance.name", body)
		# …with no whole-pass enqueue left.
		self.assertNotIn("frappe.enqueue", body)

	def test_complete_task_runs_inline(self):
		from one_bpmn.api import instance_api

		body = self._func_body(instance_api, "def complete_task")
		self.assertIn("_complete_task_job(", body)
		self.assertNotIn("frappe.enqueue", body)
		# The response reports the real resulting state.
		self.assertIn('"queued": False', body)
		self.assertIn('"waiting_for_ai"', body)

	def test_no_in_test_branch_at_entry_points(self):
		# Inline is unconditional — no environment-dependent branching left.
		from one_bpmn.api import instance_api
		from one_bpmn.one_bpmn import trigger

		for module, func in (
			(trigger, "def _maybe_start_instance"),
			(instance_api, "def complete_task"),
		):
			body = self._func_body(module, func)
			self.assertNotIn(
				"frappe.flags.in_test",
				body,
				f"{func} still branches on in_test",
			)

	def test_doc_event_advance_still_inline(self):
		from one_bpmn.one_bpmn import trigger

		body = self._func_body(trigger, "def _advance_instance_on_doc_event")
		self.assertNotIn("frappe.enqueue", body)
		self.assertIn("instance.advance(", body)

	def test_trigger_has_no_queue_call_sites_left(self):
		# After WI-001496 the seam (bpmn_process_instance.py) and the explicit
		# start_process_async API are the only bpmn_ai_agent producers.
		from one_bpmn.one_bpmn import trigger

		self.assertNotIn('queue="bpmn_ai_agent"', self._source(trigger))

	def test_start_queued_instance_guard_survives(self):
		# Stranded pre-inline Queued instances must still be startable.
		from one_bpmn.one_bpmn import trigger

		body = self._func_body(trigger, "def start_queued_instance")
		self.assertIn('if instance.status != "Queued":', body)
