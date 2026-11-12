"""ProsAlly Finalize runs the redirect or clarify stage itself when the orchestrator skipped it (WI-000286).

The Redirect and Clarify logic lives in prosally_helpers.redirect_output and clarify_output; the
Redirect, Clarify and Finalize Server Scripts all call those helpers, so there is one copy of each.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

from one_bpmn.agents import prosally_helpers as helpers

CFG = {"sub_prompts": {"redirect": {"prompt": "Redirect text."}, "clarifier": {"prompt": "sys"}}}
GENERIC_QUESTION = "Could you tell me more about the process you'd like to model?"


class TestRedirectOutput(unittest.TestCase):
    def test_declines_with_the_redirect_prompt_when_no_document_answers(self):
        with (
            mock.patch.object(helpers, "get_turn", return_value={"user_text": "hi"}),
            mock.patch.object(helpers, "get_agent_config", return_value=dict(CFG)),
            mock.patch.object(helpers, "dms_answer_output", return_value=None),
            mock.patch.object(helpers, "update_turn") as update,
        ):
            out = helpers.redirect_output("ctx")

        self.assertEqual(out["response"], "Redirect text.")
        self.assertEqual(out["intent"], "IRRELEVANT")
        update.assert_called_once_with("ctx", output=out, done=True)


class TestClarifyOutput(unittest.TestCase):
    def test_asks_the_clarifier_question_and_closes_the_turn(self):
        adapter = mock.Mock()
        adapter.complete.return_value = SimpleNamespace(
            text='{"question": "Which lanes?", "options": ["A"]}'
        )
        with (
            mock.patch.object(
                helpers, "get_turn", return_value={"user_text": "make one", "process_name": "P"}
            ),
            mock.patch.object(helpers, "get_agent_config", return_value=dict(CFG)),
            mock.patch.object(helpers, "get_llm_adapter_from_settings", return_value=adapter),
            mock.patch.object(helpers, "run_sync", side_effect=lambda x: x),
            mock.patch.object(helpers, "update_turn") as update,
        ):
            out = helpers.clarify_output("ctx")

        self.assertEqual(out["response"], "Which lanes?")
        self.assertEqual(out["options"], ["A"])
        update.assert_called_once()


class TestFinalizeRunsTheRoutedTool(unittest.TestCase):
    def _run_finalize(self, turn):
        ns = {"context_docname": "ctx", "instance": None, "result": {}}
        with (
            mock.patch("one_bpmn.agents.turn_state.get_turn", return_value=turn),
            mock.patch("one_bpmn.agents.turn_state.update_turn"),
            mock.patch.object(
                helpers, "redirect_output", return_value={"response": "R", "options": []}
            ) as redirect,
            mock.patch.object(
                helpers, "clarify_output", return_value={"response": "C", "options": []}
            ) as clarify,
        ):
            exec(patch.FINALIZE, ns)
        return ns["result"], redirect, clarify

    def test_irrelevant_intent_runs_redirect_and_records_it(self):
        result, redirect, clarify = self._run_finalize({"intent": "IRRELEVANT"})

        redirect.assert_called_once()
        clarify.assert_not_called()
        self.assertEqual(result["response"], "R")
        self.assertEqual(result["ran_tool"], "redirect")
        self.assertTrue(result["finalized"])

    def test_incomplete_intent_runs_clarify_and_records_it(self):
        result, redirect, clarify = self._run_finalize({"intent": "INCOMPLETE"})

        clarify.assert_called_once()
        redirect.assert_not_called()
        self.assertEqual(result["response"], "C")
        self.assertEqual(result["ran_tool"], "clarify")

    def test_a_turn_already_done_is_left_alone(self):
        result, redirect, clarify = self._run_finalize({"done": True, "intent": "IRRELEVANT"})

        redirect.assert_not_called()
        clarify.assert_not_called()
        self.assertTrue(result["finalized"])
        self.assertNotIn("ran_tool", result)

    def test_no_routed_intent_keeps_the_generic_fallback(self):
        result, redirect, clarify = self._run_finalize({})

        redirect.assert_not_called()
        clarify.assert_not_called()
        self.assertTrue(result["fallback"])
        self.assertNotIn("ran_tool", result)
        self.assertIn(GENERIC_QUESTION, patch.FINALIZE)
