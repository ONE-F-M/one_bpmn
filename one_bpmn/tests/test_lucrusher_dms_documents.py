# Copyright (c) 2026, one-fm and contributors
"""LuCrusher reads the Document Register through its search_dms_documents tool.

Run with:
    bench run-tests --app one_bpmn --module one_bpmn.tests.test_lucrusher_dms_documents
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.ai_agent_registry.definitions.shared.tools_dms import search_dms_documents
from one_bpmn.one_bpmn.patches.v1_0 import lucrusher_reads_dms_documents as patch

MAP_XML = """<bpmn:process id="p">
    <bpmn:adHocSubProcess id="lucrusher_tools" name="Tools">
      <bpmn:scriptTask id="finalize" name="finalize" />
      <bpmn:completionCondition xsi:type="bpmn:tFormalExpression">True</bpmn:completionCondition>
    </bpmn:adHocSubProcess>
  </bpmn:process>
  <bpmndi:BPMNPlane id="plane">
  </bpmndi:BPMNPlane>"""


class TestLucrusherDmsPatch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def make_config(self):
		frappe.db.delete("AI Agent Configuration", {"agent_id": patch.AGENT_ID})
		return frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_id": patch.AGENT_ID,
				"agent_name": "ZZ LuCrusher",
				"chat_mode_label": "ZZ LuCrusher",
				"agent_type": "Chat",
				"agent_framework": "Direct API",
				"lifecycle_status": "Live",
				"enabled": 1,
				"system_prompt": "You are LuCrusher.",
			}
		).insert(ignore_permissions=True)

	def test_splice_adds_the_shape_to_the_tools_sub_process_and_canvas(self):
		xml = patch.splice_shape(MAP_XML)

		self.assertIn('<bpmn:scriptTask id="search_dms_documents"', xml)
		self.assertIn('bpmnElement="search_dms_documents"', xml)
		self.assertLess(xml.index('id="search_dms_documents"'), xml.index("<bpmn:completionCondition"))

	def test_splice_twice_changes_nothing(self):
		once = patch.splice_shape(MAP_XML)

		self.assertEqual(patch.splice_shape(once), once)

	def test_splice_refuses_a_map_without_the_tools_sub_process(self):
		self.assertIsNone(patch.splice_shape(MAP_XML.replace("lucrusher_tools", "other_tools")))

	def test_prompt_gets_the_dms_rules_once(self):
		config = self.make_config()

		patch.append_prompt()
		patch.append_prompt()

		prompt = frappe.db.get_value("AI Agent Configuration", config.name, "system_prompt")
		self.assertEqual(prompt.count(patch.MARKER), 1)
		self.assertIn("Policy, SOP, Manual, Guideline, Knowledge Base", prompt)

	def test_tool_script_calls_the_search_as_the_chatting_user(self):
		patch._ensure_script(patch.SCRIPT_NAME, patch.API_METHOD, patch.SCRIPT)

		script = frappe.db.get_value("Server Script", patch.SCRIPT_NAME, "script")

		self.assertIn("search_dms_documents(task_data.get", script)
		self.assertIn("instance=instance", script)

	def test_search_refuses_a_chatting_user_without_read_permission(self):
		conversation = frappe.get_doc({"doctype": "Chat Conversation"}).insert(ignore_permissions=True)
		frappe.db.set_value("Chat Conversation", conversation.name, "owner", "Guest")
		instance = frappe._dict(context_doctype="Chat Conversation", context_docname=conversation.name)

		with self.assertRaises(frappe.PermissionError):
			search_dms_documents("annual leave entitlement", instance=instance)
