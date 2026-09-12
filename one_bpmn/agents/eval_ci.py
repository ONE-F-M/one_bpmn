# Copyright (c) 2026, one-fm and contributors
"""Selecting suites and running one, for callers that need an answer inline.

The web entry points enqueue a run and return, which is no use to anything that
has to act on the outcome — a bench command that must exit non-zero, or a
scheduled process that must decide whether to raise an alert. Both of those go
through here, so there is one definition of "the pass rate of a suite" rather
than one per caller.
"""

import json

import frappe
from frappe.utils import flt

from one_bpmn.agents.eval_runner import _execute_eval_suite


def select_suites(role: str = "", suite: str = "") -> list[dict]:
	"""The suites a role or a name selects, in a stable order."""
	filters = {}
	if suite:
		filters["name" if frappe.db.exists("AI Eval Suite", suite) else "title"] = suite
	if role:
		filters["ci_role"] = role
	return frappe.get_all(
		"AI Eval Suite",
		filters=filters,
		fields=["name", "title", "ci_role"],
		order_by="title asc",
	)


def run_suite(suite: dict, backend: str, spend_cap: float = 0) -> dict:
	"""Execute one suite here and now, and describe what happened.

	*spend_cap* is the most this run may spend; 0 means no ceiling. It is
	recorded on the run so the runner can stop between cases, and so anyone
	reading the run afterwards can see the limit it was given.
	"""
	run = frappe.get_doc({
		"doctype": "AI Eval Run",
		"suite": suite["name"],
		"status": "Running",
		"backend": backend,
		"scope": "Suite",
		"spend_cap": flt(spend_cap),
		"started_at": frappe.utils.now_datetime(),
		"agent_configuration": frappe.db.get_value(
			"AI Eval Suite", suite["name"], "agent_configuration"
		),
	})
	run.flags.ignore_mandatory = True
	run.insert(ignore_permissions=True)
	# Durable before and after, so a run interrupted halfway is still readable
	# — skipped under test so FrappeTestCase rollback cleans its fixtures up
	# instead of leaving suites and runs behind on the site.
	if not frappe.flags.in_test:
		frappe.db.commit()

	_execute_eval_suite(run.name)
	if not frappe.flags.in_test:
		frappe.db.commit()
	run.reload()

	checked = [r for r in run.results if r.status != "Skipped"]
	passed = [r for r in checked if r.status == "Passed"]
	titles = {
		c.name: c.title
		for c in frappe.get_all("AI Eval Case", filters={"suite": suite["name"]}, fields=["name", "title"])
	}
	return {
		"suite": suite["title"] or suite["name"],
		"run": run.name,
		"status": run.status,
		"cases": len(run.results or []),
		"checked": len(checked),
		"passed": len(passed),
		"skipped": len(run.results or []) - len(checked),
		# The rate is over what was actually CHECKED. Counting a skipped case as
		# a pass would let a suite whose assertions all need a model report 100%
		# from a run that verified nothing.
		"rate": (len(passed) / len(checked) * 100) if checked else None,
		"cost": flt(run.total_cost),
		"stopped": (run.get("stop_reason") or "").strip(),
		"failures": [
			{
				"case": titles.get(r.eval_case) or r.eval_case,
				"status": r.status,
				# The assertion that actually failed, not the row's summary note:
				# a CI log is read once, in a hurry, by someone who did not write
				# the case.
				"why": _why(r),
			}
			for r in run.results if r.status in ("Failed", "Error")
		],
	}


def _why(result) -> str:
	"""What to print for a failed case: the assertions that did not hold."""
	try:
		assertions = json.loads(result.assertion_results or "[]")
	except Exception:
		assertions = []

	broken = [a for a in assertions if not a.get("passed")]
	if broken:
		return "; ".join(
			f"{a.get('assertion_type')}"
			+ (f" [{str(a.get('value'))[:60]}]" if a.get("value") else "")
			+ (f": {a.get('message') or a.get('explanation') or ''}".rstrip(": ") if (a.get("message") or a.get("explanation")) else "")
			for a in broken
		)[:400]
	return (result.error_message or "").strip()[:400] or "no detail recorded"
