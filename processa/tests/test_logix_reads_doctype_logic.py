# Copyright (c) 2026, one-fm and contributors
"""Logix reads the controller logic of a DocType and shows it to the script writer."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_skills.tools import shape_tools
from processa.patches.v1_0 import logix_reads_doctype_logic as p
from processa.patches.v1_0.add_assistant_eval_authoring_tools import _ensure_script
from processa.patches.v1_0.approve_live_script_tasks import approve

CONVERSATION = "logix-doctype-logic-test"
PROCESS = "Logix Doctype Logic Test"
MAP = (
	'<bpmn:definitions><bpmn:process id="p"><bpmn:adHocSubProcess id="logix_tools">'
	'<bpmn:serviceTask id="write_agent_tool" spiffworkflow:aiUserPrompt="{% if turn.violations %}fix{% endif %}">'
	"</bpmn:serviceTask>"
	'<bpmn:serviceTask id="write_script" spiffworkflow:aiUserPrompt="**Shape kind:** x&#10;'
	'{% if turn.violations %}fix{% endif %}"></bpmn:serviceTask>'
	"<bpmn:completionCondition>done</bpmn:completionCondition></bpmn:adHocSubProcess></bpmn:process>"
	'<bpmndi:BPMNDiagram><bpmndi:BPMNPlane bpmnElement="p"></bpmndi:BPMNPlane></bpmndi:BPMNDiagram>'
	"</bpmn:definitions>"
)


class TestLogixReadsDoctypeLogic(FrappeTestCase):
	def setUp(self):
		super().setUp()
		_ensure_script(p.SCRIPT_NAME, p.API_METHOD, p.SCRIPT)
		if not frappe.db.exists("Process", PROCESS):
			frappe.get_doc(
				{
					"doctype": "Process",
					"process_name": PROCESS,
					"description": PROCESS,
					"process_owner": "Administrator",
				}
			).insert()

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _call(self, doctypes):
		task = shape_tools._synthetic_task(p.SHAPE_ID, {"doctypes": doctypes})
		instance = frappe._dict(context_doctype="Chat Conversation", context_docname=CONVERSATION)
		with patch("processa.processa_engine.engine.script_engine.process_of", return_value=PROCESS):
			shape_tools._run_server_script(instance, p.SCRIPT_NAME, task, p.SHAPE_ID)
		return task.data["doctype_logic"]

	def _approve(self):
		approve(PROCESS, p.SHAPE_ID, p.SHAPE_ID, p.SCRIPT_NAME)

	def test_the_tool_sits_in_the_tools_sub_process_and_the_writer_sees_what_it_read(self):
		xml = p._splice(MAP)
		tools = xml[
			xml.index('<bpmn:adHocSubProcess id="logix_tools"') : xml.index("</bpmn:adHocSubProcess>")
		]
		self.assertIn(f'<bpmn:scriptTask id="{p.SHAPE_ID}"', tools)
		self.assertIn(f'bpmnElement="{p.SHAPE_ID}"', xml)
		self.assertIn("{% if turn.doctype_logic %}", xml[xml.index('id="write_script"') :])
		self.assertEqual(xml.count("{% if turn.doctype_logic %}"), 1)

	def test_splicing_twice_adds_the_tool_once(self):
		self.assertEqual(p._splice(p._splice(MAP)), p._splice(MAP))

	def test_the_writer_gets_the_controller_method_that_already_holds_the_rule(self):
		if not frappe.db.exists("DocType", "Overtime Request"):
			self.skipTest("one_fm is not installed")
		self._approve()
		with patch("processa.processa_engine.agent_runtime.turn_state.update_turn") as kept:
			(logic,) = self._call(["Overtime Request"])
		self.assertEqual(logic["status"], "read")
		self.assertIn("validate_compensatory_day_off", [m["name"] for m in logic["methods"]])
		kept.assert_called_once_with(CONVERSATION, doctype_logic=[logic])

	def test_an_unknown_doctype_is_reported_not_raised(self):
		self._approve()
		(logic,) = self._call(["No Such DocType For Logix"])
		self.assertEqual(logic["status"], "unknown_doctype")

	def test_without_the_approval_the_gate_refuses_the_import(self):
		with self.assertRaisesRegex(frappe.ValidationError, "needs approval"):
			self._call(["Overtime Request"])
