# Copyright (c) 2026, one-fm and contributors
"""ProsAlly's generate and modify stage prompts carry the relevant Document Register excerpts.

Run with:
    bench run-tests --app one_bpmn --module one_bpmn.tests.test_prosally_dms_documents
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import prosally_helpers as helpers
from one_bpmn.agents.dms_search import DOCUMENT_TYPES

LEAVE_TEXT = "annual leave requests above five days need director approval"
OVERTIME_TEXT = "overtime must be approved by the supervisor before the shift"
CFG = {
	"sub_prompts": {
		"process_generator": {"prompt": "GENERATOR"},
		"modifier": {"prompt": "MODIFIER"},
		"intent_classifier": {"prompt": "CLASSIFIER"},
	},
	"constants": {},
}


class TestProsallyDmsDocuments(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.policy = self.make_document("DMS-PA-POLICY", "Leave Policy", "Policy", LEAVE_TEXT, "POL-T1")
		self.sop = self.make_document("DMS-PA-SOP", "Overtime SOP", "SOP", OVERTIME_TEXT, "SOP-T1")

	def tearDown(self):
		frappe.set_user("Administrator")
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

	def prompt(self, sub_id, turn):
		return helpers.stage_system_prompt(CFG, sub_id, "", turn)

	def test_generate_prompt_carries_the_matching_document(self):
		prompt = self.prompt("process_generator", {"user_text": "draw the annual leave approval process"})

		self.assertTrue(prompt.startswith("GENERATOR\n\nCompany documents relevant to this process:"))
		self.assertIn(f"[Policy] {self.policy.document_code} - Leave Policy", prompt)
		self.assertIn(LEAVE_TEXT, prompt)
		self.assertNotIn(OVERTIME_TEXT, prompt)

	def test_document_without_a_code_is_listed_by_title(self):
		self.policy.db_set("document_code", None)

		prompt = self.prompt("process_generator", {"user_text": "annual leave approval"})

		self.assertIn("[Policy] Leave Policy (v", prompt)
		self.assertNotIn("None", prompt)

	def test_modify_prompt_carries_the_matching_document(self):
		prompt = self.prompt("modifier", {"process_name": "Overtime", "user_text": "add supervisor approval"})

		self.assertIn(f"[SOP] {self.sop.document_code} - Overtime SOP", prompt)

	def test_intent_classifier_prompt_has_no_documents(self):
		prompt = self.prompt("intent_classifier", {"user_text": "annual leave approval"})

		self.assertEqual(prompt, "CLASSIFIER")

	def test_inactive_document_is_left_out(self):
		self.policy.db_set("lifecycle_state", "Inactive")

		prompt = self.prompt("process_generator", {"user_text": "annual leave approval"})

		self.assertEqual(prompt, "GENERATOR")

	def test_block_names_every_type_in_precedence_order(self):
		prompt = self.prompt("process_generator", {"user_text": "annual leave approval"})

		self.assertIn(", ".join(DOCUMENT_TYPES), prompt)
		for document_type in DOCUMENT_TYPES:
			self.assertIn(document_type, prompt)

	def test_affirmation_searches_with_the_earlier_request(self):
		turn = {
			"user_text": "yes please",
			"chat_history": [
				{"role": "user", "content": "draw the annual leave approval process"},
				{"role": "assistant", "content": "Shall I draw it?"},
			],
		}

		self.assertIn(LEAVE_TEXT, self.prompt("process_generator", turn))

	def test_user_without_read_permission_gets_no_documents_and_no_error(self):
		frappe.set_user("Guest")

		prompt = self.prompt("process_generator", {"user_text": "annual leave approval"})

		self.assertEqual(prompt, "GENERATOR")

	def test_building_the_prompt_does_not_change_the_register(self):
		modified = frappe.db.get_value("Document Register", self.policy.name, "modified")

		self.prompt("process_generator", {"user_text": "annual leave approval"})

		self.assertEqual(frappe.db.get_value("Document Register", self.policy.name, "modified"), modified)
