# Copyright (c) 2026, one-fm and contributors
"""
Integration tests for the BPMN Script-Task security ENFORCEMENT gates
(``processa.ai_agent_security.code_checks.script_gate``).

Covers the three pre-deployment gates:
  * process-model authoring / deploy → validate_process_model_scripts
  * Server Script save               → validate_server_script_on_save
  * BPMN linkage scoping             → is_bpmn_linked_server_script

Requires a Frappe bench (DB). Run with:
  bench --site <site> run-tests --app processa --module \
    processa.ai_agent_security.tests.test_script_security_gate
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_security.code_checks import script_gate
from processa.ai_agent_security.code_checks.script_categories import clear_category_cache
from processa.ai_agent_skills.tools import shape_tools
from processa.api.server_scripts import run_logix_test_case
from processa.patches.v1_0 import seed_script_import_categories
from processa.processa_engine.engine import _make_script_engine, evaluate_condition
from processa.processa_engine.maps.readiness import check_readiness


def _bpmn_with_inline(script_body: str, task_id: str = "Task_1") -> str:
	"""Minimal BPMN diagram carrying a single inline <bpmn:script> task."""
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
		'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core">'
		'<bpmn:process id="Process_1" isExecutable="true">'
		f'<bpmn:scriptTask id="{task_id}">'
		f'<bpmn:script>{script_body}</bpmn:script>'
		'</bpmn:scriptTask>'
		'</bpmn:process></bpmn:definitions>'
	)


def _bpmn_with_server_script(script_name: str, task_id: str = "Task_1") -> str:
	"""Minimal BPMN diagram whose script task references a Server Script."""
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
		'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core">'
		'<bpmn:process id="Process_1" isExecutable="true">'
		f'<bpmn:scriptTask id="{task_id}" spiffworkflow:serverScript="{script_name}">'
		'<bpmn:script>pass</bpmn:script>'
		'</bpmn:scriptTask>'
		'</bpmn:process></bpmn:definitions>'
	)


class TestProcessModelScriptGate(FrappeTestCase):
	def test_safe_inline_passes(self):
		xml = _bpmn_with_inline("doc = frappe.get_doc('User', 'Administrator')")
		# Should not raise.
		script_gate.validate_process_model_scripts(xml)

	def test_unsafe_inline_raises(self):
		xml = _bpmn_with_inline("import os\nos.system('id')")
		with self.assertRaises(frappe.ValidationError):
			script_gate.validate_process_model_scripts(xml)

	def test_kwargs_bypass_inline_raises(self):
		xml = _bpmn_with_inline("doc.save(ignore_permissions=True)")
		with self.assertRaises(frappe.ValidationError):
			script_gate.validate_process_model_scripts(xml)

	def test_unparseable_xml_is_noop(self):
		# Never raise on malformed XML — other validators own that.
		script_gate.validate_process_model_scripts("<not-bpmn>")

	def test_blocked_message_is_generic_summary(self):
		# The editor modal gets a concise summary (task label + issue count +
		# where to look), NOT a dump of every rule that tripped.
		xml = _bpmn_with_inline(
			"import os\nexec('x')\neval('y')\nopen('/etc/passwd')", task_id="Task_Bad"
		)
		with self.assertRaises(frappe.ValidationError) as ctx:
			script_gate.validate_process_model_scripts(xml)
		msg = str(ctx.exception)
		# Names the affected task and summarises with a count …
		self.assertIn("Task_Bad", msg)
		self.assertIn("security issue", msg)
		self.assertIn("Deployment Readiness", msg)
		# … but does not leak the specific per-rule blacklist text.
		self.assertNotIn("os needs approval", msg)
		self.assertNotIn("exec() needs approval", msg)


class TestServerScriptGate(FrappeTestCase):
	def _make_server_script(self, name: str, body: str):
		if frappe.db.exists("Server Script", name):
			frappe.delete_doc("Server Script", name, force=True)
		doc = frappe.get_doc({
			"doctype": "Server Script",
			"name": name,
			"script_type": "API",
			"api_method": name.replace(" ", "_").lower(),
			"script": body,
		})
		doc.flags.ignore_permissions = True
		return doc

	def test_unlinked_server_script_is_not_gated(self):
		# An unsafe body is allowed when NO BPMN model references the script.
		doc = self._make_server_script("ZZ Unlinked Script", "import os")
		# Gate is a no-op for unlinked scripts → insert must succeed.
		doc.insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Server Script", "ZZ Unlinked Script"))
		self.addCleanup(frappe.delete_doc, "Server Script", "ZZ Unlinked Script", force=True)

	def test_unlinked_name_is_not_flagged_as_linked(self):
		self.assertFalse(script_gate.is_bpmn_linked_server_script("Totally Unrelated Script"))
		self.assertFalse(script_gate.is_bpmn_linked_server_script(""))


PROCESS = "Gate Test Process"
SCRIPT = "Gate Test Fetch Rates"
TASK = "Activity_fetch"
MODEL = "Gate Test Map"


class _FakeTaskSpec:
	bpmn_id = TASK
	name = TASK


class _FakeTask:
	def __init__(self, data):
		self.data = data
		self.task_spec = _FakeTaskSpec()


class TestApprovalGates(FrappeTestCase):
	"""Saves pass; deploy and both run paths refuse a script task until its request is Approved."""

	def setUp(self):
		super().setUp()
		clear_category_cache()
		seed_script_import_categories.execute()
		if not frappe.db.exists("Process", PROCESS):
			frappe.get_doc(
				{"doctype": "Process", "process_name": PROCESS, "description": PROCESS, "process_owner": "Administrator"}
			).insert()
		if frappe.db.exists("BPMN Process Model", MODEL):
			frappe.delete_doc("BPMN Process Model", MODEL, force=1)
		model = frappe.new_doc("BPMN Process Model")
		model.update({"name": MODEL, "title": MODEL, "process_id": "Process_1", "version": 1})
		model.bpmn_xml = _bpmn_with_server_script(SCRIPT, TASK)
		model.insert()
		frappe.db.set_value("BPMN Process Model", MODEL, "process_name", PROCESS)
		self._script("import requests\nresult['fetched'] = 1")
		self.instance = frappe._dict(process_model=MODEL, context_doctype="", context_docname="")

	def tearDown(self):
		frappe.db.rollback()
		clear_category_cache()
		super().tearDown()

	def _script(self, body):
		if frappe.db.exists("Server Script", SCRIPT):
			script = frappe.get_doc("Server Script", SCRIPT)
			script.script = body
			script.save()
			return
		frappe.get_doc(
			{"doctype": "Server Script", "name": SCRIPT, "script_type": "API", "api_method": "gate_test_fetch", "script": body}
		).insert()

	def _request(self, status=None):
		request = frappe.get_doc(
			{"doctype": "Script Approval Request", "process_name": PROCESS, "script_task": TASK, "server_script": SCRIPT}
		).insert()
		if status:
			request.db_set("status", status)
		return request

	def _run_task(self):
		engine = _make_script_engine(script_task_extensions={TASK: {"serverScript": SCRIPT}}, instance=self.instance)
		task = _FakeTask({})
		engine._run_frappe_server_script(SCRIPT, task)
		return task.data

	def test_a_linked_server_script_that_needs_approval_saves(self):
		self.assertTrue(script_gate.is_bpmn_linked_server_script(SCRIPT))
		self.assertIn("requests", frappe.db.get_value("Server Script", SCRIPT, "script"))

	def test_a_linked_server_script_with_a_syntax_error_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self._script("result['x'] = (")

	def test_a_map_with_a_flagged_script_task_saves(self):
		model = frappe.get_doc("BPMN Process Model", MODEL)
		model.bpmn_xml = _bpmn_with_inline("import requests", TASK)
		model.save()

	def test_a_map_with_a_syntax_error_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			script_gate.validate_process_model_syntax(_bpmn_with_inline("x = (", TASK))

	def test_readiness_lists_what_needs_approval_and_the_open_request(self):
		request = self._request()
		items = {
			item["name"]
			for category in check_readiness(_bpmn_with_server_script(SCRIPT, TASK), MODEL)["categories"]
			if category["label"] == "Script Security"
			for item in category["items"]
		}
		self.assertEqual(len(items), 1)
		(item,) = items
		for part in (TASK, "requests", "Network", "needs approval", request.name):
			self.assertIn(part, item)

	def test_deploy_is_refused_naming_each_flagged_task_and_passes_once_approved(self):
		xml = _bpmn_with_server_script(SCRIPT, TASK)
		with self.assertRaises(frappe.ValidationError) as caught:
			script_gate.validate_process_model_scripts(xml, PROCESS)
		self.assertIn(TASK, str(caught.exception))
		self._request("Approved")
		script_gate.validate_process_model_scripts(xml, PROCESS)

	def test_a_flagged_script_task_does_not_run(self):
		with self.assertRaises(frappe.ValidationError):
			self._run_task()
		self._request("Approved")
		self.assertEqual(self._run_task()["fetched"], 1)

	def test_a_flagged_agent_tool_does_not_run(self):
		task = shape_tools._synthetic_task(TASK, {})
		with self.assertRaises(frappe.ValidationError):
			shape_tools._run_server_script(self.instance, SCRIPT, task, TASK)
		self.assertNotIn("fetched", task.data)

	def test_a_condition_gets_the_default_categories_only(self):
		with self.assertRaises(frappe.ValidationError):
			evaluate_condition("frappe.db.sql('select 1')", {"frappe": frappe})  # validator input, not a query

	def test_run_this_check_refuses_a_flagged_script(self):
		result = run_logix_test_case(SCRIPT, "{}", PROCESS, TASK)
		self.assertFalse(result["passed"])
		self.assertIn("requests", result["summary"])
		self.assertIn("Network", result["summary"])

	def test_run_this_check_runs_an_approved_script(self):
		self._request("Approved")
		self.assertTrue(run_logix_test_case(SCRIPT, "{}", PROCESS, TASK)["passed"])

	def test_run_this_check_without_a_task_uses_the_default_categories(self):
		self._request("Approved")
		self.assertFalse(run_logix_test_case(SCRIPT, "{}")["passed"])

	def test_a_doctype_event_script_run_by_a_script_task_is_not_checked(self):
		event = frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": "Gate Test ToDo Event",
				"script_type": "DocType Event",
				"reference_doctype": "Note",
				"doctype_event": "After Save",
				"script": "frappe.db.set_value('Note', doc.name, 'content', 'set by event')",
			}
		)
		note = frappe.get_doc({"doctype": "Note", "title": "Gate test event", "content": "before"}).insert()
		frappe.flags.in_processa_script = True
		try:
			event.execute_doc(note)
		finally:
			frappe.flags.in_processa_script = False
		self.assertEqual(frappe.db.get_value("Note", note.name, "content"), "set by event")
