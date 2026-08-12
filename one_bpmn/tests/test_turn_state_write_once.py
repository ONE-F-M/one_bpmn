"""The per-turn store's terminal keys are write-once (WI-002001).

``output`` is the reply ``Save Response`` persists and ``done`` marks it final.
The store used to be last-writer-wins, so the orchestrating LLM only had to call
one extra stage tool to destroy a finished turn.

That is exactly what ProsAlly did. On a confirmed MODIFY_EXISTING the tool
sequence should be ``classify_intent → modify_process → finalize``; roughly two
turns in five came back ``classify_intent → modify_process → confirm →
finalize``. ``modify_process`` had already written a CONFIRM_REMOVAL output
carrying the rebuilt diagram, and the stray ``confirm`` replaced it with a fresh
"Shall I go ahead?" — so the designer was re-asked a question they had already
answered, and the diagram they asked for was silently discarded, every pass.

A stage tool cannot police this itself: it cannot know another tool ran after it.
These tests pin the invariant to the store, where it covers every agent that
shares it (ProsAlly, Logix, Docu, LuCrusher).

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_turn_state_write_once
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.turn_state import clear_turn, get_turn, set_turn, update_turn

ANSWERED = {"intent": "CONFIRM_REMOVAL", "response": "removals need approval", "pending_xml": "<bpmn/>"}
STRAY = {"intent": "CONFIRM", "response": "Shall I go ahead?", "options": ["Yes, proceed"]}


class TestTurnStateWriteOnce(FrappeTestCase):
    def setUp(self):
        self.conversation = f"wi2001-{frappe.generate_hash(length=8)}"
        self.addCleanup(clear_turn, self.conversation)
        # What "Build Context" does at the top of every turn.
        set_turn(self.conversation, {"user_text": "Yes, proceed", "confirmed_action": "MODIFY_EXISTING"})

    def _answer(self):
        update_turn(self.conversation, output=ANSWERED, done=True)

    def test_first_terminal_write_lands(self):
        self._answer()
        turn = get_turn(self.conversation)
        self.assertEqual(turn["output"], ANSWERED)
        self.assertTrue(turn["done"])

    def test_second_terminal_write_is_refused(self):
        """The bug: a stage tool running after the turn was answered."""
        self._answer()
        update_turn(self.conversation, output=STRAY, done=True)
        self.assertEqual(
            get_turn(self.conversation)["output"],
            ANSWERED,
            "a later stage tool overwrote the turn's reply",
        )

    def test_refusal_survives_repeated_attempts(self):
        self._answer()
        for _ in range(3):
            update_turn(self.conversation, output=STRAY, done=True)
        self.assertEqual(get_turn(self.conversation)["output"], ANSWERED)

    def test_done_alone_cannot_reopen_or_close_a_turn(self):
        """``done`` is terminal too — neither key may be rewritten."""
        self._answer()
        update_turn(self.conversation, done=False)
        self.assertTrue(get_turn(self.conversation)["done"])

    def test_non_terminal_keys_still_apply_after_the_turn_is_answered(self):
        """The guard protects the reply, not the whole scratch dict — a refused
        call must not silently drop the other keys it carried."""
        self._answer()
        update_turn(self.conversation, output=STRAY, done=True, intent="MODIFY_EXISTING")
        turn = get_turn(self.conversation)
        self.assertEqual(turn["output"], ANSWERED)
        self.assertEqual(turn["intent"], "MODIFY_EXISTING")

    def test_non_terminal_writes_before_the_answer_are_untouched(self):
        """classify_intent writes intent/confirmed with no output — the common path."""
        update_turn(self.conversation, intent="MODIFY_EXISTING", confirmed=True)
        turn = get_turn(self.conversation)
        self.assertEqual(turn["intent"], "MODIFY_EXISTING")
        self.assertTrue(turn["confirmed"])
        self.assertNotIn("output", turn)

    def test_the_guard_is_per_turn_not_across_turns(self):
        """``Build Context`` reseeds with set_turn, which clears ``done``. The
        NEXT turn must be able to answer, or the fix would freeze the whole
        conversation on its first reply."""
        self._answer()
        set_turn(self.conversation, {"user_text": "now change the lanes"})
        update_turn(self.conversation, output=STRAY, done=True)
        self.assertEqual(get_turn(self.conversation)["output"], STRAY)

    def test_a_turn_that_was_never_answered_can_be_answered(self):
        """finalize's fallback path: nothing terminal written yet."""
        update_turn(self.conversation, intent="INCOMPLETE")
        update_turn(self.conversation, output=STRAY, done=True)
        self.assertEqual(get_turn(self.conversation)["output"], STRAY)


class TestProsAllyModifyToolContract(FrappeTestCase):
    """The signal that invited the stray call in the first place.

    The removal-confirmation branch used to hand the orchestrator
    ``{"modified": false}``, which reads as "the change did not happen" — so the
    model asked the designer again. The stage IS complete; the diagram is in the
    turn output awaiting approval of the removals it implies.
    """

    SCRIPT = "ProsAlly – Tool Modify Process"

    def setUp(self):
        if not frappe.db.exists("Server Script", self.SCRIPT):
            self.skipTest(f"{self.SCRIPT} is not installed on this site")
        self.body = frappe.db.get_value("Server Script", self.SCRIPT, "script") or ""

    def test_no_branch_reports_completed_work_as_falsy(self):
        self.assertNotIn(
            'result["modified"] = False',
            self.body,
            "the removal-confirm branch reports a completed stage as a failure again",
        )

    def test_both_branches_report_the_stage_as_complete(self):
        self.assertEqual(
            self.body.count('result["stage_complete"] = True'),
            2,
            "both the removal-confirm and the applied branch must report stage_complete",
        )
