"""
Whitelisted endpoints backing the Processa Evals UI (WI-001681).

Every read goes through ``frappe.get_list`` so the AI Evals permission scoping
(WI-001744) applies automatically — a process owner sees only their own suites,
System Manager sees all.
"""

import frappe
from frappe import _
from frappe.utils import get_datetime


def _run_title(suite_title: str, seq: int, started_at) -> str:
	"""Human-readable title for an AI Eval Run (which has no title field):
	the suite title + the run's ordinal + its start time."""
	base = f"{suite_title or 'Suite'} — Run {seq}"
	if started_at:
		try:
			return f"{base} · {get_datetime(started_at).strftime('%Y-%m-%d %H:%M')}"
		except Exception:
			pass
	return base


@frappe.whitelist()
def list_eval_suites() -> dict:
	"""Return the eval suites visible to the current user, each with a summary
	of its latest run, for the Evals console (WI-001745).
	"""
	suites = frappe.get_list(
		"AI Eval Suite",
		fields=["name", "title", "process_model", "agent_configuration", "gate_deployment"],
		order_by="modified desc",
		limit_page_length=0,
	)

	names = [s["name"] for s in suites]
	latest_run: dict[str, dict] = {}
	agent_labels: dict[str, str] = {}
	case_counts: dict[str, int] = {}

	if names:
		# Newest run per suite. get_list keeps this scoped to permitted rows.
		for run in frappe.get_list(
			"AI Eval Run",
			filters={"suite": ["in", names]},
			fields=["suite", "status", "total_cases", "passed_cases", "failed_cases", "ended_at"],
			order_by="creation desc",
			limit_page_length=0,
		):
			latest_run.setdefault(run["suite"], run)

		# Case count per suite (one bulk grouped query).
		for row in frappe.get_all(
			"AI Eval Case",
			filters={"suite": ["in", names]},
			fields=["suite", "count(name) as n"],
			group_by="suite",
		):
			case_counts[row["suite"]] = row["n"]

		configs = [s["agent_configuration"] for s in suites if s.get("agent_configuration")]
		if configs:
			for cfg in frappe.get_all(
				"AI Agent Configuration",
				filters={"name": ["in", list(set(configs))]},
				fields=["name", "agent_name"],
			):
				agent_labels[cfg["name"]] = cfg["agent_name"]

	for s in suites:
		s["latest_run"] = latest_run.get(s["name"])
		s["case_count"] = case_counts.get(s["name"], 0)
		s["agent_name"] = agent_labels.get(s.get("agent_configuration"))

	return {
		"suites": suites,
		"is_system_manager": "System Manager" in frappe.get_roles(),
	}


@frappe.whitelist()
def get_suite_detail(suite: str) -> dict:
	"""Suite header, its cases, and recent runs for the suite-detail view
	(WI-001746). Permission is enforced by check_permission (owner / SM).
	"""
	doc = frappe.get_doc("AI Eval Suite", suite)
	doc.check_permission("read")

	agent_name = None
	if doc.agent_configuration:
		agent_name = frappe.db.get_value(
			"AI Agent Configuration", doc.agent_configuration, "agent_name"
		)

	cases = frappe.get_all(
		"AI Eval Case",
		filters={"suite": suite},
		fields=["name", "title", "provider", "model", "source_run"],
		order_by="creation asc",
	)
	# Assertion summary per case (one bulk query on the child table). Kept
	# defensive: a hiccup building the summary must never blank the whole
	# detail view — the cases and runs still return, just without chips.
	assertions: dict[str, list] = {}
	if cases:
		try:
			for a in frappe.get_all(
				"AI Eval Assertion",
				filters={"parenttype": "AI Eval Case", "parent": ["in", [c["name"] for c in cases]]},
				fields=["parent", "assertion_type"],
			):
				assertions.setdefault(a["parent"], []).append(a["assertion_type"])
		except Exception:
			frappe.log_error(
				title="Evals: assertion summary failed",
				message=frappe.get_traceback(),
			)
	for c in cases:
		c["assertion_types"] = assertions.get(c["name"], [])

	runs = frappe.get_all(
		"AI Eval Run",
		filters={"suite": suite},
		fields=["name", "status", "backend", "total_cases", "passed_cases",
				"failed_cases", "started_at", "ended_at"],
		order_by="creation desc",
		limit_page_length=20,
	)
	# Number runs by their absolute order (newest first in the list), and give
	# each a readable title so the UI never shows the raw run id.
	total_runs = frappe.db.count("AI Eval Run", {"suite": suite})
	for idx, r in enumerate(runs):
		r["display_title"] = _run_title(doc.title, total_runs - idx, r.get("started_at"))

	return {
		"suite": {
			"name": doc.name,
			"title": doc.title,
			"process_model": doc.process_model,
			"agent_configuration": doc.agent_configuration,
			"agent_name": agent_name,
		},
		"cases": cases,
		"runs": runs,
	}


