# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class AIEvalCase(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        from one_bpmn.one_bpmn.doctype.ai_eval_assertion.ai_eval_assertion import AIEvalAssertion

        assertions: DF.Table[AIEvalAssertion]
        backend: DF.Literal["direct_api", "antigravity"]
        bpmn_id: DF.Data | None
        expected_output: DF.LongText | None
        input_context: DF.JSON | None
        input_system_prompt: DF.LongText | None
        input_user_prompt: DF.LongText
        model: DF.Data
        process_model: DF.Link | None
        provider: DF.Link
        source_run: DF.Link | None
        suite: DF.Link | None
        title: DF.Data
    # end: auto-generated types

    def validate(self):
        self._validate_assertions()
        self._validate_tool_call_assertions()

    def _validate_tool_call_assertions(self):
        """A tool_calls assertion needs a mode, expected calls, and — where the
        agent can act on the world — an order to check.

        ANY_ORDER says nothing about sequence, which is fine for a read-only
        lookup and not fine for a skill that is allowed to act: reviewing after
        writing is not the same as reviewing before it, and only the order shows
        which happened.
        """
        from one_bpmn.agents.eval_runner import TOOL_CALL_MODES

        rows = [r for r in self.assertions if r.assertion_type == "tool_calls"]
        if not rows:
            return

        for idx, row in enumerate(rows, start=1):
            mode = (row.value or "").strip().upper()
            if mode not in TOOL_CALL_MODES:
                frappe.throw(
                    _("tool_calls assertion {0}: the value must be one of {1}.").format(
                        idx, ", ".join(TOOL_CALL_MODES)
                    ),
                    title=_("Invalid Tool Call Mode"),
                )
            if not self.expected_tool_calls:
                frappe.throw(
                    _("tool_calls assertion {0} has nothing to check — add Expected Tool Calls.").format(idx),
                    title=_("No Expected Tool Calls"),
                )
            if mode == "ANY_ORDER" and self._acts_on_the_world():
                frappe.throw(
                    _(
                        "This case tests something that is allowed to act, so its tool calls must be "
                        "checked in order. Use EXACT or IN_ORDER."
                    ),
                    title=_("Order Required"),
                )

        # Rows reach here as child Documents from a save, and as plain dicts
        # from a caller that assigned the table directly. `.get` reads both;
        # attribute access reads only the first, and blows up on the second.
        for idx, row in enumerate(self.expected_tool_calls, start=1):
            argument = (row.get("argument") or "").strip()
            if argument and not (row.get("expected_value") or "").strip():
                frappe.throw(
                    _("Expected call {0}: argument {1} has no value to match against.").format(
                        idx, argument
                    ),
                    title=_("Missing Expected Value"),
                )

    def _acts_on_the_world(self) -> bool:
        """Is this case testing an Action-Allowed skill, or an agent that has one?"""
        if self.target_skill:
            if frappe.db.get_value("AI Skill", self.target_skill, "tier") == "Action-Allowed":
                return True

        agent = frappe.db.get_value("AI Eval Suite", self.suite, "agent_configuration") if self.suite else None
        if not agent:
            return False

        enabled = frappe.get_all(
            "AI Agent Enabled Skill",
            filters={"parent": agent, "parenttype": "AI Agent Configuration"},
            pluck="skill",
        )
        if not enabled:
            return False
        return bool(
            frappe.db.exists("AI Skill", {"name": ["in", enabled], "tier": "Action-Allowed"})
        )

    def _validate_assertions(self):
        """Validate assertion rules — llm_judge assertions need judge config."""
        for idx, row in enumerate(self.assertions, start=1):
            if row.assertion_type != "llm_judge":
                continue

            if not row.judge_provider:
                frappe.throw(
                    _("Row {0}: Judge Provider is required for llm_judge assertions.").format(idx),
                    title=_("Missing Judge Provider"),
                )

            if not row.judge_model:
                frappe.throw(
                    _("Row {0}: Judge Model is required for llm_judge assertions.").format(idx),
                    title=_("Missing Judge Model"),
                )

            if row.pass_threshold is None:
                row.pass_threshold = 4

            if not 1 <= row.pass_threshold <= 5:
                frappe.throw(
                    _("Row {0}: Pass Threshold must be between 1 and 5.").format(idx),
                    title=_("Invalid Pass Threshold"),
                )
