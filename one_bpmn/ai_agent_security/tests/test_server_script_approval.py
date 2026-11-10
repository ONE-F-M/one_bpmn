# Copyright (c) 2026, one-fm and contributors
"""System Manager approval of blocked modules and frappe calls in Server Scripts."""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.ai_agent_security.code_checks import script_gate
from one_bpmn.ai_agent_security.code_checks.script_validator import ValidatorOptions, deep_inspect_script
from one_bpmn.api.deploy import compile_process_model
from one_bpmn.api.server_scripts import create_server_script, toggle_server_script, update_server_script
from one_bpmn.processa_engine.engine import _make_script_engine, evaluate_condition

test_ignore = ["BPMN Process Model"]

SCRIPT_MANAGER = "zz-a26-script-manager@example.com"
USES_OS = "import os\nresult['sep'] = os.sep"


class _FakeTaskSpec:
	bpmn_id = "script_1"
	name = "script_1"


class _FakeTask:
	def __init__(self, data=None):
		self.data = data or {}
		self.task_spec = _FakeTaskSpec()


def _bpmn_with_server_script(script_name: str) -> str:
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
                  id="Defs_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:scriptTask id="Task_1" spiffworkflow:serverScript="{script_name}">
      <bpmn:script>pass</bpmn:script>
    </bpmn:scriptTask>
  </bpmn:process>
