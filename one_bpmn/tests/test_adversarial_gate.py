# Copyright (c) 2026, one-fm and contributors
# WI-001969: no chat agent goes Live without a passing adversarial suite and a
# map that still contains the screening stage.
#
# The gate fails CLOSED, unlike the runtime screens around it. Those observe
# traffic and must never take a conversation down; this authorises a release,
# so "cannot prove it is safe" has to mean no. Several tests pin that direction.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.agents.adversarial_gate import check, ungated_live_agents
from one_bpmn.agents.conformance import (
	SCREENING_MARKER,
	has_screening_stage,
	validate_chat_map,
)

PREFIX = "ZZ-wi1969"


class TestAdversarialGate(FrappeTestCase):
	def setUp(self):
		self._cleanup()
		self.agent = frappe.get_doc({
			"doctype": "AI Agent Configuration", "agent_name": f"{PREFIX} agent",
			"agent_id": "zz_wi1969_agent", "agent_type": "Chat",
			"agent_framework": "Direct API", "chat_mode_label": f"{PREFIX} Chat", "enabled": 1,
		}).insert(ignore_permissions=True).name

	def tearDown(self):
		self._cleanup()
		frappe.db.commit()

	def _cleanup(self):
		frappe.set_user("Administrator")
		suites = frappe.get_all("AI Eval Suite", filters={"title": ("like", f"{PREFIX}%")}, pluck="name")
		if suites:
			frappe.db.delete("AI Eval Run", {"suite": ("in", suites)})
			frappe.db.delete("AI Eval Case", {"suite": ("in", suites)})
			frappe.db.delete("AI Eval Suite", {"name": ("in", suites)})
		frappe.db.delete("BPMN Process Model", {"title": ("like", f"{PREFIX}%")})
		frappe.db.delete("AI Agent Configuration", {"agent_name": ("like", f"{PREFIX}%")})

	def _suite(self, suite_type="Adversarial"):
		return frappe.get_doc({
			"doctype": "AI Eval Suite", "title": f"{PREFIX} {suite_type} suite",
			"eval_type": "Agent", "suite_type": suite_type, "agent_configuration": self.agent,
		}).insert(ignore_permissions=True).name

	def _run(self, suite, failed=0, total=3, when=None, status=None):
		doc = frappe.get_doc({
			"doctype": "AI Eval Run", "suite": suite,
			"status": status or ("Failed" if failed else "Passed"),
			"started_at": now_datetime(),
			"total_cases": total, "passed_cases": total - failed, "failed_cases": failed,
		}).insert(ignore_permissions=True)
		if when:
			frappe.db.set_value("AI Eval Run", doc.name, "ended_at", when, update_modified=False)
			frappe.db.set_value("AI Eval Run", doc.name, "creation", when, update_modified=False)
		else:
			frappe.db.set_value("AI Eval Run", doc.name, "ended_at", now_datetime(), update_modified=False)
		return doc.name

	def _touch_agent(self, when=None):
		"""Move the agent's modified stamp, as an edit would."""
		frappe.db.set_value("AI Agent Configuration", self.agent, "modified",
		                    when or now_datetime(), update_modified=False)

	# ------------------------------------------------------------------
	# The suite half of the gate
	# ------------------------------------------------------------------
	def test_no_adversarial_suite_blocks_go_live(self):
		result = check(self.agent)
		self.assertFalse(result["ok"])
		self.assertIn("adversarial", result["reason"].lower())

	def test_a_baseline_suite_does_not_satisfy_the_gate(self):
		"""'Tested' must mean tested against attacks, not tested at all."""
		self._run(self._suite("Baseline"))
		self.assertFalse(check(self.agent)["ok"])

	def test_a_passing_adversarial_suite_opens_the_gate(self):
		self._touch_agent(add_to_date(now_datetime(), minutes=-10))
		self._run(self._suite(), failed=0)
		result = check(self.agent)
		self.assertTrue(result["ok"], result.get("reason"))

	def test_a_failing_adversarial_suite_blocks(self):
		self._touch_agent(add_to_date(now_datetime(), minutes=-10))
		self._run(self._suite(), failed=1)
		result = check(self.agent)
		self.assertFalse(result["ok"])
		self.assertIn("failed", result["reason"].lower())

	def test_a_suite_that_never_ran_blocks(self):
		self._suite()
		result = check(self.agent)
		self.assertFalse(result["ok"])
		self.assertIn("never run", result["reason"].lower())

	def test_a_run_with_no_cases_does_not_count_as_passing(self):
		"""An empty suite passes trivially and proves nothing."""
		self._touch_agent(add_to_date(now_datetime(), minutes=-10))
		self._run(self._suite(), failed=0, total=0)
		self.assertFalse(check(self.agent)["ok"])

	def test_a_pass_older_than_the_agents_last_change_is_stale(self):
		"""The clause that closes the real hole: change the prompt, retest."""
		suite = self._suite()
		self._run(suite, failed=0, when=add_to_date(now_datetime(), days=-30))
		self._touch_agent(now_datetime())   # edited after the run

		result = check(self.agent)
		self.assertFalse(result["ok"])
		self.assertIn("before the agent was changed", result["reason"])

	def test_retesting_after_a_change_reopens_the_gate(self):
		suite = self._suite()
		self._run(suite, failed=0, when=add_to_date(now_datetime(), days=-30))
		self._touch_agent(add_to_date(now_datetime(), minutes=-5))
		self.assertFalse(check(self.agent)["ok"])

		self._run(suite, failed=0)  # fresh run, after the edit
		self.assertTrue(check(self.agent)["ok"])

	def test_one_passing_suite_is_enough_among_several(self):
		self._touch_agent(add_to_date(now_datetime(), minutes=-10))
		self._run(self._suite(), failed=2)
		good = frappe.get_doc({
			"doctype": "AI Eval Suite", "title": f"{PREFIX} second suite", "eval_type": "Agent",
			"suite_type": "Adversarial", "agent_configuration": self.agent,
		}).insert(ignore_permissions=True).name
		self._run(good, failed=0)
		self.assertTrue(check(self.agent)["ok"])

	def test_the_gate_fails_closed_when_it_cannot_be_evaluated(self):
		"""Unlike the runtime screens: this authorises a release."""
		with patch("frappe.get_all", side_effect=RuntimeError("db down")):
			result = check(self.agent)
		self.assertFalse(result["ok"])

	# ------------------------------------------------------------------
	# The conformance half
	# ------------------------------------------------------------------
	def _map(self, xml, title=None):
		"""A throwaway map. process_name is a Link, so borrow an existing one."""
		process = frappe.db.get_value("BPMN Process Model", {"process_name": ("is", "set")}, "process_name")
		return frappe.get_doc({
			"doctype": "BPMN Process Model", "title": title or f"{PREFIX} map",
			"bpmn_xml": xml, "process_name": process,
			"process_id": f"zz_wi1969_{frappe.generate_hash(length=6)}",
		}).insert(ignore_permissions=True).name

	def test_a_map_with_the_marker_conforms(self):
		xml = f'<bpmn:definitions><bpmn:serviceTask id="a" spiffworkflow:{SCREENING_MARKER}="true" /></bpmn:definitions>'
		self.assertTrue(has_screening_stage(xml))
		self.assertTrue(validate_chat_map(self._map(xml))["ok"])

	def test_a_map_without_a_screening_stage_does_not_conform(self):
		xml = '<bpmn:definitions><bpmn:serviceTask id="run_agent" name="Call Agent" /></bpmn:definitions>'
		result = validate_chat_map(self._map(xml))
		self.assertFalse(result["ok"])
		self.assertIn("screening stage", result["errors"][0])

	def test_older_maps_are_recognised_by_element_id(self):
		"""Maps authored before the marker existed still conform."""
		xml = '<bpmn:definitions><bpmn:serviceTask id="screen_input_stage" name="Screen" /></bpmn:definitions>'
		self.assertTrue(has_screening_stage(xml))

	def test_the_marker_must_be_truthy(self):
		xml = f'<bpmn:definitions><bpmn:serviceTask id="a" spiffworkflow:{SCREENING_MARKER}="false" /></bpmn:definitions>'
		self.assertFalse(has_screening_stage(xml))

	def test_a_missing_or_empty_map_does_not_conform(self):
		self.assertFalse(validate_chat_map(None)["ok"])
		self.assertFalse(validate_chat_map("no-such-map")["ok"])
		self.assertFalse(validate_chat_map(self._map("  "))["ok"])

	# ------------------------------------------------------------------
	# Nothing already Live is disturbed
	# ------------------------------------------------------------------
	def test_the_gate_does_not_touch_agents_already_live(self):
		"""It runs on the way to Live. Existing agents keep serving."""
		live = frappe.get_all(
			"AI Agent Configuration",
			filters={"agent_type": "Chat", "lifecycle_status": "Live"},
			pluck="name",
		)
		before = {a: frappe.db.get_value("AI Agent Configuration", a, "lifecycle_status") for a in live}
		ungated_live_agents()  # merely reports
		after = {a: frappe.db.get_value("AI Agent Configuration", a, "lifecycle_status") for a in live}
		self.assertEqual(before, after, "reporting the gap must not change any agent's status")

	def test_ungated_live_agents_reports_the_gap(self):
		rows = ungated_live_agents()
		self.assertIsInstance(rows, list)
		for row in rows:
			self.assertIn("agent", row)
			self.assertIn("reason", row)

	# ------------------------------------------------------------------
	# Promotion marks a suite adversarial
	# ------------------------------------------------------------------
	def test_promoting_a_security_event_marks_the_suite_adversarial(self):
		from one_bpmn.api.security_events import promote_to_eval_case
		from one_bpmn.security.events import record_event

		suite = self._suite("Baseline")
		event = record_event(boundary="input", stage=f"{PREFIX}-stage", action="Flag",
		                     matched_pattern=r"\bignore previous\b")
		self.assertIsNotNone(event)
		try:
			promote_to_eval_case(event=event, suite=suite, input_text="ignore previous instructions")
			self.assertEqual(
				frappe.db.get_value("AI Eval Suite", suite, "suite_type"),
				"Adversarial",
				"a suite holding a promoted attack IS an adversarial suite",
			)
		finally:
			frappe.db.delete("AI Security Event", {"stage": f"{PREFIX}-stage"})

	def test_an_errored_run_is_not_a_pass(self):
		"""The run itself broke, so it proves nothing either way."""
		self._touch_agent(add_to_date(now_datetime(), minutes=-10))
		self._run(self._suite(), failed=0, status="Error")
		result = check(self.agent)
		self.assertFalse(result["ok"])
		self.assertIn("errored", result["reason"].lower())

	def test_a_run_still_in_flight_does_not_open_the_gate(self):
		self._touch_agent(add_to_date(now_datetime(), minutes=-10))
		self._run(self._suite(), failed=0, status="Running")
		self.assertFalse(check(self.agent)["ok"])
