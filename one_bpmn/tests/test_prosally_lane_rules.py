"""
ProsAlly draws the lanes the designer asked for, and no others (WI-002042).

Asked for "3 lanes only: Recruiter, GRD Operator, GRD Manager", it produced four
— the extra being "System (Automatic)". The model was not guessing: that lane was
instructed in three places, the two sub-prompts and the generator tool's own
repair hint, which also rejected any IR with fewer than two lanes.

Lane fidelity is decided by a language model, so no test can prove the output.
What these tests pin is the instruction: the rule that makes a designer-named
lane set authoritative is present, nothing still orders an unconditional system
lane, and the tool no longer refuses a lane set smaller than two. When one of
those regresses, the extra lane comes back — that is the failure this catches.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_prosally_lane_rules
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

CONFIG = "prosally"
GENERATOR_TOOL = "ProsAlly – Tool Generate Process"


def _sub_prompt(sub_agent_id: str) -> str:
    doc = frappe.get_doc("AI Agent Configuration", CONFIG)
    for sp in doc.sub_prompts or []:
        if sp.sub_agent_id == sub_agent_id:
            return sp.prompt_text or ""
    return ""


class TestProsAllyLaneRules(FrappeTestCase):
    def setUp(self):
        if not frappe.db.exists("AI Agent Configuration", CONFIG):
            self.skipTest(f"{CONFIG} is not configured on this site")

    def test_generator_makes_a_named_lane_set_authoritative(self):
        text = _sub_prompt("process_generator")
        self.assertTrue(text, "process_generator sub-prompt is missing")
        self.assertIn("LANES THE DESIGNER NAMED WIN", text)

    def test_modifier_makes_a_named_lane_set_authoritative(self):
        text = _sub_prompt("modifier")
        self.assertTrue(text, "modifier sub-prompt is missing")
        self.assertIn("LANES THE DESIGNER NAMED WIN", text)

    def test_no_prompt_orders_an_unconditional_system_lane(self):
        """The three instructions that produced the extra lane. Each is allowed to
        MENTION the system lane — the new rules do, to forbid it — but none may
        still order one for every automated step."""
        banned = (
            'Any automated step (send email, validate, calculate, check, create record, notify) '
            '→ "System (Automatic)"',
            'Minimum: if only one human is mentioned, still add "System (Automatic)" as a second lane',
            'Automated steps → "system" lane, name "System (Automatic)".',
        )
        combined = _sub_prompt("process_generator") + "\n" + _sub_prompt("modifier")
        for order in banned:
            self.assertNotIn(order, combined, f"still instructs a system lane: {order[:60]!r}")

    def test_automated_steps_fall_back_to_the_responsible_role(self):
        """With no system lane, automated work still needs a home — otherwise the
        model either invents the lane again or leaves nodes unassigned, and an
        unassigned node is rejected by the pipeline."""
        text = _sub_prompt("process_generator")
        self.assertIn("the lane of\n                      the role responsible", text)

    def test_rework_converges_on_one_re_entry_point(self):
        for sub in ("process_generator", "modifier"):
            self.assertIn("REWORK LOOPS", _sub_prompt(sub), f"{sub} lost the rework rule")

    def test_generator_tool_accepts_a_lane_set_the_designer_asked_for(self):
        """It used to demand two or more lanes, so "1 lane only" could never be
        honoured and the model was pushed into inventing a second."""
        if not frappe.db.exists("Server Script", GENERATOR_TOOL):
            self.skipTest(f"{GENERATOR_TOOL} is not installed on this site")
        body = frappe.db.get_value("Server Script", GENERATOR_TOOL, "script") or ""
        self.assertNotIn("if len(_lanes) < 2:", body)
        self.assertIn("if len(_lanes) < 1:", body)
        self.assertIn("if the request NAMED the lanes", body)