</bpmn:definitions>"""


class TestServerScriptApproval(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("User", SCRIPT_MANAGER):
			user = frappe.get_doc(
				{"doctype": "User", "email": SCRIPT_MANAGER, "first_name": "Script", "send_welcome_email": 0}
			)
			user.append("roles", {"role": "Script Manager"})
			user.insert(ignore_permissions=True)  # test fixture

	def _script(self, name: str, body: str, **fields):
		if frappe.db.exists("Server Script", name):
			frappe.delete_doc("Server Script", name, force=True)
		doc = frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": name,
				"script_type": "API",
				"api_method": frappe.scrub(name),
				"script": body,
				**fields,
			}
		).insert(ignore_permissions=True)  # test fixture
		self.addCleanup(
			lambda: (
				frappe.db.exists("Server Script", name)
				and frappe.delete_doc("Server Script", name, force=True)
			)
		)
		return doc

	def _link_to_model(self, script_name: str):
		model = frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"title": script_name,
				"process_id": "Process_1",
				"bpmn_xml": _bpmn_with_server_script(script_name),
			}
		)
		model.flags.skip_editability_check = True
		model.flags.skip_script_security_check = True
		model.insert(ignore_permissions=True)  # test fixture
		self.addCleanup(frappe.delete_doc, "BPMN Process Model", model.name, force=True)

	def test_approved_script_listing_os_runs_import_os(self):
		doc = self._script("ZZ A26 Approved OS", USES_OS, processa_allowed_modules="os", processa_approved=1)
		self.assertEqual(doc.processa_approved_by, "Administrator")
		self.assertEqual(doc.processa_approved_hash, script_gate.script_hash(USES_OS))

		task = _FakeTask()
		_make_script_engine()._run_frappe_server_script(doc.name, task)
		self.assertEqual(task.data["sep"], "/")

	def test_unapproved_script_with_import_os_is_rejected_on_save_and_at_run(self):
		self._link_to_model("ZZ A26 Unapproved OS")
		with self.assertRaises(frappe.ValidationError):
			self._script("ZZ A26 Unapproved OS", USES_OS, processa_allowed_modules="os")

		doc = self._script("ZZ A26 Unlinked OS", USES_OS, processa_allowed_modules="os")
		with self.assertRaises(frappe.ValidationError):
			_make_script_engine()._run_frappe_server_script(doc.name, _FakeTask())

	def test_user_without_system_manager_cannot_set_allowed_modules(self):
		doc = self._script("ZZ A26 Plain", "result['x'] = 1")
		with self.set_user(SCRIPT_MANAGER):
			doc.reload()
			doc.processa_allowed_modules = "os"
			with self.assertRaises(frappe.PermissionError):
				doc.save()
			doc.reload()
			doc.processa_approved = 1
			with self.assertRaises(frappe.PermissionError):
				doc.save()

	def test_code_change_clears_approval_and_disables(self):
		doc = self._script("ZZ A26 Code Change", USES_OS, processa_allowed_modules="os", processa_approved=1)
		with self.set_user(SCRIPT_MANAGER):
			doc.reload()
			doc.script = USES_OS + "\nresult['y'] = 2"
			# A forged hash from the client must not keep the approval.
			doc.processa_approved_hash = script_gate.script_hash(doc.script)
			doc.save()
		doc.reload()
		self.assertEqual(doc.processa_approved, 0)
		self.assertIsNone(doc.processa_approved_by)
		self.assertIsNone(doc.processa_approved_hash)
		self.assertEqual(doc.disabled, 1)
		self.assertEqual(script_gate.approved_names(doc), frozenset())

	def test_agent_written_script_is_saved_disabled(self):
		name = "ZZ A26 Logix Tool"
		self.addCleanup(
			lambda: (
				frappe.db.exists("Server Script", name)
				and frappe.delete_doc("Server Script", name, force=True)
			)
		)
		create_server_script(name, "API", "result['x'] = 1")
		self.assertEqual(frappe.db.get_value("Server Script", name, "disabled"), 1)

		frappe.db.set_value("Server Script", name, "disabled", 0)
		update_server_script(name, "result['x'] = 2")
		self.assertEqual(frappe.db.get_value("Server Script", name, "disabled"), 1)

	def test_only_a_system_manager_enables_a_script(self):
		doc = self._script("ZZ A26 Toggle", "result['x'] = 1", disabled=1)
		with self.set_user(SCRIPT_MANAGER):
			with self.assertRaises(frappe.PermissionError):
				toggle_server_script(doc.name, 0)
			toggle_server_script(doc.name, 1)
		toggle_server_script(doc.name, 0)
		self.assertEqual(frappe.db.get_value("Server Script", doc.name, "disabled"), 0)

	def test_doc_event_script_called_from_a_script_task_can_import(self):
		event = frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": "ZZ A26 ToDo Event",
				"script_type": "DocType Event",
				"reference_doctype": "ToDo",
				"doctype_event": "Before Insert",
				"script": "import json\ndoc.description = json.dumps({'from': 'event'})",
			}
		).insert(ignore_permissions=True)  # test fixture
		self.addCleanup(frappe.delete_doc, "Server Script", event.name, force=True)
		task_script = self._script(
			"ZZ A26 Inserts ToDo",
			"todo = frappe.get_doc({'doctype': 'ToDo', 'description': 'x', 'allocated_to': 'Administrator'}).insert()\nresult['description'] = todo.description",
		)

		task = _FakeTask()
		engine = _make_script_engine(script_task_extensions={"script_1": {"serverScript": task_script.name}})
		engine.execute(task, "pass")
		self.assertEqual(task.data["description"], '{"from": "event"}')

		# Outside a map Frappe still runs it in safe_exec, where imports fail.
		with self.assertRaises(ImportError):
			frappe.get_doc({"doctype": "ToDo", "description": "x", "allocated_to": "Administrator"}).insert()

	def test_conditions_have_builtins_and_the_validator(self):
		self.assertTrue(evaluate_condition("bool(amount) and isinstance(amount, int)", {"amount": 3}))
		with self.assertRaises(frappe.ValidationError):
			evaluate_condition("__import__('os')", {})

		environment = _make_script_engine().environment
		self.assertTrue(environment.evaluate("bool(x)", {"x": 1}))
		with self.assertRaises(frappe.ValidationError):
			environment.evaluate("frappe.get_attr('frappe.utils.execute_in_shell')", {})

	def test_gated_frappe_calls_need_the_approved_list(self):
		options = ValidatorOptions()
		for code, entry in (
			("frappe.get_attr('a.b')", "frappe.get_attr"),
			("from frappe.utils import execute_in_shell", "frappe.utils.execute_in_shell"),
			("db = frappe.db\ndb.sql('select 1')", "frappe.db.sql"),
			("frappe.local.conf.get('x')", "frappe.local.conf"),
			("import frappe as f\nf.call('a.b')", "frappe.call"),
		):
			self.assertTrue(deep_inspect_script(code, options), code)
			self.assertEqual(deep_inspect_script(code, options, frozenset({entry})), [], code)

	def test_deploy_leaves_an_agent_written_script_disabled_until_a_system_manager_enables_it(self):
		name = "ZZ A26 Deploy Tool"
		self.addCleanup(
			lambda: (
				frappe.db.exists("Server Script", name)
				and frappe.delete_doc("Server Script", name, force=True)
			)
		)
		create_server_script(name, "API", "result['x'] = 1")
		self.assertEqual(frappe.db.get_value("Server Script", name, "processa_pending_review"), 1)
		model = frappe.new_doc("BPMN Process Model")
		model.title = "ZZ A26 Deploy Map"
		model.process_id = "zz_a26_deploy"
		model.bpmn_xml = _deployable_map(name)
		model.insert()
		self.addCleanup(frappe.delete_doc, "BPMN Process Model", model.name, force=True)

		warnings = compile_process_model(model.name).get("warnings", [])
		self.assertEqual(frappe.db.get_value("Server Script", name, "disabled"), 1)
		self.assertTrue(any(name in w["detail"] for w in warnings if w["label"] == "Script awaits review"))

		with self.set_user(SCRIPT_MANAGER):
			script = frappe.get_doc("Server Script", name)
			script.disabled = 0
			with self.assertRaises(frappe.PermissionError):
				script.save()
		toggle_server_script(name, 0)
		self.assertEqual(frappe.db.get_value("Server Script", name, "processa_pending_review"), 0)

		frappe.db.set_value("Server Script", name, "disabled", 1)
		warnings = compile_process_model(model.name).get("warnings", [])
		self.assertEqual(frappe.db.get_value("Server Script", name, "disabled"), 0)
		self.assertFalse([w for w in warnings if w["label"] == "Script awaits review"])


def _deployable_map(script_name: str) -> str:
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
                  id="Defs_zz_a26" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="zz_a26_deploy" isExecutable="true">
    <bpmn:startEvent id="s"><bpmn:outgoing>f1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t" />
    <bpmn:scriptTask id="t" name="Tool" spiffworkflow:serverScript="{script_name}">
      <bpmn:incoming>f1</bpmn:incoming><bpmn:outgoing>f2</bpmn:outgoing>
    </bpmn:scriptTask>
    <bpmn:sequenceFlow id="f2" sourceRef="t" targetRef="e" />
    <bpmn:endEvent id="e"><bpmn:incoming>f2</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""
