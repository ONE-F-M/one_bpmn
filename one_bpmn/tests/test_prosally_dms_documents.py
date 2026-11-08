# Copyright (c) 2026, one-fm and contributors
"""ProsAlly reads the Document Register through its search_dms_documents tool.

Run with:
    bench run-tests --app one_bpmn --module one_bpmn.tests.test_prosally_dms_documents
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers as helpers
from one_bpmn.agents.dms_search import DOCUMENT_TYPES
from one_bpmn.agents.turn_state import clear_turn, get_turn, set_turn
from one_bpmn.one_bpmn.patches.v1_0 import prosally_reads_dms_documents as dms_patch

LEAVE_TEXT = "annual leave requests above five days need director approval"
OVERTIME_TEXT = "overtime must be approved by the supervisor before the shift"
CONVERSATION = "zz-prosally-dms-test"
CFG = {
	"sub_prompts": {
		"process_generator": {"prompt": "GENERATOR"},
		"modifier": {"prompt": "MODIFIER"},
		"intent_classifier": {"prompt": "CLASSIFIER"},
	},
	"constants": {},
}
TOOLS_MAP = """<bpmn:process id="p">
    <bpmn:adHocSubProcess id="prosally_tools" name="Tools">
      <bpmn:scriptTask id="finalize" name="finalize" />
      <bpmn:completionCondition xsi:type="bpmn:tFormalExpression">True</bpmn:completionCondition>
    </bpmn:adHocSubProcess>
  </bpmn:process>
  <bpmndi:BPMNPlane id="plane">
  </bpmndi:BPMNPlane>"""


class TestProsallyDmsTool(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		set_turn(CONVERSATION, {"user_text": "draw the annual leave approval process"})
		self.policy = self.make_document("DMS-PA-POLICY", "Leave Policy", "Policy", LEAVE_TEXT, "POL-T1")
		self.sop = self.make_document("DMS-PA-SOP", "Overtime SOP", "SOP", OVERTIME_TEXT, "SOP-T1")

	def tearDown(self):
		frappe.set_user("Administrator")
		clear_turn(CONVERSATION)
		frappe.db.rollback()

	def make_document(self, drive_file_id, title, document_type, content, document_code=None):
		return frappe.get_doc(
			{
				"doctype": "Document Register",
				"document_code": document_code,
				"drive_file_id": drive_file_id,
				"title": title,
				"drive_file_link": f"https://drive.google.com/file/d/{drive_file_id}/view",
				"document_type": document_type,
				"lifecycle_state": "Active",
				"content": content,
			}
		).insert(ignore_permissions=True)

	def search(self, query, document_type=None):
		return helpers.search_dms_for_turn(CONVERSATION, query, document_type)

	def prompt(self, sub_id):
		return helpers.stage_system_prompt(CFG, sub_id, "", get_turn(CONVERSATION))

	def test_search_returns_the_matching_document_and_keeps_it_for_the_turn(self):
		found = self.search("annual leave approval")

		self.assertEqual([r["title"] for r in found["results"]], ["Leave Policy"])
		self.assertEqual(get_turn(CONVERSATION)["dms_documents"], found["results"])

	def test_a_second_search_adds_to_what_the_turn_holds(self):
		self.search("annual leave approval")
		self.search("overtime supervisor")

		titles = [r["title"] for r in get_turn(CONVERSATION)["dms_documents"]]

		self.assertEqual(titles, ["Leave Policy", "Overtime SOP"])

	def test_an_empty_search_keeps_what_the_turn_already_holds(self):
		self.search("annual leave approval")
		self.search("warehouse pallets")

		self.assertEqual(len(get_turn(CONVERSATION)["dms_documents"]), 1)

	def test_document_type_filter_excludes_other_types(self):
		self.assertEqual(self.search("annual leave approval", "SOP")["results"], [])

	def test_user_without_read_permission_is_refused(self):
		frappe.set_user("Guest")

		with self.assertRaises(frappe.PermissionError):
			self.search("annual leave approval")

		self.assertNotIn("dms_documents", get_turn(CONVERSATION))

	def test_inactive_document_is_not_found(self):
		self.policy.db_set("lifecycle_state", "Inactive")

		self.assertEqual(self.search("annual leave approval")["results"], [])

	def test_searching_does_not_change_the_register(self):
		modified = frappe.db.get_value("Document Register", self.policy.name, "modified")

		self.search("annual leave approval")

		self.assertEqual(frappe.db.get_value("Document Register", self.policy.name, "modified"), modified)

	def test_generate_and_modify_prompts_carry_what_the_tool_found(self):
		self.search("annual leave approval")

		for sub_id, label in (("process_generator", "GENERATOR"), ("modifier", "MODIFIER")):
			prompt = self.prompt(sub_id)
			self.assertTrue(prompt.startswith(f"{label}\n\nCompany documents relevant to this process:"))
			self.assertIn(f"[Policy] POL-T1 - Leave Policy (v{self.policy.current_version})", prompt)
			self.assertIn(LEAVE_TEXT, prompt)
			self.assertNotIn(OVERTIME_TEXT, prompt)

	def test_prompts_are_unchanged_when_the_tool_was_not_called(self):
		self.assertEqual(self.prompt("process_generator"), "GENERATOR")

	def test_intent_classifier_prompt_has_no_documents(self):
		self.search("annual leave approval")

		self.assertEqual(self.prompt("intent_classifier"), "CLASSIFIER")

	def test_block_names_every_type_in_precedence_order(self):
		self.search("annual leave approval")

		prompt = self.prompt("process_generator")

		self.assertIn(", ".join(DOCUMENT_TYPES), prompt)
		for document_type in DOCUMENT_TYPES:
			self.assertIn(document_type, prompt)

	def test_document_without_a_code_is_listed_by_title(self):
		self.policy.db_set("document_code", None)
		self.search("annual leave approval")

		prompt = self.prompt("process_generator")

		self.assertIn("[Policy] Leave Policy (v", prompt)
		self.assertNotIn("None", prompt)


class TestProsallyDmsPatch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()

	def test_tool_script_calls_the_turn_search_with_the_shapes_arguments(self):
		dms_patch._upsert_tool_script()

		script = frappe.db.get_value("Server Script", dms_patch.TOOL_SCRIPT, "script")

		self.assertIn("search_dms_for_turn(context_docname, task_data.get", script)

	def test_shape_lands_in_the_tools_sub_process_with_its_arguments_and_bounds(self):
		xml = dms_patch.splice_shape(TOOLS_MAP)

		tools = xml[xml.index('id="prosally_tools"') : xml.index("</bpmn:adHocSubProcess>")]
		self.assertIn('<bpmn:scriptTask id="search_dms_documents"', tools)
		self.assertIn("aiToolParams", tools)
		self.assertIn(f"<bpmn:script>{dms_patch.TOOL_SCRIPT}</bpmn:script>", tools)
		self.assertIn('bpmnElement="search_dms_documents"', xml)

	def test_splicing_twice_changes_nothing(self):
		once = dms_patch.splice_shape(TOOLS_MAP)

		self.assertEqual(dms_patch.splice_shape(once), once)

	def test_a_map_without_the_tools_sub_process_is_left_alone(self):
		self.assertIsNone(dms_patch.splice_shape("<bpmn:process id='p'></bpmn:process>"))

	def test_a_refused_recompile_is_logged_and_does_not_stop_the_patch(self):
		refused = patch("one_bpmn.api.compilation.compile_process_model", side_effect=frappe.ValidationError("not Live"))
		with patch.object(frappe.db, "get_value", side_effect=["Model", TOOLS_MAP]), patch.object(
			frappe.db, "set_value"
		) as set_value, refused, patch.object(frappe, "log_error") as log_error:
			dms_patch._update_process_model()

		self.assertIn("search_dms_documents", set_value.call_args.args[3])
		log_error.assert_called_once()

	def test_prompt_gets_the_dms_rules_once(self):
		frappe.db.delete("AI Agent Configuration", {"agent_id": dms_patch.AGENT_ID})
		config = frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_id": dms_patch.AGENT_ID,
				"agent_name": "ZZ ProsAlly",
				"chat_mode_label": "ZZ ProsAlly",
				"agent_type": "Chat",
				"agent_framework": "Direct API",
				"lifecycle_status": "Live",
				"enabled": 1,
				"system_prompt": "Exactly THREE tool calls per turn.",
			}
		).insert(ignore_permissions=True)

		dms_patch.append_prompt()
		dms_patch.append_prompt()

		prompt = frappe.db.get_value("AI Agent Configuration", config.name, "system_prompt")
		self.assertEqual(prompt.count("COMPANY DOCUMENTS (DMS)"), 1)
		self.assertIn("four calls", prompt)
		self.assertIn("Policy, SOP, Manual, Guideline, Knowledge Base", prompt)
