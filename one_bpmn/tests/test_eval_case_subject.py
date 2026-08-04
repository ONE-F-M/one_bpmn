# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Tests for the document under test on a map-driven eval case.

Two failures kept happening because the case editor exposed only a prompt:

  * a hand-made case on a map-driven suite had no way to name a document, so
    every run died with "must name the document to run against";
  * a case captured from a run kept its ORIGINAL document, so editing the prompt
    to reference another record silently changed nothing — the map renders its own
    prompt against the document, and the case's prompt is never sent.

The document is therefore a first-class field on create/update/read, and a
map-driven case without one is refused at SAVE time rather than at run time.
"""
from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_agent_configuration, make_eval_suite
from one_bpmn.api.eval_api import create_eval_case, get_eval_case, update_eval_case

test_ignore = ["BPMN Process Instance", "AI Eval Suite"]

RECORD_TRIGGERED_XML = (
	'<bpmn:definitions><bpmn:process id="p"><bpmn:startEvent id="s">'
	'<bpmn:conditionalEventDefinition spiffworkflow:triggerDoctype="Leave Application" '
	'spiffworkflow:triggerType="After Insert" />'
	"</bpmn:startEvent></bpmn:process></bpmn:definitions>"
)


class TestEvalCaseSubject(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.map_name = self._map()
		# Background agent + Agent suite => the case takes the map path.
		self.agent = make_agent_configuration(agent_type="Background", chat_mode_label=None)
		self.suite = make_eval_suite(
			agent_configuration=self.agent.name,
			eval_type="Agent",
			process_model=self.map_name,
		)
		self.todo = self._todo()

	def _map(self):
		doc = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"title": f"_Test Subject Map {frappe.generate_hash(length=8)}",
			"process_id": f"_test_subject_{frappe.generate_hash(length=6)}",
			"version": 1,
			"bpmn_xml": RECORD_TRIGGERED_XML,
		})
		doc.flags.ignore_mandatory = True
		doc.flags.ignore_links = True
		return doc.insert(ignore_permissions=True).name

	def _todo(self):
		return frappe.get_doc({
			"doctype": "ToDo",
			"description": "_Test subject doc",
			"allocated_to": frappe.session.user,
		}).insert(ignore_permissions=True)

	# ── create ────────────────────────────────────────────────────────────
	def test_map_driven_case_without_a_document_is_refused_at_save(self):
		"""The failure the user hit: the run died with a traceback. It is a form
		error now, before any tokens are spent."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			create_eval_case(
				suite=self.suite.name,
				title="Fetch Leave Details",
				input_user_prompt="The Leave application is HR-LAP-2026-00342, fetch it.",
			)
		self.assertIn("Document under test", str(ctx.exception))

	def test_document_is_stored_as_input_context(self):
		name = create_eval_case(
			suite=self.suite.name,
			title="With a document",
			input_user_prompt="Summarise it.",
			context_doctype="ToDo",
			context_docname=self.todo.name,
		)
		stored = frappe.parse_json(frappe.db.get_value("AI Eval Case", name, "input_context"))
		self.assertEqual(
			stored, {"context_doctype": "ToDo", "context_docname": self.todo.name}
		)

	def test_unknown_document_is_rejected(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			create_eval_case(
				suite=self.suite.name, title="Bad doc", input_user_prompt="x",
				context_doctype="ToDo", context_docname="no-such-todo",
			)
		self.assertIn("No ToDo named", str(ctx.exception))

	def test_direct_suite_needs_no_document(self):
		"""A Direct suite never runs the map, so the prompt IS the test."""
		suite = make_eval_suite(
			agent_configuration=make_agent_configuration().name,
			eval_type="Direct",
			process_model=self.map_name,
		)
		name = create_eval_case(
			suite=suite.name, title="Direct case", input_user_prompt="Say hello.",
		)
		self.assertTrue(frappe.db.exists("AI Eval Case", name))

	# ── read / update ─────────────────────────────────────────────────────
	def test_document_round_trips_through_get_eval_case(self):
		name = create_eval_case(
			suite=self.suite.name, title="Round trip", input_user_prompt="x",
			context_doctype="ToDo", context_docname=self.todo.name,
		)
		got = get_eval_case(name)
		self.assertTrue(got["runs_map"])
		self.assertEqual(got["context_doctype"], "ToDo")
		self.assertEqual(got["context_docname"], self.todo.name)
		self.assertEqual(got["context_source"], "case")

	def test_updating_the_document_repoints_the_case(self):
		"""Re-pointing a case is an edit to the DOCUMENT, not to the prompt."""
		other = self._todo()
		name = create_eval_case(
			suite=self.suite.name, title="Repoint me", input_user_prompt="x",
			context_doctype="ToDo", context_docname=self.todo.name,
		)
		update_eval_case(name, context_doctype="ToDo", context_docname=other.name)
		self.assertEqual(get_eval_case(name)["context_docname"], other.name)

	def test_clearing_the_document_on_a_map_case_is_refused(self):
		name = create_eval_case(
			suite=self.suite.name, title="Do not strand me", input_user_prompt="x",
			context_doctype="ToDo", context_docname=self.todo.name,
		)
		with self.assertRaises(frappe.ValidationError):
			update_eval_case(name, context_doctype="", context_docname="")
		# The original document survives the refused edit.
		self.assertEqual(get_eval_case(name)["context_docname"], self.todo.name)
