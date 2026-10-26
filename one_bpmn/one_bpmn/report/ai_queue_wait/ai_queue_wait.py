import statistics

import frappe
from frappe import _
from frappe.utils import add_days, cint, now_datetime

DEFAULT_DAYS = 7
TARGET_P90_MS = 5000


def execute(filters=None):
	filters = frappe._dict(filters or {})
	waits = queue_waits_by_agent(filters)
	return get_columns(), [row_for(agent, values) for agent, values in sorted(waits.items())]


def queue_waits_by_agent(filters) -> dict:
	run_filters = {
		"status": ["in", ["Success", "Error"]],
		"started_at": [">=", add_days(now_datetime(), -(cint(filters.days) or DEFAULT_DAYS))],
	}
	if filters.origin:
		run_filters["origin"] = filters.origin
	waits = {}
	for run in frappe.get_list(
		"AI Agent Run",
		filters=run_filters,
		fields=["agent_configuration", "queue_wait_ms"],
		limit_page_length=0,
	):
		waits.setdefault(run.agent_configuration, []).append(cint(run.queue_wait_ms))
	return waits


def row_for(agent: str, values: list) -> dict:
	p90 = statistics.quantiles(values, n=10, method="inclusive")[-1] if len(values) > 1 else values[0]
	return {
		"agent": agent,
		"runs": len(values),
		"median_ms": statistics.median(values),
		"p90_ms": p90,
		"max_ms": max(values),
		"within_target": 1 if p90 < TARGET_P90_MS else 0,
	}


def get_columns():
	return [
		{
			"fieldname": "agent",
			"label": _("Agent"),
			"fieldtype": "Link",
			"options": "AI Agent Configuration",
			"width": 200,
		},
		{"fieldname": "runs", "label": _("Runs"), "fieldtype": "Int", "width": 80},
		{"fieldname": "median_ms", "label": _("Median Queue Wait (ms)"), "fieldtype": "Int", "width": 170},
		{"fieldname": "p90_ms", "label": _("P90 Queue Wait (ms)"), "fieldtype": "Int", "width": 160},
		{"fieldname": "max_ms", "label": _("Max Queue Wait (ms)"), "fieldtype": "Int", "width": 160},
		{"fieldname": "within_target", "label": _("P90 Under 5 s"), "fieldtype": "Check", "width": 110},
	]
