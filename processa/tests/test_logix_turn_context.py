# Copyright (c) 2026, one-fm and contributors
# The Logix turn context carries the linked script and the map's libraries, and no JSON reply contract:
# the orchestrator answers through its finalize tool.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api.server_scripts import build_logix_turn_context

CONTRACT_MARKER = "LOGIX REPLY CONTRACT"


class TestLogixTurnContext(FrappeTestCase):
	def test_no_reply_contract_without_linked_script(self):
		out = build_logix_turn_context({})
		self.assertNotIn(CONTRACT_MARKER, out.get("dialog_context", ""))
		self.assertNotIn("original_script_content", out)

	def test_a_missing_linked_script_is_cleared(self):
		out = build_logix_turn_context({"current_script": "No Such Script"})
		self.assertEqual(out["current_script"], "")
		self.assertNotIn("CURRENT SERVER SCRIPT", out["dialog_context"])

	def test_existing_dialog_context_is_preserved(self):
		out = build_logix_turn_context({"dialog_context": "PRIOR CONTEXT"})
		self.assertEqual(out["dialog_context"], "PRIOR CONTEXT")

	def test_linked_script_content_rides_without_the_contract(self):
		script = frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": "Logix Turn Context Fixture",
				"script_type": "API",
				"api_method": "logix_turn_context_fixture",
				"script": "frappe.flags.logix_fixture = 1",
			}
		).insert(ignore_if_duplicate=True)
		out = build_logix_turn_context({"current_script": script.name})
		self.assertEqual(out["original_script_content"], script.script)
		self.assertIn("CURRENT SERVER SCRIPT", out["dialog_context"])
		self.assertNotIn(CONTRACT_MARKER, out["dialog_context"])


LIBRARY = "P: Lib Replies"
STEP = "Logix Library Test Finalize"
MODEL = "Logix Library Test Map"
READER = "logix-library-reader@example.com"


class TestLogixLibraryScripts(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._script(LIBRARY, "def strip_fences(text):\n\treturn text.strip('`')\n")
		self._script(STEP, "result['ok'] = 1")
		self._model(
			'<bpmn:scriptTask id="lib" name="Lib" spiffworkflow:serverScript="P: Lib Replies" />'
			'<bpmn:scriptTask id="t" name="Finalize" spiffworkflow:serverScript="Logix Library Test Finalize">'
			"<bpmn:incoming>f1</bpmn:incoming></bpmn:scriptTask>"
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		super().tearDown()

	def _script(self, name, body):
		if frappe.db.exists("Server Script", name):
			frappe.db.set_value("Server Script", name, "script", body)
			return
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": name,
				"script_type": "API",
				"api_method": frappe.scrub(name),
				"script": body,
			}
		).insert()

	def _model(self, shapes):
		if frappe.db.exists("BPMN Process Model", MODEL):
			frappe.delete_doc("BPMN Process Model", MODEL, force=1)
		model = frappe.new_doc("BPMN Process Model")
		model.update({"name": MODEL, "title": MODEL, "process_id": "logix_library_test", "version": 1})
		model.bpmn_xml = (
			'<?xml version="1.0" encoding="UTF-8"?>'
			'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
			'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core">'
			f'<bpmn:process id="logix_library_test" isExecutable="true">{shapes}</bpmn:process></bpmn:definitions>'
		)
		model.insert()

	def _turn(self):
		return build_logix_turn_context({"current_script": STEP, "process_context": {"process_model": MODEL}})

	def test_a_library_on_the_map_reaches_the_context_and_the_text(self):
		out = self._turn()
		self.assertEqual(out["library_scripts"], [{"name": LIBRARY, "functions": ["strip_fences(text)"]}])
		self.assertIn("LIBRARY SCRIPTS ON THIS MAP", out["dialog_context"])
		self.assertIn(f"- {LIBRARY}: strip_fences(text)", out["dialog_context"])

	def test_a_map_with_no_library_has_no_library_section(self):
		self._model(
			'<bpmn:scriptTask id="t" name="Finalize" spiffworkflow:serverScript="Logix Library Test Finalize" />'
		)
		self._script(STEP, "result['ok'] = 1")
		out = build_logix_turn_context({"process_context": {"process_model": MODEL}})
		self.assertNotIn("library_scripts", out)
		self.assertNotIn("LIBRARY SCRIPTS ON THIS MAP", out["dialog_context"])

	def test_a_library_the_user_cannot_read_is_left_out(self):
		if not frappe.db.exists("User", READER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": READER,
					"first_name": "Reader",
					"send_welcome_email": 0,
					"roles": [{"role": "Blogger"}],
				}
			).insert()
		frappe.set_user(READER)
		out = build_logix_turn_context({"process_context": {"process_model": MODEL}})
		self.assertNotIn("library_scripts", out)

	def test_a_library_with_a_syntax_error_is_listed_with_no_functions(self):
		self._script(LIBRARY, "def strip_fences(text:\n")
		out = self._turn()
		self.assertEqual(out["library_scripts"], [{"name": LIBRARY, "functions": []}])
		self.assertIn(f"- {LIBRARY}: no functions could be read", out["dialog_context"])

	def test_a_turn_without_a_map_has_no_library_section(self):
		self.assertNotIn("library_scripts", build_logix_turn_context({"current_script": STEP}))
