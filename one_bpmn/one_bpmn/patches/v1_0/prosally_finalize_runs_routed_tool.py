"""ProsAlly finalize runs the routed redirect or clarify stage itself (WI-000286).

In run i5car8itak the orchestrator called finalize directly after classify_intent routed the turn to
redirect, so no stage answered and finalize fell back to the generic clarify question.

When classify_intent routed the turn to redirect (intent IRRELEVANT) or clarify (intent AMBIGUOUS or
INCOMPLETE) and no other stage ran (the turn is not done), finalize now calls the same shared helper
the stage tool uses (prosally_helpers.redirect_output / clarify_output), replies with its text, and
records which tool it ran in result["ran_tool"]. Turns that a stage already answered are unchanged.

Idempotent: _edit_script applies the block only once.
"""

from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import _edit_script

FINALIZE_ANCHOR = 'else:\n    output = {\n        "intent": "CLARIFY",'

ROUTED_ELIFS = (
    'elif turn.get("intent") == "IRRELEVANT" and not turn.get("done"):\n'
    "    from one_bpmn.agents.prosally_helpers import redirect_output\n"
    "    _routed = redirect_output(context_docname)\n"
    '    result["response"] = _routed.get("response", "")\n'
    '    result["options"] = _routed.get("options") or []\n'
    '    result["ran_tool"] = "redirect"\n'
    '    result["finalized"] = True\n'
    'elif turn.get("intent") in ("AMBIGUOUS", "INCOMPLETE") and not turn.get("done"):\n'
    "    from one_bpmn.agents.prosally_helpers import clarify_output\n"
    "    _routed = clarify_output(context_docname)\n"
    '    result["response"] = _routed.get("response", "")\n'
    '    result["options"] = _routed.get("options") or []\n'
    '    result["ran_tool"] = "clarify"\n'
    '    result["finalized"] = True\n'
)

# The routing chain as it reads once patched, for the unit tests. The real finalize script gets
# ROUTED_ELIFS inserted above its generic fallback branch.
FINALIZE = (
    "from one_bpmn.agents.turn_state import get_turn\n"
    "turn = get_turn(context_docname)\n"
    "if False:\n"
    "    pass\n" + ROUTED_ELIFS + "else:\n"
    '    result["fallback"] = True\n'
    '    result["finalized"] = True\n'
)


def execute():
    _edit_script("prosally_tool_finalize", FINALIZE_ANCHOR, ROUTED_ELIFS + FINALIZE_ANCHOR)
