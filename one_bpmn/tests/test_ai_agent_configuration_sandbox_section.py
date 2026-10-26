# Copyright (c) 2026, one-fm and contributors
"""The sandbox checkboxes sit in their own open Sandbox section, not inside the collapsed A2A guardrails."""

from __future__ import annotations

import json
import os

import frappe
from frappe.tests.utils import FrappeTestCase

SETTINGS = ("sandbox_use_job", "sandbox_retry_on_test_failure", "require_reproduction")


def _doctype() -> dict:
	path = os.path.join(
		frappe.get_app_path("one_bpmn"),
		"one_bpmn",
		"doctype",
		"ai_agent_configuration",
		"ai_agent_configuration.json",
	)
	with open(path, encoding="utf-8") as handle:
		return json.load(handle)


class TestSandboxSection(FrappeTestCase):
	def test_the_section_is_open_and_holds_the_three_settings(self):
		doctype = _doctype()
		fields = {f["fieldname"]: f for f in doctype["fields"]}
		order = doctype["field_order"]
		section = fields["section_sandbox"]
		self.assertEqual((section["fieldtype"], section["label"]), ("Section Break", "Sandbox"))
		self.assertFalse(section.get("collapsible"))
		start = order.index("section_sandbox")
		end = order.index("evaluation_section")
		self.assertTrue(set(SETTINGS) <= set(order[start:end]))

	def test_none_of_them_is_left_inside_the_collapsed_guardrails_section(self):
		order = _doctype()["field_order"]
		guardrails = order[order.index("section_guardrails") : order.index("section_sandbox")]
		self.assertEqual([name for name in SETTINGS if name in guardrails], [])

	def test_the_local_meta_agrees(self):
		names = [f.fieldname for f in frappe.get_meta("AI Agent Configuration").fields]
		start = names.index("section_sandbox")
		self.assertTrue(set(SETTINGS) <= set(names[start : start + 6]))
