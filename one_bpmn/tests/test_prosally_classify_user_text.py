# Copyright (c) 2026, one-fm and contributors
"""ProsAlly Classify Intent recovers a missing message and reads a pasted specification as a drawing request.

Run with:
    bench run-tests --app one_bpmn --module one_bpmn.tests.test_prosally_classify_user_text
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import (
	prosally_classify_recovers_user_text_and_pasted_specs as classify_patch,
)

# The slice of the live script the patch edits, with the unrelated code between replaced by pass.
STUB_SCRIPT = (
	'turn = get_turn(context_docname)\nconfirmed = (turn.get("confirmed_action") or "").strip()\n'
	"if confirmed:\n    pass\nelse:\n"
	'    message = turn.get("user_text", "")\n'
	'    data = extract_json(complete_sub_prompt(_cfg, "intent_classifier", prompt, system=_system))\n'
)
PROMPT = "rules\n- CRITICAL: type change. " + classify_patch.PROMPT_ANCHOR + "\n- AMBIGUOUS applies when x."


def _patched_script():
	code = STUB_SCRIPT
	for _marker, anchor, replacement in classify_patch.EDITS:
		code = classify_patch.apply_edit(code, anchor, replacement)
	return code


class TestClassifyScriptPatch(FrappeTestCase):
	def _run(self, code):
		store = {classify_patch.SCRIPT: code}

		def set_value(doctype, name, field, value=None, **kwargs):
			store[name] = value

		with (
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(frappe.db, "get_value", side_effect=lambda doctype, name, *a, **k: store[name]),
			patch.object(frappe.db, "set_value", side_effect=set_value),
			patch.object(classify_patch, "edit_prompt"),
			patch.object(frappe, "log_error") as log_error,
		):
			classify_patch.execute()
			classify_patch.execute()
		return store[classify_patch.SCRIPT], log_error

	def test_edits_apply_once_and_compile(self):
		code, _ = self._run(STUB_SCRIPT)
		self.assertEqual(code.count("update_turn(context_docname, user_text=message)"), 1)
		self.assertEqual(code.count("No message text reached ProsAlly"), 1)
		compile(code, "classify", "exec")

	def test_a_missing_anchor_is_logged_and_the_script_is_unchanged(self):
		code, log_error = self._run("x = 1\n")
		self.assertEqual(code, "x = 1\n")
		self.assertEqual(log_error.call_count, 2 * len(classify_patch.EDITS))


class TestClassifyScriptBehaviour(FrappeTestCase):
	def _run(self, turn, chat_texts, confirmed=""):
		result = {}
		update_turn = MagicMock()
		complete = MagicMock(return_value='{"intent": "GENERATE_NEW"}')
		scope = {
			"context_docname": "CONV-1",
			"result": result,
			"get_turn": lambda _conversation: dict(turn, confirmed_action=confirmed),
			"update_turn": update_turn,
			"frappe": MagicMock(get_all=MagicMock(return_value=chat_texts)),
			"extract_json": lambda raw: {"intent": "GENERATE_NEW"} if raw else {},
			"complete_sub_prompt": complete,
			"_cfg": {},
			"_system": "",
			"prompt": "",
		}
		exec(_patched_script(), scope)  # nosemgrep
		return scope, result, update_turn, complete

	def test_a_blank_turn_is_filled_from_the_latest_chat_message(self):
		text = "# SYSTEM PROMPT: BPMN 2.0"
		scope, result, update_turn, _ = self._run({"user_text": ""}, [text])
		self.assertEqual(scope["message"], text)
		update_turn.assert_called_once_with("CONV-1", user_text=text)
		self.assertEqual(result["user_text_len"], len(text))
		self.assertEqual(result["user_text_source"], "chat_message")

	def test_text_in_the_turn_is_not_looked_up_again(self):
		scope, result, update_turn, _ = self._run({"user_text": "draw it"}, ["other"])
		scope["frappe"].get_all.assert_not_called()
		update_turn.assert_not_called()
		self.assertEqual((result["user_text_len"], result["user_text_source"]), (7, "turn"))

	def test_no_text_anywhere_is_incomplete_without_a_model_call(self):
		scope, result, _, complete = self._run({"user_text": "  "}, [])
		complete.assert_not_called()
		self.assertEqual(scope["data"]["intent"], "INCOMPLETE")
		self.assertEqual((result["user_text_len"], result["user_text_source"]), (0, "none"))

	def test_a_confirmed_turn_still_reports_the_length(self):
		_, result, _, _ = self._run({"user_text": "Yes, proceed"}, [], confirmed="GENERATE_NEW")
		self.assertEqual(result["user_text_len"], 12)


class TestClassifierPromptPatch(FrappeTestCase):
	def _run(self, prompt_text):
		row = frappe._dict(sub_agent_id="intent_classifier", prompt_text=prompt_text)
		doc = MagicMock(sub_prompts=[row])
		with (
			patch.object(frappe.db, "get_value", return_value="Prosally"),
			patch.object(frappe, "get_doc", return_value=doc),
			patch.object(frappe, "log_error") as log_error,
		):
			classify_patch.edit_prompt()
			classify_patch.edit_prompt()
		return row.prompt_text, doc, log_error

	def test_the_rule_is_added_once_after_the_type_change_rule(self):
		text, doc, _ = self._run(PROMPT)
		self.assertEqual(text.count(classify_patch.PROMPT_MARKER), 1)
		self.assertIn("Never classify it as IRRELEVANT", text)
		self.assertTrue(text.endswith("\n- AMBIGUOUS applies when x."))
		doc.save.assert_called_once()

	def test_a_missing_anchor_is_logged_and_the_prompt_is_unchanged(self):
		text, doc, log_error = self._run("no anchor here")
		self.assertEqual(text, "no anchor here")
		doc.save.assert_not_called()
		self.assertEqual(log_error.call_count, 2)
