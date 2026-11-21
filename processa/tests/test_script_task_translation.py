# Copyright (c) 2026, one-fm and contributors
"""Script tasks, agent tools and Run this check get _ for translations, like any other Server Script."""

from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_security.code_checks.script_validator import undefined_name_findings
from processa.ai_agent_skills.tools import shape_tools
from processa.api.server_scripts import run_logix_test_case
from processa.processa_engine.engine import _make_script_engine

SCRIPT = "Translation Test Greeting"
BODY = (
	'result["greeting"] = _("Hello")\n'
	'if task_data.get("holiday"):\n'
	'\tfrappe.throw(_("Overtime is not allowed on a public holiday"))\n'
)


class TestScriptTaskTranslation(FrappeTestCase):
	def setUp(self):
		super().setUp()
		if frappe.db.exists("Server Script", SCRIPT):
			frappe.delete_doc("Server Script", SCRIPT, force=True)
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": SCRIPT,
				"script_type": "API",
				"api_method": "translation_test_greeting",
				"script": BODY,
			}
		).insert()

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _run_task(self, data):
		engine = _make_script_engine(script_task_extensions={"t": {"serverScript": SCRIPT}}, instance=None)
		task = SimpleNamespace(data=data, task_spec=SimpleNamespace(bpmn_id="t", name="t"))
		engine._run_frappe_server_script(SCRIPT, task)
		return task.data

	def test_a_script_task_returns_translated_text(self):
		self.assertEqual(self._run_task({})["greeting"], "Hello")

	def test_a_throw_with_translated_text_shows_the_text(self):
		with self.assertRaises(frappe.ValidationError) as caught:
			self._run_task({"holiday": 1})
		self.assertIn("Overtime is not allowed on a public holiday", str(caught.exception))

	def test_an_agent_tool_returns_translated_text(self):
		task = shape_tools._synthetic_task("t", {})
		shape_tools._run_server_script(
			frappe._dict(context_doctype="", context_docname=""), SCRIPT, task, "t"
		)
		self.assertEqual(task.data["greeting"], "Hello")

	def test_run_this_check_returns_translated_text(self):
		result = run_logix_test_case(SCRIPT, "{}")
		self.assertTrue(result["passed"], result)
		self.assertEqual(result["result"]["greeting"], "Hello")

	def test_logix_does_not_report_underscore_as_undefined(self):
		self.assertEqual(undefined_name_findings(BODY), [])
