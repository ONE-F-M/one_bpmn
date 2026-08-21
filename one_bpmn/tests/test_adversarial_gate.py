# Copyright (c) 2026, one-fm and contributors
# No chat agent goes Live without a passing adversarial suite and a
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

from one_bpmn.agents.adversarial_gate import (
	check,
	ensure_fresh_runs,
	has_fresh_run,
	is_conversational,
	ungated_live_agents,
)
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

	def test_a_pass_older_than_the_suites_last_change_is_stale(self):
		"""A suite can be edited, or reassigned to a different agent. Either way
		the earlier run is no longer evidence about what is in front of you —
		without this, moving a reusable suite from a tested agent to an untested
		one carries the pass across and opens the gate for an agent nothing has
		ever attacked."""
		suite = self._suite()
		self._run(suite)  # a clean pass
		self.assertTrue(check(self.agent)["ok"], "a fresh pass should open the gate")

		# Touch the suite the way reassign_suite does (db_set bumps modified).
		frappe.db.set_value(
			"AI Eval Suite", suite, "modified",
			add_to_date(now_datetime(), minutes=5), update_modified=False,
		)

		gate = check(self.agent)
		self.assertFalse(gate["ok"])
		self.assertIn("before the suite was changed", gate["reason"])

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

	def test_the_marker_is_still_honoured_on_a_map_that_carries_it(self):
		"""Conformance no longer HUNTS for the marker, but an author who does put
		screening in a map keeps the recognition — the constants remain the
		published contract."""
		xml = f'<bpmn:definitions><bpmn:serviceTask id="a" spiffworkflow:{SCREENING_MARKER}="true" /></bpmn:definitions>'
		self.assertTrue(has_screening_stage(xml))

	def test_a_chat_map_without_a_screening_stage_still_conforms(self):
		"""The cloned template this check was written against was retired,
		and screening was never a map step — it runs centrally on every turn. No
		map on the site has ever carried the marker, so requiring one failed every
		agent for a declaration nothing produces."""
		xml = (
			'<bpmn:definitions><bpmn:startEvent id="s">'
			'<bpmn:conditionalEventDefinition spiffworkflow:triggerDoctype="Chat Conversation" />'
			"</bpmn:startEvent></bpmn:definitions>"
		)
		self.assertFalse(has_screening_stage(xml))
		self.assertTrue(validate_chat_map(self._map(xml))["ok"])

	def test_a_map_that_is_not_a_chat_map_does_not_conform(self):
		"""The thing a linked map can still get wrong: an agent with a chat mode
		label pointed at a business process can never receive a turn."""
		xml = '<bpmn:definitions><bpmn:startEvent id="s" /></bpmn:definitions>'
		result = validate_chat_map(self._map(xml))
		self.assertFalse(result["ok"])
		self.assertIn("not a chat map", result["errors"][0])

	def test_conformance_fails_closed_when_the_pack_is_empty(self):
		"""Screening that matches nothing is not screening."""
		from one_bpmn.agents.conformance import screening_status

		with patch.object(frappe.db, "count", return_value=0):
			result = screening_status()
		self.assertFalse(result["ok"])
		self.assertIn("no enabled rules", result["errors"][0])

	def test_conformance_fails_closed_when_the_hook_is_unwired(self):
		from one_bpmn.agents.conformance import screening_status
		from one_bpmn import hooks

		with patch.object(hooks, "doc_events", {"Chat Message": {"before_insert": "something.else"}}):
			result = screening_status()
		self.assertFalse(result["ok"])
		self.assertIn("not wired", result["errors"][0])

	def test_older_maps_are_recognised_by_element_id(self):
		"""Maps authored before the marker existed still conform."""
		xml = '<bpmn:definitions><bpmn:serviceTask id="screen_input_stage" name="Screen" /></bpmn:definitions>'
		self.assertTrue(has_screening_stage(xml))

	def test_the_marker_must_be_truthy(self):
		xml = f'<bpmn:definitions><bpmn:serviceTask id="a" spiffworkflow:{SCREENING_MARKER}="false" /></bpmn:definitions>'
		self.assertFalse(has_screening_stage(xml))

	def test_no_map_at_all_conforms(self):
		"""A chat agent may legitimately have no map — that is the Direct API
		path that was left in place — and screening does not live there anyway."""
		self.assertTrue(validate_chat_map(None)["ok"])

	def test_a_map_that_is_missing_or_empty_does_not_conform(self):
		"""Linking one and getting it wrong is still an error, unlike linking none."""
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
	# ------------------------------------------------------------------
	# The gate runs the suite itself
	# ------------------------------------------------------------------
	def test_a_suite_that_never_ran_is_not_fresh(self):
		self.assertFalse(has_fresh_run(self.agent, self._suite()))

	def test_a_run_after_the_last_change_is_fresh(self):
		suite = self._suite()
		self._run(suite)
		self.assertTrue(has_fresh_run(self.agent, suite))

	def test_a_run_before_the_last_change_is_not_fresh(self):
		suite = self._suite()
		self._run(suite, when=add_to_date(now_datetime(), minutes=-30))
		self._touch_agent()
		self.assertFalse(has_fresh_run(self.agent, suite))

	def test_the_gate_runs_a_suite_that_has_no_fresh_result(self):
		"""The gate used to only READ runs, so an agent was parked for a suite the
		process could perfectly well have executed itself — the designer had to go
		and press Run, then come back."""
		suite = self._suite()
		with patch("one_bpmn.agents.eval_runner._execute_eval_suite") as execute:
			ran = ensure_fresh_runs(self.agent)

		self.assertEqual(ran, [suite])
		self.assertTrue(execute.called, "the suite must actually be executed, not just recorded")
		self.assertEqual(
			frappe.db.count("AI Eval Run", {"suite": suite}), 1,
			"exactly one run — enqueuing as well would double-execute it",
		)

	def test_the_gate_does_not_re_run_a_suite_that_already_passed(self):
		"""Clicking again after a pass must cost nothing — these are real model
		calls, and re-running a clean pass would burn minutes and money."""
		suite = self._suite()
		self._run(suite)

		with patch("one_bpmn.agents.eval_runner._execute_eval_suite") as execute:
			ran = ensure_fresh_runs(self.agent)

		self.assertEqual(ran, [])
		self.assertFalse(execute.called)

	def test_a_suite_that_cannot_run_leaves_the_gate_closed(self):
		"""Fails in the safe direction: no fresh result means the gate refuses,
		rather than an exception taking the whole creation process down."""
		suite = self._suite()
		with patch(
			"one_bpmn.agents.eval_runner._execute_eval_suite", side_effect=RuntimeError("boom")
		), patch("frappe.log_error"):
			ran = ensure_fresh_runs(self.agent)

		self.assertEqual(ran, [], "a suite that blew up was not run")
		self.assertFalse(check(self.agent)["ok"], "and the gate stays shut")