@frappe.whitelist()
def create_eval_case(
	suite: str,
	title: str,
	input_user_prompt: str,
	provider: str,
	model: str,
	input_system_prompt: str = "",
	expected_output: str = "",
) -> str:
	"""Create a manual AI Eval Case in ``suite`` (WI-001746). The current user
	must be able to write the suite (owner / SM)."""
	suite_doc = frappe.get_doc("AI Eval Suite", suite)
	suite_doc.check_permission("write")

	case = frappe.get_doc({
		"doctype": "AI Eval Case",
		"suite": suite,
		"title": title,
		"process_model": suite_doc.process_model or None,
		"provider": provider,
		"model": model,
		"backend": "direct_api",
		"input_system_prompt": input_system_prompt,
		"input_user_prompt": input_user_prompt,
		"expected_output": expected_output,
	})
	case.insert()
	return case.name


@frappe.whitelist()
def get_run_review(run: str) -> dict:
	"""Full result of one AI Eval Run for the run-review view (WI-001747):
	summary, per-case results (status, actual output, parsed assertion results
	incl. judge score/reasoning), and a per-case comparison to the previous
	run of the same suite. Permission enforced via check_permission (owner/SM).
	"""
	doc = frappe.get_doc("AI Eval Run", run)
	doc.check_permission("read")

	suite_title = frappe.db.get_value("AI Eval Suite", doc.suite, "title")
	run_seq = frappe.db.count("AI Eval Run", {"suite": doc.suite, "creation": ["<=", doc.creation]})

	case_titles = {
		c["name"]: c["title"]
		for c in frappe.get_all(
			"AI Eval Case",
			filters={"suite": doc.suite},
			fields=["name", "title"],
		)
	}

	results = []
	for r in doc.results:
		results.append({
			"eval_case": r.eval_case,
			"case_title": case_titles.get(r.eval_case, r.eval_case),
			"status": r.status,
			"actual_output": r.actual_output,
			"error_message": r.error_message,
			"tokens_used": r.tokens_used,
			"cost": r.cost,
			"assertions": frappe.parse_json(r.assertion_results) or [],
		})

	# Previous finished run of the same suite, for a per-case delta.
	prev = frappe.get_all(
		"AI Eval Run",
		filters={
			"suite": doc.suite,
			"name": ["!=", doc.name],
			"creation": ["<", doc.creation],
			"status": ["in", ["Passed", "Failed"]],
		},
		fields=["name", "started_at", "creation"],
		order_by="creation desc",
		limit_page_length=1,
	)
	previous = None
	if prev:
		prev_name = prev[0]["name"]
		prev_seq = frappe.db.count(
			"AI Eval Run", {"suite": doc.suite, "creation": ["<=", prev[0]["creation"]]}
		)
		prev_status = {
			row.eval_case: row.status
			for row in frappe.get_doc("AI Eval Run", prev_name).results
		}
		previous = {
			"name": prev_name,
			"display_title": _run_title(suite_title, prev_seq, prev[0]["started_at"]),
			"case_status": prev_status,
		}

	return {
		"run": {
			"name": doc.name,
			"display_title": _run_title(suite_title, run_seq, doc.started_at),
			"suite": doc.suite,
			"status": doc.status,
			"backend": doc.backend,
			"started_at": doc.started_at,
			"ended_at": doc.ended_at,
			"total_cases": doc.total_cases,
			"passed_cases": doc.passed_cases,
			"failed_cases": doc.failed_cases,
			"total_tokens": doc.total_tokens,
			"total_cost": doc.total_cost,
		},
		"results": results,
		"previous": previous,
	}
