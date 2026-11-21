# Copyright (c) 2026, one-fm and contributors
"""Logix tries a draft on a record, reads the newest error of a script, and shows the real error of a check."""

import ast
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.logix import dry_run as trial
from processa.ai_agent_registry.definitions.logix import tools
from processa.ai_agent_registry.definitions.logix.helpers import debug_inputs
from processa.api.server_scripts import run_logix_test_case
from processa.patches.v1_0 import logix_tries_drafts_on_a_record as p

MODEL = frappe._dict(name="Trial Model", trigger_doctype="Note", bpmn_xml="")
TURN = {"process_context": {"process_name": "trial", "element_id": "t"}}
SCRIPT = "Trial Attendance Script"


class TestLogixTriesDrafts(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.note = frappe.get_doc({"doctype": "Note", "title": "trial sample"}).insert()

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _try(self, code):
		with patch.object(trial, "_process_model", return_value=MODEL):
			return trial.dry_run(code, TURN)

	def test_a_failing_draft_returns_its_traceback_and_failing_line(self):
		outcome = self._try('x = 1\nresult["date"] = doc.appointment_date.year\n')
		self.assertEqual(
			(outcome["line"], outcome["code"]), (2, 'result["date"] = doc.appointment_date.year')
		)
		self.assertIn("AttributeError", outcome["error"])
		self.assertIn("It failed on Note", outcome["summary"])

	def test_a_working_draft_is_described_and_undone(self):
		count = frappe.db.count("Note")
		outcome = self._try(
			'frappe.get_doc({"doctype": "Note", "title": doc.title + " copy"}).insert()\n'
			'frappe.sendmail(recipients=["a@example.com"], subject="s", message="m")\n'
			'result["seen"] = doc.name\n'
		)
		self.assertNotIn("error", outcome)
		self.assertEqual(outcome["record"], f"Note {self.note.name}")
		self.assertTrue(any(w.startswith("insert Note") for w in outcome["writes"]), outcome["writes"])
		self.assertEqual(outcome["stubbed"], ["sendmail"])
		self.assertEqual(outcome["result"], {"seen": self.note.name})
		self.assertIn("Not executed in the trial: sendmail", outcome["summary"])
		self.assertEqual(frappe.db.count("Note"), count)

	def test_a_throw_is_reported_as_a_stop_not_a_failure(self):
		outcome = self._try('frappe.throw("Date and Time Confirmation is missing")\n')
		self.assertNotIn("error", outcome)
		self.assertIn("Date and Time Confirmation is missing", outcome["summary"])

	def test_it_runs_as_the_person_who_asked(self):
		frappe.flags.requesting_user = "Guest"
		self.addCleanup(frappe.flags.pop, "requesting_user", None)
		outcome = self._try('result["user"] = frappe.session.user\n')
		self.assertEqual(outcome["result"], {"user": "Guest"})
		self.assertEqual(frappe.session.user, "Administrator")

	def test_a_draft_the_gate_refuses_is_not_run(self):
		outcome = self._try("import os\nos.remove('x')\n")
		self.assertFalse(outcome["ran"])

	def test_with_no_record_to_try_it_is_not_run(self):
		with patch.object(trial, "_process_model", return_value=None):
			self.assertFalse(trial.dry_run('result["x"] = 1', TURN)["ran"])

	def test_the_review_script_edits_land_once_and_still_parse(self):
		code = frappe.db.get_value("Server Script", p.REVIEW_SCRIPT, "script")
		if not code:
			self.skipTest("the Logix review script is not on this site")
		for pattern, new in p.EDITS:
			self.assertEqual(len(pattern.findall(code)), 1)
			code = pattern.sub(new, code, count=1)
		ast.parse(code)
		self.assertIn("dry_run(code, turn)", code)


class TestLogixReadsTheNewestError(FrappeTestCase):
	def setUp(self):
		super().setUp()
		if frappe.db.exists("Server Script", SCRIPT):
			frappe.delete_doc("Server Script", SCRIPT, force=True)
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": SCRIPT,
				"script_type": "API",
				"api_method": "trial_attendance_script",
				"script": 'result["saved"] = 1',
			}
		).insert()

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_debug_reads_the_saved_script_and_the_newest_error_from_any_path(self):
		frappe.log_error(
			title=f'BPMN ScriptTask: "{SCRIPT}" execution failed', message="old appointment_date error"
		)
		frappe.log_error(
			title="BPMN runtime failure [X]",
			message=f'File "<serverscript>: {frappe.scrub(SCRIPT)}", line 51\nAttributeError: commit',
		)
		inputs = debug_inputs("still not creating attendance", 'result["editor"] = 1', SCRIPT)
		self.assertEqual(inputs["script_text"], 'result["saved"] = 1')
		self.assertIn("line 51", inputs["last_error"])
		self.assertIn("the script was last saved", inputs["last_error"])

	def test_a_fix_that_only_changes_spacing_is_not_offered(self):
		self.assertEqual(tools._code_lines("a = 1\n\nb = 2"), tools._code_lines("a = 1  \nb = 2\n"))
		self.assertNotEqual(tools._code_lines("a = 1"), tools._code_lines("a = 2"))

	def test_a_failing_check_shows_the_real_error_and_logs_it(self):
		frappe.db.set_value("Server Script", SCRIPT, "script", 'result["x"] = doc.appointment_date.year')
		outcome = run_logix_test_case(SCRIPT, "{}")
		self.assertIn("AttributeError", outcome["summary"])
		self.assertTrue(frappe.db.exists("Error Log", {"method": f'Logix check: "{SCRIPT}" failed'}))