class TestReReviewGoesThroughTheGate(FrappeTestCase):
	"""Disable / re-enable must not be a way around the gate.

	provision_agent is only reachable through the agent-creation process, which
	is not active on every site. The path a human actually takes — save the
	config, watch it heal from Needs Attention back to Live — ran on credentials
	alone. That is the "re-review" the story names, and it bypassed the gate
	entirely until this was added.
	"""

	def setUp(self):
		frappe.set_user("Administrator")
		self._cleanup()
		frappe.flags.test_agent_revalidation = True

	def tearDown(self):
		frappe.flags.test_agent_revalidation = False
		self._cleanup()
		frappe.db.commit()

	def _cleanup(self):
		frappe.db.delete("AI Agent Configuration", {"agent_name": ("like", f"{PREFIX}%")})

	def _agent(self, agent_type="Chat", status="Needs Attention"):
		doc = frappe.get_doc({
			"doctype": "AI Agent Configuration", "agent_name": f"{PREFIX} rr agent",
			"agent_id": "zz_wi1969_rr", "agent_type": agent_type,
			"agent_framework": "Direct API", "chat_mode_label": f"{PREFIX} RR", "enabled": 1,
		}).insert(ignore_permissions=True)
		frappe.db.set_value("AI Agent Configuration", doc.name, "lifecycle_status", status,
		                    update_modified=False)
		doc.reload()
		return doc

	def test_re_review_does_not_promote_from_the_controller(self):
		"""Going Live is the MAP's decision.

		The controller used to stamp Live itself when credentials revalidated,
		which made disable/re-enable a way around the adversarial gate. It now
		hands the agent back to the Agent Creation Process, which runs the gate
		as a step you can see in the diagram.
		"""
		doc = self._agent()
		frappe.flags.test_agent_revalidation = True
		try:
			with patch(
				"one_bpmn.agents.agent_provisioning.validate_agent_config",
				return_value={"ok": True, "errors": []},
			), patch(
				"one_bpmn.agents.agent_config_resolver._start_reprovision", return_value=True
			) as handoff:
				doc.revalidate_credentials_on_save()
		finally:
			frappe.flags.test_agent_revalidation = False

		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", doc.name, "lifecycle_status"),
			"Needs Attention",
			"the controller must not promote — only the map may",
		)
		self.assertTrue(handoff.called, "the agent must be handed to the creation process")

	def test_the_controller_no_longer_carries_a_gate_of_its_own(self):
		"""Two gates that can disagree is worse than one. The check lives in the
		map's Adversarial Gate step; the controller must not grow a second copy."""
		doc = self._agent()
		self.assertFalse(
			hasattr(doc, "_adversarial_block_reason"),
			"the doctype gate was removed on purpose — enforcement belongs in the map",
		)

	def test_an_already_live_agent_is_never_parked_by_the_gate(self):
		"""It governs entering Live, not staying there."""
		doc = self._agent(status="Live")
		before = frappe.db.get_value("AI Agent Configuration", doc.name, "lifecycle_status")
		check(doc.name)  # would report a problem, must not act on it
		after = frappe.db.get_value("AI Agent Configuration", doc.name, "lifecycle_status")
		self.assertEqual(before, after, "the gate must not demote a running agent")

	def test_a_chat_agent_is_conversational(self):
		self.assertTrue(is_conversational(self._agent().name))

	def test_a_chat_agent_without_a_label_yet_is_still_conversational(self):
		"""Agent type is the signal, not the label — a chat agent is gated
		before it has been given one."""
		doc = self._agent()
		frappe.db.set_value("AI Agent Configuration", doc.name, "chat_mode_label", "",
		                    update_modified=False)
		self.assertTrue(is_conversational(doc.name))

	def test_a_background_agent_is_not_conversational_even_with_a_label(self):
		"""Every agent type walks the creation map now, so the gate step is what
		scopes this to chat. A label on a Background agent is not a dependable
		signal — the doctype only enforces label uniqueness for chat agents — so
		it must not drag one into a gate about chat exposure."""
		doc = self._agent(agent_type="Background")
		frappe.db.set_value("AI Agent Configuration", doc.name, "chat_mode_label",
		                    f"{PREFIX} label", update_modified=False)
		self.assertFalse(is_conversational(doc.name))

	def test_an_unreadable_agent_is_treated_as_conversational(self):
		"""Fails closed: this feeds a release gate."""
		self.assertTrue(is_conversational("ZZ no such agent"))

	# ------------------------------------------------------------------
	# Re-running the checks without a sham edit
	# ------------------------------------------------------------------
	def test_rerun_refuses_an_agent_the_process_is_past(self):
		"""Live is already through, and Retired is a deliberate state the
		creation process must not resurrect."""
		from one_bpmn.agents.agent_provisioning import rerun_creation_process

		for status in ("Live", "Retired"):
			doc = self._agent(status=status)
			with self.assertRaises(frappe.ValidationError):
				rerun_creation_process(doc.name)
			self._cleanup()

	def test_rerun_hands_a_parked_agent_back_to_the_map(self):
		"""It decides nothing — whether the agent may go Live stays the map's
		call. This only asks the map to look again."""
		from one_bpmn.agents import agent_provisioning as AP

		doc = self._agent()
		with patch("one_bpmn.one_bpmn.trigger._maybe_send_message"), patch(
			"one_bpmn.agents.agent_config_resolver.get_creation_process_model",
			return_value="Some Creation Map",
		), patch(
			"one_bpmn.agents.agent_config_resolver._start_reprovision", return_value=True
		) as start:
			res = AP.rerun_creation_process(doc.name)

		self.assertTrue(res["ok"])
		self.assertEqual(res["action"], "started")
		self.assertTrue(start.called)
		self.assertEqual(
			frappe.db.get_value("AI Agent Configuration", doc.name, "lifecycle_status"),
			"Needs Attention",
			"asking for a re-run must not itself change the lifecycle",
		)

	def test_rerun_refuses_when_no_creation_process_is_deployed(self):
		from one_bpmn.agents import agent_provisioning as AP

		doc = self._agent()
		with patch(
			"one_bpmn.agents.agent_config_resolver.get_creation_process_model",
			return_value=None,
		):
			with self.assertRaises(frappe.ValidationError):
				AP.rerun_creation_process(doc.name)

	def test_the_gate_library_does_not_second_guess_agent_type(self):
		"""Conversational exposure is what the gate is about, but WHICH agents
		are subject to it is the map's call — its start condition is
		agent_type=="Chat", so a Background agent never enters the process.
		check() stays agent-type-agnostic so that decision lives in one place
		(the diagram) instead of being duplicated here and silently diverging.
		"""
		doc = self._agent(agent_type="Background")
		self.assertFalse(check(doc.name)["ok"])


