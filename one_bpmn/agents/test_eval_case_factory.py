# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The starter assertion on a case built from a run (WI-001751 follow-up).

"Create case from run" copied a prompt and a reference answer and stopped there,
so the new case had no assertions — and a case with no assertions passes
trivially. The feature produced a green tick that proved nothing until somebody
noticed and wrote a rubric by hand.

It now seeds one llm_judge assertion scoring a future reply against the captured
output. These tests pin when that happens, when it deliberately does not, and
that the rubric carries the reference rather than merely mentioning it.
"""
from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from one_bpmn.agents._eval_test_factories import make_agent_configuration, make_eval_suite
from one_bpmn.agents.eval_case_factory import (
    _MAX_REFERENCE_CHARS,
    _STARTER_PASS_THRESHOLD,
    _starter_judge_assertion,
    create_eval_case_from_run,
)


class TestStarterAssertion(FrappeTestCase):
    def setUp(self):
        self.credentials = self._make_credentials()

    # ── fixtures ────────────────────────────────────────────────────────────
    def _make_credentials(self):
        doc = frappe.get_doc({
            "doctype": "AI Provider Credentials",
            "provider_name": f"_Test Judge Creds {frappe.generate_hash(length=6)}",
            "provider_type": "Anthropic",
            "api_key": "sk-test-not-a-real-key",
            "enabled": 1,
        })
        doc.flags.ignore_mandatory = True
        return doc.insert(ignore_permissions=True).name

    def _make_model(self):
        doc = frappe.get_doc({
            "doctype": "AI Model",
            "model_name": f"_test-judge-{frappe.generate_hash(length=6)}",
            "ai_provider_credentials": self.credentials,
        })
        doc.flags.ignore_mandatory = True
        doc.flags.ignore_links = True
        return doc.insert(ignore_permissions=True).name

    def _suite_for(self, **agent_kwargs):
        agent = make_agent_configuration(
            ai_provider_credentials=self.credentials, **agent_kwargs
        )
        return make_eval_suite(agent_configuration=agent.name).name

    def _make_run(self, user_prompt: str, final_output: str):
        run = frappe.get_doc({
            "doctype": "AI Agent Run",
            "bpmn_id": "Activity_test",
            "status": "Success",
            "started_at": now_datetime(),
            "element_type": "task",
            "final_output": final_output,
        })
        run.flags.ignore_mandatory = True
        run.flags.ignore_links = True
        run.insert(ignore_permissions=True)

        step = frappe.get_doc({
            "doctype": "AI Agent Step",
            "run": run.name,
            "step_index": 1,
            "role": "user",
            "content": user_prompt,
        })
        step.flags.ignore_mandatory = True
        step.flags.ignore_links = True
        step.insert(ignore_permissions=True)
        return run.name

    # ── when an assertion IS seeded ─────────────────────────────────────────
    def test_uses_the_agents_own_judge_model(self):
        model = self._make_model()
        suite = self._suite_for(ai_model=model)

        assertion = _starter_judge_assertion("The leave is 5 days.", suite)

        self.assertIsNotNone(assertion)
        self.assertEqual(assertion["assertion_type"], "llm_judge")
        self.assertEqual(assertion["judge_model"], model)
        self.assertEqual(assertion["judge_provider"], self.credentials)
        self.assertEqual(assertion["pass_threshold"], _STARTER_PASS_THRESHOLD)

    def test_rubric_carries_the_reference_answer(self):
        """The rubric has to CONTAIN the reference — a rubric that only refers
        to it gives the judge nothing to compare against."""
        self._make_model()
        suite = self._suite_for()

        assertion = _starter_judge_assertion("Total leave days: 5", suite)

        self.assertIn("Total leave days: 5", assertion["value"])

    def test_falls_back_to_a_catalog_model_for_a_legacy_agent(self):
        """An agent predating WI-001655 has no ai_model — and those are exactly
        the cases that most need an assertion, so a judge is still resolved."""
        model = self._make_model()
        suite = self._suite_for()  # no ai_model
        self.assertFalse(
            frappe.db.get_value(
                "AI Agent Configuration",
                frappe.db.get_value("AI Eval Suite", suite, "agent_configuration"),
                "ai_model",
            )
        )

        assertion = _starter_judge_assertion("anything", suite)

        self.assertEqual(assertion["judge_model"], model)

    def test_long_reference_is_truncated_and_says_so(self):
        """A 64KB final_output would make an unaffordable prompt. Truncating
        silently would have the judge scoring against half an expectation."""
        self._make_model()
        suite = self._suite_for()

        assertion = _starter_judge_assertion("x" * (_MAX_REFERENCE_CHARS + 500), suite)

        self.assertIn("truncated", assertion["value"].lower())
        self.assertLess(len(assertion["value"]), _MAX_REFERENCE_CHARS + 800)

    # ── when it deliberately is NOT seeded ──────────────────────────────────
    def test_none_without_a_reference_answer(self):
        self._make_model()
        suite = self._suite_for()
        self.assertIsNone(_starter_judge_assertion("", suite))
        self.assertIsNone(_starter_judge_assertion("   ", suite))

    def test_none_for_a_failed_run(self):
        """A case from a FAILED run is a regression test: the captured behaviour
        must not recur. "Match the reference" would assert the opposite."""
        self._make_model()
        suite = self._suite_for()

        self.assertIsNone(
            _starter_judge_assertion("a broken answer", suite, run_status="Error")
        )
        # Success is what earns the baseline rubric.
        self.assertIsNotNone(
            _starter_judge_assertion("a good answer", suite, run_status="Success")
        )

    def test_rubric_says_it_is_only_a_baseline(self):
        """The rubric treats the captured output as the standard. Left unsaid,
        that reads as a correctness check and quietly enshrines any flaw."""
        self._make_model()
        suite = self._suite_for()

        rubric = _starter_judge_assertion("some answer", suite)["value"]

        self.assertIn("BASELINE CHECK", rubric)
        self.assertIn("not been reviewed for correctness", rubric)

    def test_none_without_a_suite(self):
        """A suite-less case has no agent to borrow a judge model from."""
        self.assertIsNone(_starter_judge_assertion("something", None))

    def test_none_when_no_model_can_be_resolved(self):
        """Better a case the designer must finish than an llm_judge assertion
        that errors on every run for want of a judge model."""
        suite = self._suite_for()  # credentials exist, but no AI Model links them
        self.assertIsNone(_starter_judge_assertion("something", suite))

    # ── end to end ──────────────────────────────────────────────────────────
    def test_case_from_run_is_a_real_test_on_creation(self):
        self._make_model()
        suite = self._suite_for()
        run = self._make_run("Summarise this leave application.", "John took 5 days.")

        case = create_eval_case_from_run(run_name=run, suite=suite)

        doc = frappe.get_doc("AI Eval Case", case)
        self.assertEqual(len(doc.assertions), 1)
        self.assertEqual(doc.assertions[0].assertion_type, "llm_judge")
        self.assertIn("John took 5 days.", doc.assertions[0].value)
        self.assertEqual(doc.source_run, run)

    def test_opt_out_leaves_the_bare_prefill(self):
        self._make_model()
        suite = self._suite_for()
        run = self._make_run("Summarise this.", "A summary.")

        case = create_eval_case_from_run(
            run_name=run, suite=suite, add_starter_assertion=False
        )

        self.assertEqual(len(frappe.get_doc("AI Eval Case", case).assertions), 0)
