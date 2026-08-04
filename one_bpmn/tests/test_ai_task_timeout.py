# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
The timeout an AI Agent Task actually runs with.

This exists because a fix was made and had no effect. ``ExecutorConfig``'s
default was raised from 30s to 180s with a careful note explaining why — but
``dispatch_ai_agent`` passed its own hardcoded ``30`` for every shape, so the
new default was unreachable from any process map. Nothing failed; drafting just
kept being cut off mid-thought.

The cost was real: a Policy drafted from a 3k-character guideline needs ~58s and
was being killed at 30s, twice (once per retry), and the process then published
the empty result. Measured on the run that prompted this — 61,794 ms to fail
with 0 tokens, against 58,115 ms to succeed once the limit was right.

So these tests assert the *resolved* value rather than the constant. A test on
the constant alone would have passed throughout the period the bug existed.
"""

from __future__ import annotations

import re

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch

from one_bpmn.agents.executor import (
	DEFAULT_TIMEOUT_SECONDS,
	ErrorCode,
	ExecutorResult,
	TokenUsage,
)


def _ok_result():
	return ExecutorResult(
		error_code=ErrorCode.SUCCESS, output="drafted", token_usage=TokenUsage(), trace=[]
	)


class TestResolvedTimeout(FrappeTestCase):
	"""What reaches ExecutorConfig, not what the dataclass declares."""

	def setUp(self):
		self.instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_id": f"test-{frappe.generate_hash(length=6)}",
			"status": "Active",
		})
		self.instance.flags.ignore_mandatory = True
		self.instance.insert(ignore_permissions=True, ignore_mandatory=True)
		self.bpmn_id = "Agent_1"
		self.task = frappe._dict({
			"data": {},
			"task_spec": frappe._dict({"name": self.bpmn_id, "description": "Agent"}),
		})

	def _resolved(self, task_cfg):
		"""Dispatch and return the ExecutorConfig the dispatcher built."""
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		captured = {}

		def fake_run(_self, config, context):
			captured["config"] = config
			return _ok_result()

		base = {"serviceType": "ai_agent", "aiProvider": "", "aiModel": "gpt-4o",
		        "aiUserPrompt": "draft it"}
		base.update(task_cfg)
		with patch("one_bpmn.agents.executor.direct_api.DirectApiExecutor.run", new=fake_run):
			dispatchers.dispatch_ai_agent(self.instance, self.task, base, self.bpmn_id)
		return captured["config"]

	def test_a_shape_that_sets_no_timeout_gets_the_shared_default(self):
		"""The regression. This asserted 30 for the whole time the bug existed —
		which is why it is written against the resolved config, not the constant."""
		self.assertEqual(self._resolved({}).timeout_seconds, DEFAULT_TIMEOUT_SECONDS)

	def test_the_default_is_long_enough_to_draft_a_document(self):
		"""58s measured for a real Policy draft. A limit under that publishes
		nothing and calls it success."""
		self.assertGreaterEqual(DEFAULT_TIMEOUT_SECONDS, 120)

	def test_a_shape_can_still_set_its_own_timeout(self):
		"""Configuration must keep winning — the point is the fallback, not a
		fixed value."""
		self.assertEqual(self._resolved({"aiTimeout": "45"}).timeout_seconds, 45)

	def test_a_blank_timeout_falls_through_rather_than_becoming_zero(self):
		"""A shape attribute arrives as a string, and "" must not mean "no time
		at all" — which is what int("" or 30) narrowly avoided and cint() makes
		explicit."""
		for blank in ("", "   ", None):
			with self.subTest(value=blank):
				self.assertEqual(
					self._resolved({"aiTimeout": blank}).timeout_seconds,
					DEFAULT_TIMEOUT_SECONDS,
				)

	def test_junk_falls_through_instead_of_raising(self):
		"""int() would raise here and take the whole task down with it."""
		self.assertEqual(
			self._resolved({"aiTimeout": "abc"}).timeout_seconds, DEFAULT_TIMEOUT_SECONDS
		)

	def test_the_dispatcher_does_not_carry_its_own_copy_of_the_number(self):
		"""The shape of the original bug: two places holding the same default,
		one of them silently authoritative."""
		import inspect

		from one_bpmn.one_bpmn.doctype.bpmn_process_instance import dispatchers

		src = inspect.getsource(dispatchers.dispatch_ai_agent)
		line = next(l for l in src.splitlines() if "timeout_seconds" in l)
		self.assertIn("DEFAULT_TIMEOUT_SECONDS", line)
		self.assertNotRegex(line, r"aiTimeout\"?,\s*\d+")


class TestDraftingFailureCannotPublish(FrappeTestCase):
	"""A failed draft must stop the process, not flow into publish.

	The dispatcher has always supported this via ``aiStopOnError``; the Document
	Request map simply never set it, so a timeout wrote its error into task data
	and the flow carried on through save-to-Drive, index and publish. The result
	was a Published Policy, issued a code and a version, with nothing in it.
	"""

	MODEL = "Document Request"

	def _draft_task_attrs(self):
		xml = frappe.db.get_value("BPMN Process Model", self.MODEL, "bpmn_xml") or ""
		match = re.search(r'<bpmn:serviceTask id="draft_task"[^>]*>', xml)
		self.assertIsNotNone(match, "the map must still have a drafting task")
		return dict(re.findall(r'spiffworkflow:(\w+)="([^"]*)"', match.group(0)))

	def test_the_drafting_task_halts_on_error(self):
		attrs = self._draft_task_attrs()
		self.assertEqual(
			(attrs.get("aiStopOnError") or "").lower(),
			"true",
			"without this a drafting failure publishes an empty document",
		)

	def test_the_drafting_task_declares_where_its_output_goes(self):
		"""The downstream steps read this name; if it drifts they silently see
		nothing, which is the same failure by another route.

		It is ``document_sections`` rather than the old ``document_markdown``
		because the task no longer returns a formatted document. It returns named
		bilingual fields, and the branded template is filled from them — asking a
		model to reproduce a bilingual Google Docs table as markdown produced pipe
		characters in published Policies."""
		self.assertEqual(self._draft_task_attrs().get("aiOutputVariable"), "document_sections")

	def test_the_drafting_task_returns_json_not_prose(self):
		"""The fill reads named fields off this output. Under "text" it would get
		a string, and every field would be missing."""
		self.assertEqual(self._draft_task_attrs().get("aiResponseFormat"), "json")
