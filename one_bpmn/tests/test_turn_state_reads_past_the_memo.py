"""``get_turn`` must see a write made outside this process's cache memo.

The store is Redis-backed, but ``frappe.cache.get_value`` answers from
``frappe.local.cache`` whenever the key is present and never consults Redis:

    local_cache = frappe.local.cache
    if key in local_cache:
        val = local_cache[key]

A stage tool's write does not reliably survive into the caller's local cache, so
``Save Response`` read a copy of the turn from before ``finalize`` had answered
it. Redis held the answer the whole time; only the memo was stale.

The consequence was total rather than subtle. With no ``output`` visible,
``Save Response`` falls back to the agent's own final text — and the protocol
makes that the literal word ``DONE``. Live on the BA Agent, every turn published
one word in place of a full analysis, recorded ``DONE`` as what the agent had
said, and fed that back as the next turn's history. Confirmed by tracing a real
turn: ``finalize`` wrote ``output`` to Redis and to its own memo, and the very
next read returned the pre-finalize keys.

Every agent sharing this store is exposed, which is why the guard belongs here.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_turn_state_reads_past_the_memo
"""

from __future__ import annotations

import pickle

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.turn_state import _key, clear_turn, get_turn, set_turn, update_turn

CONVERSATION = "_TestTurnStateMemo"
ANSWER = {"response": "A full reply, not the word DONE.", "stage": "architect"}


class TestGetTurnReadsPastTheMemo(FrappeTestCase):
    def setUp(self):
        clear_turn(CONVERSATION)

    def tearDown(self):
        clear_turn(CONVERSATION)

    def _write_behind_the_memo(self, turn):
        """Write straight to Redis, leaving this process's memo untouched.

        This is what a stage tool's write looked like from Save Response's point
        of view: present in Redis, absent from the local cache it would consult.
        """
        frappe.cache.set(frappe.cache.make_key(_key(CONVERSATION)), pickle.dumps(turn))

    def test_a_write_this_process_never_saw_is_still_read(self):
        set_turn(CONVERSATION, {"user_text": "hi"})
        get_turn(CONVERSATION)  # populates the memo with the pre-answer turn

        self._write_behind_the_memo(
            {"user_text": "hi", "output": ANSWER, "done": True}
        )

        turn = get_turn(CONVERSATION)
        self.assertEqual(turn.get("output"), ANSWER, "read the stale memo instead of Redis")
        self.assertTrue(turn.get("done"))

    def test_the_reply_survives_rather_than_falling_back_to_the_agents_text(self):
        """The specific failure this exists to prevent.

        Save Response takes ``output["response"]`` when it can see one, and the
        agent's own final text when it cannot. The protocol makes that text the
        single word DONE, so a stale read does not degrade the reply — it
        replaces it.
        """
        set_turn(CONVERSATION, {"user_text": "hi"})
        get_turn(CONVERSATION)

        self._write_behind_the_memo({"user_text": "hi", "output": ANSWER, "done": True})

        out = get_turn(CONVERSATION).get("output") or {}
        response = out.get("response") or "DONE"
        self.assertNotEqual(response, "DONE")
        self.assertEqual(response, ANSWER["response"])

    def test_update_turn_merges_onto_what_another_context_wrote(self):
        """A merge that reads the stale copy would drop the other write.

        ``update_turn`` reads before it merges, so a stale read does not just
        hide the answer — it overwrites it with a turn that never had one.
        """
        set_turn(CONVERSATION, {"user_text": "hi"})
        get_turn(CONVERSATION)

        self._write_behind_the_memo({"user_text": "hi", "output": ANSWER, "done": True})

        update_turn(CONVERSATION, classify_result={"intent": "architect"})

        turn = get_turn(CONVERSATION)
        self.assertEqual(turn.get("output"), ANSWER, "the merge clobbered the answer")
        self.assertEqual(turn.get("classify_result"), {"intent": "architect"})

    def test_a_missing_turn_is_still_an_empty_dict(self):
        """Bypassing the memo must not turn "no turn" into an error."""
        self.assertEqual(get_turn("_TestTurnStateMemoAbsent"), {})