class TestAdversarialPack(FrappeTestCase):
	"""The shipped case pack. A gate is only real if writing the suite is easy."""

	def setUp(self):
		frappe.set_user("Administrator")
		self._cleanup()
		self.agent = frappe.get_doc({
			"doctype": "AI Agent Configuration", "agent_name": f"{PREFIX} pack agent",
			"agent_id": "zz_wi1969_pack", "agent_type": "Chat",
			"agent_framework": "Direct API", "chat_mode_label": f"{PREFIX} Pack", "enabled": 1,
		}).insert(ignore_permissions=True).name

	def tearDown(self):
		self._cleanup()
		frappe.db.commit()

	def _cleanup(self):
		suites = frappe.get_all("AI Eval Suite", filters={"title": ("like", f"%{PREFIX}%")}, pluck="name")
		if suites:
			frappe.db.delete("AI Eval Case", {"suite": ("in", suites)})
			frappe.db.delete("AI Eval Suite", {"name": ("in", suites)})
		frappe.db.delete("AI Agent Configuration", {"agent_name": ("like", f"{PREFIX}%")})

	def test_building_a_suite_covers_every_attack_family(self):
		from one_bpmn.agents.adversarial_pack import BENIGN_CASES, CASES, build_suite_for_agent

		result = build_suite_for_agent(self.agent)
		self.assertTrue(result["created_suite"])
		# Attacks AND benign controls: the rates need both kinds present or
		# the false-positive rate has no denominator, so the pack seeds the
		# controls rather than leaving them to be written by hand.
		self.assertEqual(result["cases_total"], len(CASES) + len(BENIGN_CASES))

		titles = " ".join(frappe.get_all("AI Eval Case", filters={"suite": result["suite"]}, pluck="title")).lower()
		for family in ("instruction override", "system prompt extraction", "jailbreak",
		               "delimiter injection", "exfiltration", "tool coercion"):
			self.assertIn(family, titles, f"the pack must cover {family}")

	def test_the_pack_seeds_benign_controls_labelled_as_such(self):
		"""Without these the suite can only report how often an attack succeeded,
		which on its own always argues for screening harder — a control that
		refuses everything would score perfectly."""
		from one_bpmn.agents.adversarial_pack import BENIGN_CASES, CASES, build_suite_for_agent

		suite = build_suite_for_agent(self.agent)["suite"]
		kinds = frappe.get_all("AI Eval Case", filters={"suite": suite}, fields=["case_kind"], limit_page_length=0)
		counted = [k["case_kind"] for k in kinds]

		self.assertEqual(counted.count("Attack"), len(CASES))
		self.assertEqual(counted.count("Benign Control"), len(BENIGN_CASES))

	def test_the_suite_is_marked_adversarial_and_gates_deployment(self):
		from one_bpmn.agents.adversarial_pack import build_suite_for_agent

		suite = build_suite_for_agent(self.agent)["suite"]
		row = frappe.db.get_value("AI Eval Suite", suite, ["suite_type", "gate_deployment"], as_dict=True)
		self.assertEqual(row.suite_type, "Adversarial")
		self.assertTrue(row.gate_deployment)

	def test_every_case_is_judged_rather_than_keyword_matched(self):
		"""A refusal has a thousand phrasings; 'contains' would be fragile."""
		from one_bpmn.agents.adversarial_pack import build_suite_for_agent

		suite = build_suite_for_agent(self.agent)["suite"]
		for case in frappe.get_all("AI Eval Case", filters={"suite": suite}, pluck="name"):
			doc = frappe.get_doc("AI Eval Case", case)
			self.assertTrue(doc.assertions, f"{doc.title} has no assertion")
			for a in doc.assertions:
				self.assertEqual(a.assertion_type, "llm_judge")
				self.assertTrue(a.judge_model, "an llm_judge assertion needs a judge model")
				self.assertTrue(1 <= a.pass_threshold <= 5)

	def test_building_twice_adds_nothing(self):
		from one_bpmn.agents.adversarial_pack import build_suite_for_agent

		first = build_suite_for_agent(self.agent)
		second = build_suite_for_agent(self.agent)
		self.assertEqual(first["suite"], second["suite"])
		self.assertEqual(second["cases_added"], 0)
		self.assertEqual(second["cases_total"], first["cases_total"])

	def test_building_a_suite_does_not_make_the_agent_pass(self):
		"""A gate satisfied by a result nobody produced is not a gate."""
		from one_bpmn.agents.adversarial_pack import build_suite_for_agent

		build_suite_for_agent(self.agent)
		result = check(self.agent)
		self.assertFalse(result["ok"])
		self.assertIn("never run", result["reason"].lower())
