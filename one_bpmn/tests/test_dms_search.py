import hashlib
import math
import os
import tempfile
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import dms_search
from one_bpmn.one_bpmn.patches.v1_0 import general_chat_answers_from_dms as patch_module

DIMENSIONS = 64
LEAVE_TEXT = "annual leave entitlement is thirty days per year"
OVERTIME_TEXT = "overtime must be approved by the supervisor before the shift"


def word_hash_embed(texts):
	"""Bag-of-words vectors, so texts sharing words are near each other."""
	vectors = []
	for text in texts:
		vector = [0.0] * DIMENSIONS
		for word in text.lower().split():
			vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIMENSIONS] += 1.0
		norm = math.sqrt(sum(v * v for v in vector)) or 1.0
		vectors.append([v / norm for v in vector])
	return vectors


class TestDmsSearch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		index_path = os.path.join(tempfile.mkdtemp(), "dms_search_index.json")
		patcher = patch.object(dms_search, "_index_path", lambda: index_path)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.use_embeddings(word_hash_embed)

		self.policy = self.make_document("DMS-TEST-POLICY", "Leave Policy", "Policy", LEAVE_TEXT)
		self.sop = self.make_document("DMS-TEST-SOP", "Overtime SOP", "SOP", OVERTIME_TEXT)
		dms_search.reindex_document(self.policy.name)
		dms_search.reindex_document(self.sop.name)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def use_embeddings(self, embed):
		patcher = patch.object(dms_search, "embed", embed)
		patcher.start()
		self.addCleanup(patcher.stop)

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

	def test_result_carries_type_code_and_version(self):
		result = dms_search.search_dms_documents("how many days of annual leave")["results"][0]

		self.assertEqual(result["document_type"], "Policy")
		self.assertEqual(result["title"], "Leave Policy")
		self.assertEqual(result["document_code"], self.policy.document_code)
		self.assertEqual(result["version"], self.policy.current_version)

	def test_document_type_filter_excludes_other_types(self):
		query = "overtime approved by the supervisor before the shift"

		self.assertEqual(dms_search.search_dms_documents(query, document_type="Policy"), {"results": []})
		results = dms_search.search_dms_documents(query, document_type="SOP")["results"]
		self.assertEqual({r["document_type"] for r in results}, {"SOP"})

	def test_unknown_document_type_is_rejected(self):
		self.assertIn("error", dms_search.search_dms_documents("leave", document_type="Memo"))

	def test_inactive_document_is_not_returned(self):
		self.policy.db_set("lifecycle_state", "Inactive")
		dms_search.reindex_document(self.policy.name)

		titles = [r["title"] for r in dms_search.search_dms_documents("annual leave entitlement")["results"]]

		self.assertNotIn("Leave Policy", titles)

	def test_deleted_document_is_not_returned(self):
		frappe.delete_doc(dms_search.DOCTYPE, self.policy.name, force=True, ignore_permissions=True)
		dms_search.reindex_document(self.policy.name)

		self.assertEqual(dms_search.search_dms_documents("annual leave entitlement"), {"results": []})

	def test_user_without_read_permission_gets_nothing(self):
		frappe.set_user("Guest")

		self.assertEqual(dms_search.search_dms_documents("annual leave entitlement"), {"results": []})

	def test_keyword_search_answers_when_embeddings_are_unavailable(self):
		self.use_embeddings(lambda texts: None)
		dms_search.reindex_document(self.policy.name)
		dms_search.reindex_document(self.sop.name)

		titles = [r["title"] for r in dms_search.search_dms_documents("annual leave entitlement")["results"]]

		self.assertEqual(titles, ["Leave Policy"])


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
