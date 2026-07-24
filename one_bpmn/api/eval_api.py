"""
Whitelisted endpoints backing the Processa Evals UI (WI-001681).

Every read goes through ``frappe.get_list`` so the AI Evals permission scoping
(WI-001744) applies automatically — a process owner sees only their own suites,
System Manager sees all.
"""

import frappe
from frappe import _


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
