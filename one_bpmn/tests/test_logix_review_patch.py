# Copyright (c) 2026, one-fm and contributors

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import logix_review_skips_an_answer_in_words as review_patch
from one_bpmn.one_bpmn.patches.v1_0.inline_logix_tool_scripts import REVIEW

ANSWER = "This script shows a message saying the visa cancellation remark is mandatory."
CODE_DRAFT = 'Done.\n\n```python\nresult["ok"] = True\n```'


class TestLogixReviewSkipsAnAnswerInWords(FrappeTestCase):
	def setUp(self):
		if frappe.db.exists("Server Script", review_patch.SCRIPT):
			frappe.db.set_value("Server Script", review_patch.SCRIPT, "script", REVIEW)
		else:
			frappe.get_doc(
				{
					"doctype": "Server Script",
					"name": review_patch.SCRIPT,
					"script_type": "API",
					"api_method": "zz_logix_review_stub",
					"script": REVIEW,
				}
			).db_insert()

	def _review(self, draft):
		"""Run the stored review script on *draft*; return the reviewer mock and the turn updates."""
		code = frappe.db.get_value("Server Script", review_patch.SCRIPT, "script")
		adapter = MagicMock()
		completion = MagicMock(text='{"approved": false, "revised_script": "x = 1"}')
		updates = {}
		with (
			patch("one_bpmn.agents.turn_state.get_turn", return_value={"draft": draft}),
			patch("one_bpmn.agents.turn_state.update_turn", side_effect=lambda _c, **kw: updates.update(kw)),
			patch("one_bpmn.agents.turn_state.run_sync", return_value=completion),
			patch("one_bpmn.agents.llm_provider.get_llm_adapter_from_settings", return_value=adapter),
		):
			exec(code, {"frappe": frappe, "context_docname": "zz-conv", "result": {}})
		return adapter, updates

	def test_an_answer_in_words_is_passed_through_unreviewed(self):
		review_patch.execute()
		adapter, updates = self._review(ANSWER)
		adapter.complete.assert_not_called()
		self.assertEqual((updates["final"], updates["is_question"]), (ANSWER, True))

	def test_a_draft_with_code_is_still_reviewed(self):
		review_patch.execute()
		adapter, _ = self._review(CODE_DRAFT)
		adapter.complete.assert_called_once()

	def test_the_edit_is_applied_once(self):
		review_patch.execute()
		review_patch.execute()
		code = frappe.db.get_value("Server Script", review_patch.SCRIPT, "script")
		self.assertEqual(code.count("_has_code = re.search"), 1)
