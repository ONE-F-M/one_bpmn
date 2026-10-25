import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import dms_search
from one_bpmn.one_bpmn.patches.v1_0 import general_chat_answers_from_dms as patch_module

LEAVE_TEXT = "annual leave entitlement is thirty days per year"
OVERTIME_TEXT = "overtime must be approved by the supervisor before the shift"


class TestDmsSearch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.policy = self.make_document("DMS-TEST-POLICY", "Leave Policy", "Policy", LEAVE_TEXT)
		self.sop = self.make_document("DMS-TEST-SOP", "Overtime SOP", "SOP", OVERTIME_TEXT)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def make_document(self, drive_file_id, title, document_type, content):
		return frappe.get_doc(
			{
				"doctype": "Document Register",
				"drive_file_id": drive_file_id,
				"title": title,
				"drive_file_link": f"https://drive.google.com/file/d/{drive_file_id}/view",
				"document_type": document_type,
				"lifecycle_state": "Active",
				"content": content,
			}
		).insert(ignore_permissions=True)

	def titles(self, query, document_type=None):
		results = dms_search.search_dms_documents(query, document_type)["results"]
		return [result["title"] for result in results]

	def test_result_carries_type_code_and_version(self):
		result = dms_search.search_dms_documents("how many days of annual leave")["results"][0]

		self.assertEqual(result["document_type"], "Policy")
		self.assertEqual(result["title"], "Leave Policy")
		self.assertEqual(result["document_code"], self.policy.document_code)
		self.assertEqual(result["version"], self.policy.current_version)
		self.assertEqual(result["excerpt"], LEAVE_TEXT)

	def test_only_the_matching_document_is_returned(self):
		self.assertEqual(self.titles("annual leave entitlement"), ["Leave Policy"])

	def test_plural_query_words_match_singular_text(self):
		self.assertEqual(self.titles("overtimes approved supervisors"), ["Overtime SOP"])

	def test_document_type_filter_excludes_other_types(self):
		query = "annual leave entitlement overtime supervisor"

		self.assertEqual(self.titles(query, "SOP"), ["Overtime SOP"])
		self.assertEqual(self.titles(query, "Policy"), ["Leave Policy"])
		self.assertEqual(self.titles(query, "Manual"), [])

	def test_unknown_document_type_is_rejected(self):
		self.assertIn("error", dms_search.search_dms_documents("leave", document_type="Memo"))

	def test_query_with_no_keywords_returns_nothing(self):
		self.assertEqual(dms_search.search_dms_documents("the and of"), {"results": []})

	def test_inactive_document_is_not_returned(self):
		self.policy.db_set("lifecycle_state", "Inactive")

		self.assertEqual(self.titles("annual leave entitlement"), [])

	def test_user_without_read_permission_is_refused(self):
		frappe.set_user("Guest")

		with self.assertRaises(frappe.PermissionError):
			dms_search.search_dms_documents("annual leave entitlement")

	def conversation_instance(self, owner):
		conversation = frappe.get_doc({"doctype": "Chat Conversation", "agent_mode": "General Chat"}).insert(
			ignore_permissions=True
		)
		frappe.db.set_value("Chat Conversation", conversation.name, "owner", owner)
		return frappe._dict(context_doctype="Chat Conversation", context_docname=conversation.name)

	def test_reads_are_checked_as_the_conversation_owner(self):
		instance = self.conversation_instance("Administrator")
		frappe.set_user("Guest")

		results = dms_search.search_dms_documents("annual leave entitlement", instance=instance)["results"]

		self.assertEqual([result["title"] for result in results], ["Leave Policy"])

	def test_conversation_owner_without_read_permission_is_refused(self):
		instance = self.conversation_instance("Guest")

		with self.assertRaises(frappe.PermissionError):
			dms_search.search_dms_documents("annual leave entitlement", instance=instance)


class TestGeneralChatDmsPatch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.delete("AI Agent Configuration", {"agent_id": patch_module.AGENT_ID})
		self.config = frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_id": patch_module.AGENT_ID,
				"agent_name": "ZZ General Chat",
				"chat_mode_label": "ZZ General Chat",
				"agent_type": "Chat",
				"agent_framework": "Direct API",
				"lifecycle_status": "Live",
				"enabled": 1,
				"system_prompt": "You are a helpful assistant.",
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	def test_prompt_gets_the_dms_rules_once(self):
		patch_module.append_prompt()
		patch_module.append_prompt()

		prompt = frappe.db.get_value("AI Agent Configuration", self.config.name, "system_prompt")

		self.assertEqual(prompt.count("COMPANY DOCUMENTS (DMS)"), 1)
		self.assertIn("Policy, SOP, Manual, Guideline, Knowledge Base", prompt)

	def test_tool_script_calls_the_search(self):
		patch_module._upsert_tool_script()

		script = frappe.db.get_value("Server Script", patch_module.TOOL_SCRIPT, "script")

		self.assertIn("search_dms_documents(task_data.get", script)
