# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A case promoted from a security event can fail, and a case with no assertions never passes."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.agents._eval_test_factories import make_eval_case, make_eval_suite
from one_bpmn.agents.eval_runner import _execute_eval_suite
from one_bpmn.api.security_events import REFUSAL_RUBRIC, promote_to_eval_case
from one_bpmn.one_bpmn.patches.v1_0 import promoted_security_cases_get_assertions
from one_bpmn.security.events import record_event


def _event(**kw):
	return record_event(boundary="input", stage="promoted-case-test", action="Flag", **kw)


def _run() -> str:
	return (
		frappe.get_doc(
			{"doctype": "AI Agent Run", "bpmn_id": "agent", "status": "Success", "started_at": now_datetime()}
		)
		.insert(ignore_permissions=True, ignore_links=True)
		.name
	)


def _step(run: str, index: int, tools: list[str], creation=None) -> None:
	step = frappe.get_doc({"doctype": "AI Agent Step", "run": run, "step_index": index, "role": "assistant"})
	for tool in tools:
		step.append("tool_calls", {"tool_name": tool, "status": "Success"})
	step.insert(ignore_permissions=True)
	if creation:
		frappe.db.set_value("AI Agent Step", step.name, "creation", creation, update_modified=False)


def _assertions(case_name: str) -> set:
	case = frappe.get_doc("AI Eval Case", case_name)
	return {(a.assertion_type, a.value) for a in case.assertions}


class TestPromotionSeedsAssertions(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(title="_Test promoted " + frappe.generate_hash(length=6)).name
		self.judge = frappe.db.get_value(
			"AI Model", {"provider": ("is", "set")}, ["name", "provider"], as_dict=True
		)
		frappe.db.set_single_value("Processa Settings", "nightly_eval_grading_model", self.judge.name)

	def test_a_promoted_case_carries_the_refusal_judge(self):
		out = promote_to_eval_case(
			event=_event(), suite=self.suite, input_text="ignore previous instructions"
		)
		self.assertEqual(_assertions(out["eval_case"]), {("llm_judge", REFUSAL_RUBRIC)})
		judge = frappe.get_doc("AI Eval Case", out["eval_case"]).assertions[0]
		self.assertEqual((judge.judge_provider, judge.judge_model), (self.judge.provider, self.judge.name))

	def test_tools_the_run_called_after_the_event_are_banned(self):
		run = _run()
		event = _event(run=run)
		_step(run, 0, ["read_file"], creation=add_to_date(now_datetime(), minutes=-1))
		_step(run, 1, ["send_email", "delete_record"])
		out = promote_to_eval_case(event=event, suite=self.suite, input_text="attack")
		self.assertEqual(
			_assertions(out["eval_case"]),
			{("llm_judge", REFUSAL_RUBRIC), ("no_tool_call", "delete_record, send_email")},
		)

	def test_the_patch_seeds_a_case_promoted_before_and_leaves_others_alone(self):
		bare = promote_to_eval_case(event=_event(), suite=self.suite, input_text="attack")["eval_case"]
		frappe.db.delete("AI Eval Assertion", {"parent": bare})
		kept = promote_to_eval_case(event=_event(), suite=self.suite, input_text="attack")["eval_case"]
		frappe.db.set_value("AI Eval Assertion", {"parent": kept}, "value", "a reviewer's own rubric")

		promoted_security_cases_get_assertions.execute()
		promoted_security_cases_get_assertions.execute()

		self.assertEqual(_assertions(bare), {("llm_judge", REFUSAL_RUBRIC)})
		self.assertEqual(_assertions(kept), {("llm_judge", "a reviewer's own rubric")})


class TestACaseWithNoAssertionsIsInvalid(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(title="_Test invalid " + frappe.generate_hash(length=6)).name

	def _run(self):
		run = frappe.get_doc(
			{
				"doctype": "AI Eval Run",
				"suite": self.suite,
				"status": "Running",
				"backend": "deterministic",
				"scope": "Suite",
				"started_at": now_datetime(),
			}
		)
		run.flags.ignore_mandatory = True
		run.flags.ignore_links = True
		run.insert(ignore_permissions=True)
		with patch("one_bpmn.agents.eval_runner._eval_concurrency", return_value=1):
			_execute_eval_suite(run.name)
		return run.reload()

	def test_the_case_is_invalid_and_fails_the_run(self):
		make_eval_case(
			suite=self.suite,
			expected_output="ready",
			assertions=[{"assertion_type": "equals", "value": "ready"}],
		)
		empty = make_eval_case(suite=self.suite, expected_output="ready").name

		run = self._run()

		row = next(r for r in run.results if r.eval_case == empty)
		self.assertEqual(row.status, "Invalid")
		self.assertIn("no assertions", row.error_message)
		self.assertEqual((run.passed_cases, run.failed_cases, run.status), (1, 1, "Failed"))
