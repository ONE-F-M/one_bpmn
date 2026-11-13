"""Evals dashboard overview and scheduled-run results."""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt


def get_evals_overview(from_date: str = None, to_date: str = None) -> dict:
	"""Portfolio metrics for the Evals console dashboard, scoped to
	the suites the user can see. Suites/cases are structural totals; runs,
	tokens and cost respect the optional date range (like the Insights page).
	Cost is ``AI Eval Run.total_cost`` - the same per-1k pricing as observability.
	"""
	names = [s["name"] for s in frappe.get_list("AI Eval Suite", fields=["name"], limit_page_length=0)]
	overview = {
		"suites": len(names),
		"cases": 0,
		"runs": 0,
		"suites_passing": 0,
		"total_tokens": 0,
		"total_cost": 0.0,
	}
	if not names:
		return overview

	overview["cases"] = frappe.db.count("AI Eval Case", {"suite": ["in", names]})

	run_filters = {"suite": ["in", names]}
	if from_date and to_date:
		run_filters["creation"] = ["between", [from_date, f"{to_date} 23:59:59"]]
	period_runs = frappe.get_all(
		"AI Eval Run", filters=run_filters, fields=["total_tokens", "total_cost"], limit_page_length=0
	)
	overview["runs"] = len(period_runs)
	overview["total_tokens"] = sum((r.get("total_tokens") or 0) for r in period_runs)
	overview["total_cost"] = sum(flt(r.get("total_cost")) for r in period_runs)

	# Suites currently passing = each suite's latest run status is "Passed".
	latest: dict[str, str] = {}
	for r in frappe.get_all(
		"AI Eval Run",
		filters={"suite": ["in", names]},
		fields=["suite", "status"],
		order_by="creation desc",
		limit_page_length=0,
	):
		latest.setdefault(r["suite"], r["status"])
	overview["suites_passing"] = sum(1 for st in latest.values() if st == "Passed")

	return overview


def scheduled_results(
	days: int = 7, triggered_by: str = "", agent: str = "", failures_only: int = 0, limit: int = 60
) -> dict:
	"""Recent eval runs, newest first, with the first failure on the row.

	The suites list answers "what have we set up". This answers "what happened",
	which is a different question and needs the opposite ordering: by time,
	across every suite, with the failure text in front of the reader. A page of
	pass rates alone is a page of numbers that all need a click.

	Scoped like every other eval screen: a process owner sees runs for the
	agents whose process they own, a System Manager sees all.
	"""
	from frappe.utils import flt

	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication required"))

	is_sm = "System Manager" in frappe.get_roles(frappe.session.user)
	filters = {"creation": [">=", frappe.utils.add_days(frappe.utils.nowdate(), -abs(cint(days) or 7))]}
	if triggered_by:
		filters["triggered_by"] = triggered_by

	runs = frappe.get_all(
		"AI Eval Run",
		filters=filters,
		fields=[
			"name",
			"suite",
			"agent_configuration",
			"triggered_by",
			"scope",
			"backend",
			"status",
			"total_cases",
			"passed_cases",
			"failed_cases",
			"total_cost",
			"pass_rate",
			"stop_reason",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=min(cint(limit) or 60, 200),
	)
	if not runs:
		return {"runs": [], "agents": [], "is_system_manager": is_sm}

	suites = {
		s["name"]: s
		for s in frappe.get_all(
			"AI Eval Suite",
			filters={"name": ["in", list({r.suite for r in runs if r.suite})]},
			fields=["name", "title", "agent_configuration", "process_model"],
		)
	}
	visible = _runs_visible_to(runs, suites, is_sm)
	# A run's agent is its own field, else its suite's - and it has to be the
	# same answer whether the reader is looking at the row or filtering by it.
	# Filtering on the raw field dropped every run that only knew its agent
	# through the suite, while the dropdown still listed that agent.
	for run in visible:
		run.agent = run.agent_configuration or (suites.get(run.suite) or {}).get("agent_configuration") or ""
	# The choices come from everything the reader may see, not from the rows
	# left after filtering - otherwise picking one agent removes the others.
	agents = sorted({r.agent for r in visible if r.agent})
	if agent:
		visible = [r for r in visible if r.agent == agent]

	first_failures = _first_failure_per_run([r.name for r in visible])
	rows = []
	for run in visible:
		suite = suites.get(run.suite) or {}
		failure = first_failures.get(run.name) or {}
		if cint(failures_only) and not failure:
			continue
		rows.append(
			{
				"run": run.name,
				"when": str(run.creation),
				"triggered_by": run.triggered_by or _inferred_trigger(run, suite),
				"suite": suite.get("title") or run.suite or "",
				"agent": run.agent,
				"status": run.status,
				"passed": run.passed_cases or 0,
				"total": run.total_cases or 0,
				"rate": flt(run.pass_rate) if run.pass_rate is not None else None,
				"cost": flt(run.total_cost),
				"stopped": run.stop_reason or "",
				# The whole point of the row: what went wrong, without a click.
				"failure": failure.get("why") or "",
				"failure_subject": failure.get("subject") or "",
			}
		)
	return {"runs": rows, "agents": agents, "is_system_manager": is_sm}


def _runs_visible_to(runs, suites, is_sm) -> list:
	"""A process owner sees their own agents' runs, mirroring list_owned_processes."""
	if is_sm:
		return runs
	owners = {
		p["name"]: p["process_owner"] for p in frappe.get_all("Process", fields=["name", "process_owner"])
	}
	models = {
		m["name"]: m["process_name"]
		for m in frappe.get_all("BPMN Process Model", fields=["name", "process_name"])
	}
	mine = []
	for run in runs:
		model = (suites.get(run.suite) or {}).get("process_model")
		if model and owners.get(models.get(model)) == frappe.session.user:
			mine.append(run)
	return mine


def _inferred_trigger(run, suite) -> str:
	"""What asked for a run made before the field existed. The patch labels the
	rows that exist today; this covers anything that slips through."""
	if run.scope == "Online":
		return "Online sample"
	if run.backend == "deterministic":
		return "Pull request"
	return "By hand"


def _first_failure_per_run(run_names: list) -> dict:
	"""One failing row per run - the first - as {run: {subject, why}}.

	One query for the page rather than one per run: a week of nightly sweeps
	across a dozen agents is a hundred rows, and a hundred round trips is a
	page nobody opens twice.
	"""
	if not run_names:
		return {}
	# assertion_results too, not just error_message: a live run records the
	# summary note on the row and the actual reason inside the assertions, so a
	# page built on error_message alone showed "3/4" with a blank reason -
	# exactly the click this page exists to avoid.
	from processa.ai_agent_evals.eval_ci import why

	rows = frappe.get_all(
		"AI Eval Result",
		filters={"parent": ["in", run_names], "status": ["in", ["Failed", "Error"]]},
		fields=["parent", "eval_case", "source_run", "error_message", "assertion_results", "idx"],
		order_by="parent asc, idx asc",
	)
	out = {}
	titles = (
		{
			c["name"]: c["title"]
			for c in frappe.get_all(
				"AI Eval Case",
				filters={"name": ["in", [r.eval_case for r in rows if r.eval_case]]},
				fields=["name", "title"],
			)
		}
		if any(r.eval_case for r in rows)
		else {}
	)
	for row in rows:
		if row.parent in out:
			continue
		subject = titles.get(row.eval_case) or row.eval_case or row.source_run or ""
		out[row.parent] = {"subject": subject, "why": why(row)[:300]}
	return out
