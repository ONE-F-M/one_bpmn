# Copyright (c) 2026, one-fm and contributors
"""ProsAlly answers questions about company documents and names the documents it checked when it draws.

Run with:
    bench run-tests --app processa --module processa.tests.test_prosally_dms_replies
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.prosally import helpers, tools_prompts
from processa.ai_agent_registry.definitions.shared.tools_dms import DOCUMENT_TYPES
from processa.processa_engine.agent_runtime.turn_state import clear_turn, get_turn, set_turn
from processa.patches.v1_0 import prosally_answers_dms_questions as dms_patch

LEAVE_TEXT = "annual leave requests above five days need director approval"
QUESTION = "What does our annual leave policy say about director approval?"
CONVERSATION = "zz-prosally-dms-replies"
REDIRECT_SCRIPT = """# ProsAlly – Tool Redirect (self-contained, FLAT top-level code).
from processa.processa_engine.agent_runtime.turn_state import get_turn, update_turn
from processa.ai_agent_registry.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

turn = get_turn(context_docname)
_cfg = get_agent_config("prosally_agent") or {}
_subs = _cfg.get("sub_prompts") or {}
msg = (_subs.get("redirect") or {}).get(
    "prompt",
    "I'm here to help with process modelling. I'm not able to help with that request.",
)
output = {"intent": "IRRELEVANT", "action_intent": None, "response": msg, "options": []}
update_turn(context_docname, output=output, done=True)
result["response"] = msg
"""
SAVE_SCRIPT = """import json
conversation_id = task_data.get("conversation_id", context_docname)
_turn = get_turn(conversation_id)
response_text = "x"
intent = "BPMN_GENERATED"
agent_result = {"response": "x"}
msg = frappe.new_doc("Chat Message")
msg.text = response_text
"""


def answered(text="Director approval is needed above five days.", sources=None):
	return json.dumps({"answered": True, "answer": text, "sources": sources or []})


class TestProsallyDmsAnswer(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		set_turn(CONVERSATION, {"user_text": QUESTION})
		self.policy = self.make_document("DMS-RP-POLICY", "Leave Policy", "Policy", LEAVE_TEXT, "POL-T1")
		self.sop = self.make_document("DMS-RP-SOP", "Leave SOP", "SOP", "annual leave director approval step", "SOP-T1")

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

	def answer(self, model_reply, question=QUESTION):
		failing = isinstance(model_reply, Exception)
		with patch.object(tools_prompts, "complete_sub_prompt",
			side_effect=model_reply if failing else None,
			return_value=None if failing else model_reply,
		) as model:
			return tools_prompts.dms_answer_output(CONVERSATION, question), model

	def test_a_matching_question_gets_the_answer_and_the_documents_it_used(self):
		reply, _model = self.answer(answered(sources=["POL-T1"]))

		self.assertEqual(reply["intent"], "CLARIFY")
		self.assertIn("Director approval is needed above five days.", reply["response"])
		self.assertIn("POL-T1 - Leave Policy (Policy)", reply["response"])
		self.assertNotIn("SOP-T1", reply["response"])

	def test_the_model_gets_the_excerpts_and_the_type_rules(self):
		_reply, model = self.answer(answered())

		sent = json.loads(model.call_args.args[2])
		self.assertEqual(sent["question"], QUESTION)
		self.assertIn(LEAVE_TEXT, [d["excerpt"] for d in sent["documents"]])
		self.assertIn(", ".join(DOCUMENT_TYPES), model.call_args.kwargs["system"])

	def test_without_named_sources_every_document_found_is_listed(self):
		reply, _model = self.answer(answered())

		self.assertIn("POL-T1", reply["response"])
		self.assertIn("SOP-T1", reply["response"])

	def test_a_question_no_document_matches_is_left_to_the_ordinary_decline(self):
		reply, model = self.answer(answered(), "Which pallets are in the warehouse?")

		self.assertIsNone(reply)
		model.assert_not_called()

	def test_documents_that_do_not_answer_it_leave_the_ordinary_decline(self):
		reply, _model = self.answer(json.dumps({"answered": False, "answer": ""}))

		self.assertIsNone(reply)

	def test_a_failed_model_call_lists_the_documents_found(self):
		with patch.object(frappe, "log_error") as log_error:
			reply, _model = self.answer(RuntimeError("no model"))

		self.assertEqual(reply["intent"], "CLARIFY")
		self.assertIn("POL-T1 - Leave Policy (Policy)", reply["response"])
		log_error.assert_called_once()

	def test_a_user_who_cannot_read_the_register_gets_the_ordinary_decline(self):
		frappe.set_user("Guest")

		reply, model = self.answer(answered())

		self.assertIsNone(reply)
		model.assert_not_called()

	def test_an_empty_question_is_not_searched(self):
		reply, model = self.answer(answered(), "  ")

		self.assertIsNone(reply)
		model.assert_not_called()

	def test_the_answer_keeps_what_the_search_found_in_the_turn(self):
		self.answer(answered())

		self.assertTrue(get_turn(CONVERSATION)["dms_documents"])


class TestAddDocumentSources(FrappeTestCase):
	DOCS = [
		{"document_code": "POL-0002", "title": "Policy for workflow states", "document_type": "Policy"},
		{"document_code": "POL-0002", "title": "Policy for workflow states", "document_type": "Policy"},
		{"document_code": None, "title": "Guideline for Meetings", "document_type": "Guideline"},
	]

	def test_a_drawn_or_changed_diagram_names_the_documents_once_each(self):
		for intent in ("BPMN_GENERATED", "BPMN_MODIFIED"):
			text = helpers.add_document_sources("Drew it.", intent, {"dms_documents": self.DOCS})

			self.assertEqual(
				text,
				"Drew it.\n\nDocuments checked: POL-0002 - Policy for workflow states (Policy); Guideline for Meetings (Guideline)",
			)

	def test_other_replies_are_left_alone(self):
		for intent in ("CLARIFY", "CONFIRM", "IRRELEVANT", None):
			self.assertEqual(helpers.add_document_sources("Hello", intent, {"dms_documents": self.DOCS}), "Hello")

	def test_no_documents_found_adds_nothing(self):
		self.assertEqual(helpers.add_document_sources("Drew it.", "BPMN_GENERATED", {}), "Drew it.")
		self.assertEqual(helpers.add_document_sources("Drew it.", "BPMN_GENERATED", {"dms_documents": []}), "Drew it.")

	def test_at_most_four_documents_are_named(self):
		many = [{"document_code": f"D-{i}", "title": f"T{i}", "document_type": "SOP"} for i in range(7)]

		line = helpers.add_document_sources("x", "BPMN_GENERATED", {"dms_documents": many}).split("\n\n")[1]

		self.assertEqual(line.count(";"), 3)


class TestProsallyDmsRepliesPatch(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()

	def test_redirect_asks_for_a_document_answer_before_it_declines(self):
		edited = dms_patch.edit_redirect_script(REDIRECT_SCRIPT)

		self.assertIn("dms_answer_output(context_docname", edited)
		self.assertIn("I'm here to help with process modelling.", edited)
		self.assertLess(edited.index("dms_answer_output"), edited.index('"intent": "IRRELEVANT"'))

	def test_save_response_names_the_documents_before_the_message_is_made(self):
		edited = dms_patch.edit_save_response(SAVE_SCRIPT)

		self.assertLess(edited.index("add_document_sources"), edited.index('msg = frappe.new_doc("Chat Message")'))
		self.assertIn('agent_result["response"] = response_text', edited)

	def test_editing_twice_changes_nothing(self):
		for editor, script in ((dms_patch.edit_redirect_script, REDIRECT_SCRIPT), (dms_patch.edit_save_response, SAVE_SCRIPT)):
			once = editor(script)

			self.assertEqual(editor(once), once)

	def test_a_script_that_lost_its_edit_point_is_reported_not_edited(self):
		self.assertIsNone(dms_patch.edit_redirect_script("print('x')"))
		self.assertIsNone(dms_patch.edit_save_response("print('x')"))

	def test_execute_edits_the_live_scripts_and_logs_a_missing_edit_point(self):
		frappe.db.set_value("Server Script", dms_patch.REDIRECT_SCRIPT, "script", REDIRECT_SCRIPT)
		frappe.db.set_value("Server Script", dms_patch.SAVE_SCRIPT, "script", "print('moved on')")

		with patch.object(frappe, "log_error") as log_error:
			dms_patch.execute()

		self.assertIn("dms_answer_output", frappe.db.get_value("Server Script", dms_patch.REDIRECT_SCRIPT, "script"))
		self.assertEqual(frappe.db.get_value("Server Script", dms_patch.SAVE_SCRIPT, "script"), "print('moved on')")
		log_error.assert_called_once()
