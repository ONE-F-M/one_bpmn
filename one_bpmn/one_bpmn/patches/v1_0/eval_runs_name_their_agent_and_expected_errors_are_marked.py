"""Attribute old eval suites and runs to their agent, and mark errors eval cases cause on purpose.

A suite or run with no agent_configuration gets the only AI Agent Configuration on the
suite's process model; zero or several leave it empty. The Orchestrator Baseline's
unreadable pull request case gets its expected_error, then every case that has one has
its past step errors flagged. Running it again changes nothing.
"""

import frappe

from one_bpmn.agents.eval_runner import _mark_expected_errors, _resolve_agent_configuration_fallback
from one_bpmn.one_bpmn.patches.v1_0.orchestrator_agent_baseline_covers_every_tool import CASES, SUITE_TITLE


def execute():
	suites, runs, unresolved = _attribute_suites_and_runs()
	cases = _seed_expected_errors()
	steps = sum(
		_mark_expected_errors(case.name, case.expected_error)
		for case in frappe.get_all(
			"AI Eval Case", filters={"expected_error": ["is", "set"]}, fields=["name", "expected_error"]
		)
	)
	print(
		f"eval_runs_name_their_agent_and_expected_errors_are_marked: {suites} suite(s) and {runs} run(s) "
		f"attributed, {unresolved} run(s) left without an agent (process model has no or several "
		f"configurations), {cases} case(s) given an expected error, {steps} step error(s) marked expected"
	)


def _attribute_suites_and_runs() -> tuple[int, int, int]:
	agent_by_suite = {
		suite.name: _resolve_agent_configuration_fallback(None, suite.process_model)
		for suite in frappe.get_all("AI Eval Suite", fields=["name", "process_model"])
	}

	suites = 0
	for suite in frappe.get_all(
		"AI Eval Suite", filters={"agent_configuration": ["is", "not set"]}, pluck="name"
	):
		if agent_by_suite.get(suite):
			frappe.db.set_value(
				"AI Eval Suite", suite, "agent_configuration", agent_by_suite[suite], update_modified=False
			)
			suites += 1

	runs = unresolved = 0
	for run in frappe.get_all(
		"AI Eval Run", filters={"agent_configuration": ["is", "not set"]}, fields=["name", "suite"]
	):
		agent = agent_by_suite.get(run.suite)
		if not agent:
			unresolved += 1
			continue
		frappe.db.set_value("AI Eval Run", run.name, "agent_configuration", agent, update_modified=False)
		runs += 1
	return suites, runs, unresolved


def _seed_expected_errors() -> int:
	baseline = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if not baseline:
		return 0
	seeded = 0
	for spec in CASES:
		if not spec.get("expected_error"):
			continue
		case = frappe.db.get_value(
			"AI Eval Case",
			{"suite": baseline, "title": spec["title"], "expected_error": ["is", "not set"]},
			"name",
		)
		if case:
			frappe.db.set_value(
				"AI Eval Case", case, "expected_error", spec["expected_error"], update_modified=False
			)
			seeded += 1
	return seeded
