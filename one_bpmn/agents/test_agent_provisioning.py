# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Tests for baseline eval-suite generation during agent provisioning.

Regression cover for the suite lookup: AI Eval Suite is ``autoname: hash``, so
checking ``frappe.db.exists("AI Eval Suite", suite_title)`` never matched and
every re-provision inserted another "<agent> — Baseline" suite. Re-generating
must reuse the agent's existing baseline suite and replace its cases.
"""
from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.agent_provisioning import generate_eval_suite_for_agent


class TestGenerateEvalSuiteForAgent(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# The generator commits; that would defeat the test's auto-rollback.
		commit = patch.object(frappe.db, "commit")
		commit.start()
		self.addCleanup(commit.stop)
		# FrappeTestCase only rolls back once the whole class is done, so each
		# test needs its own agent name (the doctype is autoname:field).
		self.agent_name = "ZZ Baseline Suite " + frappe.generate_hash(length=8)
		self.suite_title = f"{self.agent_name} — Baseline"

	# -- helpers --------------------------------------------------------

	def _make_agent(self, prompts: list[str], name: str | None = None):
		"""Insert a Draft chat agent with *prompts* as its sample prompts."""
		name = name or self.agent_name
		# in_migrate suppresses the BPMN insert trigger — a real creation-process
		# run makes live AI calls; the trigger is covered by WI-001620.
		frappe.flags.in_migrate = True
		try:
			cfg = frappe.get_doc({
				"doctype": "AI Agent Configuration",
				"agent_name": name,
				"agent_id": frappe.scrub(name),
				"agent_framework": "Direct API",
				"agent_type": "Chat",
				"chat_mode_label": name,
				# Disabled so the unique-chat-mode-label check cannot clash with
				# whatever agents the site already has.
				"enabled": 0,
				"system_prompt": "Test prompt.",
				# No credentials: judge_model resolves empty, so the cases carry
				# no llm_judge assertion and nothing calls out to a provider.
				"ai_provider": None,
				"sample_prompts": [{"prompt": p} for p in prompts],
			})
			cfg.flags.ignore_links = True
			return cfg.insert(ignore_permissions=True)
		finally:
			frappe.flags.in_migrate = False

	def _make_suite(self, agent_configuration: str, title: str | None = None):
		"""A hand-rolled baseline suite, as a past duplicate run would leave."""
		return frappe.get_doc({
			"doctype": "AI Eval Suite",
			"title": title or self.suite_title,
			"agent_configuration": agent_configuration,
			"eval_type": "Direct",
		}).insert(ignore_permissions=True)

	def _suites(self) -> list[str]:
		return frappe.get_all(
			"AI Eval Suite", filters={"title": self.suite_title}, pluck="name", order_by="creation asc"
		)

	def _case_names(self, suite: str) -> set[str]:
		return set(frappe.get_all("AI Eval Case", filters={"suite": suite}, pluck="name"))

	# -- tests ----------------------------------------------------------

	def test_regenerating_reuses_the_suite_and_replaces_cases(self):
		"""Two generations for the same agent leave exactly one baseline suite."""
		self._make_agent(["one", "two"])

		first = generate_eval_suite_for_agent(self.agent_name)
		first_cases = self._case_names(first)
		self.assertEqual(len(first_cases), 2)

		second = generate_eval_suite_for_agent(self.agent_name)

		self.assertEqual(second, first)
		self.assertEqual(self._suites(), [first])
		second_cases = self._case_names(second)
		self.assertEqual(len(second_cases), 2)
		# Replaced, not appended: the old case documents are gone.
		self.assertFalse(first_cases & second_cases)

	def test_regenerating_tracks_a_changed_sample_prompt_list(self):
		"""Cases follow the current sample prompts, with no leftovers."""
		cfg = self._make_agent(["one", "two", "three"])
		suite = generate_eval_suite_for_agent(self.agent_name)
		self.assertEqual(len(self._case_names(suite)), 3)

		cfg.set("sample_prompts", [{"prompt": "only"}])
		cfg.flags.ignore_links = True
		cfg.save(ignore_permissions=True)

		self.assertEqual(generate_eval_suite_for_agent(self.agent_name), suite)
		self.assertEqual(self._suites(), [suite])
		prompts = frappe.get_all("AI Eval Case", filters={"suite": suite}, pluck="input_user_prompt")
		self.assertEqual(prompts, ["only"])

	def test_links_the_suite_back_to_the_agent(self):
		"""WI-001743: the suite owns the link to its agent configuration."""
		self._make_agent(["one"])
		suite = generate_eval_suite_for_agent(self.agent_name)

		self.assertEqual(
			frappe.db.get_value("AI Eval Suite", suite, "agent_configuration"), self.agent_name
		)

	def test_does_not_adopt_a_same_titled_suite_of_another_agent(self):
		"""A title collision across agents must not steal the other's suite."""
		self._make_agent(["one"])
		other = self._make_agent(["one"], name=self.agent_name + " Other")
		foreign = self._make_suite(other.name)  # same title, different owner

		suite = generate_eval_suite_for_agent(self.agent_name)

		self.assertNotEqual(suite, foreign.name)
		self.assertEqual(
			frappe.db.get_value("AI Eval Suite", foreign.name, "agent_configuration"), other.name
		)

	def test_picks_the_oldest_suite_when_duplicates_already_exist(self):
		"""Sites damaged by the old bug converge on one deterministic suite."""
		cfg = self._make_agent(["one"])
		oldest = self._make_suite(cfg.name)
		newest = self._make_suite(cfg.name)
		frappe.db.set_value(
			"AI Eval Suite", oldest.name, "creation", "2026-01-01 00:00:00", update_modified=False
		)
		frappe.db.set_value(
			"AI Eval Suite", newest.name, "creation", "2026-01-02 00:00:00", update_modified=False
		)

		self.assertEqual(generate_eval_suite_for_agent(self.agent_name), oldest.name)
		# No third suite was created, and the duplicate is left untouched.
		self.assertEqual(len(self._suites()), 2)
		self.assertEqual(self._case_names(newest.name), set())
