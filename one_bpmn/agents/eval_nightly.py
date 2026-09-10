# Copyright (c) 2026, one-fm and contributors
"""The overnight live run: what it does, not when it happens.

When it happens belongs to a BPMN timer start event, so the schedule is visible
and editable in Processa like any other process rather than buried in
``hooks.py``. This module is what that map's Server Script calls.

The grading model and the ceiling on what one night may spend come from
Processa Settings, because the site that owns the agents is the only place a
live suite has anything to talk to — and the only place that should hold the
money decision.
"""

import frappe
from frappe.utils import flt

from one_bpmn.agents.eval_ci import run_suite, select_suites

# A starting bar, not a measured one. Agents are not repeatable, so a live suite
# wobbles run to run; set this from observed spread once real nights exist.
DEFAULT_MIN_PASS = 90.0


def run_nightly(min_pass: float = None, backend: str = "live") -> dict:
	"""Run every suite tagged Nightly and report what happened.

	The ceiling is for the whole night, not per suite: each suite is given
	whatever is left of it, and once it is gone the remaining suites are
	reported as not run rather than started and abandoned.
	"""
	min_pass = flt(min_pass) if min_pass is not None else DEFAULT_MIN_PASS
	cap = flt(frappe.db.get_single_value("Processa Settings", "nightly_eval_spend_cap") or 0)
	grader = frappe.db.get_single_value("Processa Settings", "nightly_eval_grading_model") or ""

	suites = select_suites(role="Nightly")
	summaries = []
	not_run = []
	spent = 0.0

	for suite in suites:
		remaining = (cap - spent) if cap else 0
		if cap and remaining <= 0:
			not_run.append(suite["title"] or suite["name"])
			continue
		summary = run_suite(suite, backend, spend_cap=remaining)
		spent += flt(summary.get("cost"))
		summaries.append(summary)

	below = [
		s for s in summaries
		if s["rate"] is not None and s["rate"] < min_pass
	]
	unchecked = [s for s in summaries if s["rate"] is None]

	return {
		"backend": backend,
		"min_pass": min_pass,
		"grading_model": grader,
		"spend_cap": cap,
		"spent": spent,
		"suites": summaries,
		# Named separately from the failures so an alert can say "we ran out of
		# budget" without implying the agents got worse.
		"suites_not_run": not_run,
		"stopped_on_budget": [s["suite"] for s in summaries if s.get("stopped")],
		"below_minimum": [
			{"suite": s["suite"], "rate": s["rate"], "run": s["run"], "failures": s["failures"]}
			for s in below
		],
		"checked_nothing": [s["suite"] for s in unchecked],
		"ok": not below and not unchecked and not not_run,
		"summary_line": _summary_line(summaries, below, unchecked, not_run, spent, cap),
	}


def _summary_line(summaries, below, unchecked, not_run, spent, cap) -> str:
	"""One line fit for an alert subject or a process comment."""
	if not summaries and not not_run:
		return "No eval suite is tagged Nightly, so nothing ran."

	parts = [f"{len(summaries)} suite(s) run"]
	if below:
		parts.append(", ".join(f"{s['suite']} at {s['rate']:.1f}%" for s in below) + " below the bar")
	if unchecked:
		parts.append(f"{len(unchecked)} checked nothing")
	if not_run:
		parts.append(f"{len(not_run)} not run on budget")
	if not below and not unchecked and not not_run:
		parts.append("all above the bar")
	parts.append(f"spent {spent:.4f}" + (f" of {cap:.4f}" if cap else ""))
	return "; ".join(parts) + "."
