# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
API endpoints for the AI Agent Insights dashboard.

All methods are whitelisted, require System Manager role, and use
frappe.qb (Query Builder) exclusively — no raw SQL.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import add_days, cint, cstr, flt, getdate, today

from pypika import CustomFunction
from pypika.terms import Case

# MariaDB month bucketing, used by the cost-allocation report (WI-001668).
DateFormat = CustomFunction("DATE_FORMAT", ["field", "format"])


def _default_dates(from_date: Optional[str], to_date: Optional[str], days: int = 7):
	"""Return (from_date, to_date) defaulting to the last *days* days."""
	to_d = getdate(to_date) if to_date else getdate(today())
	from_d = getdate(from_date) if from_date else getdate(add_days(today(), -(days - 1)))
	return from_d, to_d


def _origin_condition(Run, origin: str):
	"""qb criterion for the run-origin segment (WI-001751).

	"production" (default) excludes eval-origin runs — rows created before the
	origin field existed are NULL and count as production. "eval" selects only
	eval-origin runs. "all" applies no filter.
	"""
	if origin == "eval":
		return Run.origin == "eval"
	if origin == "all":
		return Run.name.notnull()
	return fn.Coalesce(Run.origin, "production") != "eval"


# ---------------------------------------------------------------------------
# 1. Overview cards
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_agent_overview(days: int = 7, agent_configuration: str = None, origin: str = "production") -> dict:
	"""Return 6 headline metrics for the overview number cards.

	Pass *agent_configuration* to scope every metric to one agent's runs
	(WI-001636). Deeper per-agent filtering across the other reports ships
	with the observability feature story (WI-001608). *origin* segments the
	metrics: "production" (default), "eval", or "all" (WI-001751).
	"""
	frappe.only_for("System Manager")
	days = cint(days) or 7

	Run = DocType("AI Agent Run")
	today_date = getdate(today())
	range_start = getdate(add_days(today(), -(days - 1)))

	# Runs today
	runs_today = cint(
		frappe.qb.from_(Run)
		.select(fn.Count("*"))
		.where(fn.Date(Run.started_at) == today_date)
		.where(Run.agent_configuration == agent_configuration if agent_configuration else Run.name.notnull())
		.where(_origin_condition(Run, origin))
		.run()[0][0]
	)

	# Success rate over period
	period_stats = (
		frappe.qb.from_(Run)
		.select(
			fn.Count("*").as_("total"),
			fn.Sum(Case().when(Run.status == "Success", 1).else_(0)).as_("successes"),
		)
		.where(fn.Date(Run.started_at) >= range_start)
		.where(fn.Date(Run.started_at) <= today_date)
		.where(Run.agent_configuration == agent_configuration if agent_configuration else Run.name.notnull())
		.where(_origin_condition(Run, origin))
		.where(Run.status != "Running")
		.run(as_dict=True)
	)[0]

	total = cint(period_stats.get("total"))
	successes = cint(period_stats.get("successes"))
	success_rate = flt((successes / total) * 100, 1) if total else 0.0

	# Total cost
	total_cost = flt(
		frappe.qb.from_(Run)
		.select(fn.Sum(Run.estimated_cost))
		.where(fn.Date(Run.started_at) >= range_start)
		.where(fn.Date(Run.started_at) <= today_date)
		.where(Run.agent_configuration == agent_configuration if agent_configuration else Run.name.notnull())
		.where(_origin_condition(Run, origin))
		.run()[0][0],
		4,
	)

	# Active errors today
	active_errors = cint(
		frappe.qb.from_(Run)
		.select(fn.Count("*"))
		.where(fn.Date(Run.started_at) == today_date)
		.where(Run.agent_configuration == agent_configuration if agent_configuration else Run.name.notnull())
		.where(_origin_condition(Run, origin))
		.where(Run.status == "Error")
		.run()[0][0]
	)

	# Avg latency (successful runs)
	avg_latency = cint(
		frappe.qb.from_(Run)
		.select(fn.Avg(Run.duration_ms))
		.where(fn.Date(Run.started_at) >= range_start)
		.where(fn.Date(Run.started_at) <= today_date)
		.where(Run.agent_configuration == agent_configuration if agent_configuration else Run.name.notnull())
		.where(_origin_condition(Run, origin))
		.where(Run.status == "Success")
		.run()[0][0]
	)

	# Total tokens
	total_tokens = cint(
		frappe.qb.from_(Run)
		.select(fn.Sum(Run.total_tokens))
		.where(fn.Date(Run.started_at) >= range_start)
		.where(fn.Date(Run.started_at) <= today_date)
		.where(Run.agent_configuration == agent_configuration if agent_configuration else Run.name.notnull())
		.where(_origin_condition(Run, origin))
		.run()[0][0]
	)

	return {
		"runs_today": runs_today,
		"success_rate": success_rate,
		"total_cost": total_cost,
		"active_errors": active_errors,
		"avg_latency_ms": avg_latency,
		"total_tokens": total_tokens,
	}


# ---------------------------------------------------------------------------
# 2. Cost & Token report
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_cost_token_report(
	from_date: str = None,
	to_date: str = None,
	model: str = None,
	provider: str = None,
	process_model: str = None,
	agent_configuration: str = None,
	origin: str = "production",
	group_by: str = "model",
) -> dict:
	"""Return daily cost/token data grouped by date and model — or, since
	AI tasks are done by AI Agents (WI-001608), grouped by the run's
	AI Agent Configuration when ``group_by="agent"``. Runs recorded before
	agent attribution existed appear as "Unattributed"."""
	frappe.only_for("System Manager")
	group_by = group_by if group_by in ("model", "agent") else "model"
	from_d, to_d = _default_dates(from_date, to_date)

	Run = DocType("AI Agent Run")

	# The series dimension: model (classic) or the run's agent (WI-001608).
	group_field = Run.agent_configuration if group_by == "agent" else Run.model

	query = (
		frappe.qb.from_(Run)
		.select(
			fn.Date(Run.started_at).as_("date"),
			group_field.as_("group_key"),
			Run.provider,
			fn.Count("*").as_("total_runs"),
			fn.Sum(Run.total_tokens).as_("total_tokens"),
			fn.Avg(Run.total_tokens).as_("avg_tokens"),
			fn.Sum(Run.estimated_cost).as_("total_cost"),
			fn.Avg(Run.estimated_cost).as_("avg_cost"),
			fn.Sum(Run.total_input_cost).as_("input_cost"),
			fn.Sum(Run.total_output_cost).as_("output_cost"),
		)
		.where(fn.Date(Run.started_at) >= from_d)
		.where(fn.Date(Run.started_at) <= to_d)
		.where(_origin_condition(Run, origin))
		# Running runs ARE included: selector runs stay "Running" for the
		# whole life of their subprocess and their token/cost rollups are
		# refreshed after every decision — excluding them hid all selector
		# spend until (if ever) the subprocess completed. Success-rate and
		# reliability reports still exclude Running, correctly.
		.orderby(fn.Date(Run.started_at))
	)
	query = query.groupby(fn.Date(Run.started_at), group_field, Run.provider)

	if model:
		query = query.where(Run.model == model)
	if provider:
		query = query.where(Run.provider == provider)
	if process_model:
		query = query.where(Run.process_model == process_model)
	if agent_configuration:
		query = query.where(Run.agent_configuration == agent_configuration)

	raw_rows = query.run(as_dict=True)

	# Build rows with safe number conversions. "series" is the grouped
	# dimension's display value; "model" keeps carrying it too so the
	# existing frontend bindings keep working in both modes.
	unattributed = "Unattributed"
	rows = []
	for r in raw_rows:
		series = cstr(r.get("group_key")) or (unattributed if group_by == "agent" else "")
		rows.append({
			"date": cstr(r.get("date")),
			"series": series,
			"model": series,
			"provider": cstr(r.get("provider")),
			"total_runs": cint(r.get("total_runs")),
			"total_tokens": cint(r.get("total_tokens")),
			"avg_tokens": cint(r.get("avg_tokens")),
			"total_cost": flt(r.get("total_cost"), 6),
			"avg_cost": flt(r.get("avg_cost"), 6),
			"input_cost": flt(r.get("input_cost"), 6),
			"output_cost": flt(r.get("output_cost"), 6),
		})

	# Build chart_data — pivot by the grouped dimension per day
	all_dates = []
	d = from_d
	while d <= to_d:
		all_dates.append(cstr(d))
		d = getdate(add_days(cstr(d), 1))

	series_day_cost = defaultdict(lambda: defaultdict(float))
	series_seen = set()
	for r in rows:
		series_day_cost[r["series"]][r["date"]] += r["total_cost"]
		series_seen.add(r["series"])

	datasets = []
	for m in sorted(series_seen):
		datasets.append({
			"model": m,  # legacy key the chart legend binds to
			"label": m,
			"values": [flt(series_day_cost[m].get(d, 0), 6) for d in all_dates],
		})

	# Summary
	summary_cost = sum(r["total_cost"] for r in rows)
	summary_runs = sum(r["total_runs"] for r in rows)
	summary_tokens = sum(r["total_tokens"] for r in rows)

	return {
		"rows": rows,
		"chart_data": {
			"labels": all_dates,
			"datasets": datasets,
		},
		"summary": {
			"total_cost": flt(summary_cost, 6),
			"total_runs": summary_runs,
			"total_tokens": summary_tokens,
		},
	}


# ---------------------------------------------------------------------------
# 3. Error report
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_error_report(
	from_date: str = None,
	to_date: str = None,
	model: str = None,
	error_code: str = None,
	process_model: str = None,
	agent_configuration: str = None,
	origin: str = "production",
	group_by: str = "model",
) -> dict:
	"""Return error analysis grouped by model + bpmn_id — or by the run's
	AI Agent Configuration + bpmn_id when ``group_by="agent"`` (WI-001608)."""
	frappe.only_for("System Manager")
	group_by = group_by if group_by in ("model", "agent") else "model"
	from_d, to_d = _default_dates(from_date, to_date)

	Run = DocType("AI Agent Run")
	group_field = Run.agent_configuration if group_by == "agent" else Run.model

	# --- Main rows: group by (model | agent) + bpmn_id ---
	query = (
		frappe.qb.from_(Run)
		.select(
			group_field.as_("group_key"),
			Run.bpmn_id,
			fn.Max(Run.bpmn_label).as_("bpmn_label"),
			fn.Count("*").as_("total_runs"),
			fn.Sum(Case().when(Run.status == "Success", 1).else_(0)).as_("successes"),
			fn.Sum(Case().when(Run.status == "Error", 1).else_(0)).as_("errors"),
			fn.Sum(Case().when(Run.retry_count > 0, 1).else_(0)).as_("retried"),
			fn.Sum(
				Case().when(
					(Run.retry_count > 0) & (Run.status == "Success"), 1
				).else_(0)
			).as_("retry_recovered"),
			fn.Avg(Run.duration_ms).as_("avg_duration_ms"),
		)
		.where(fn.Date(Run.started_at) >= from_d)
		.where(fn.Date(Run.started_at) <= to_d)
		.where(Run.status != "Running")
		.where(_origin_condition(Run, origin))
		.groupby(group_field, Run.bpmn_id)
		.orderby(fn.Sum(Case().when(Run.status == "Error", 1).else_(0)), order=frappe.qb.desc)
	)

	if model:
		query = query.where(Run.model == model)
	if error_code:
		query = query.where(Run.error_code == error_code)
	if process_model:
		query = query.where(Run.process_model == process_model)
	if agent_configuration:
		query = query.where(Run.agent_configuration == agent_configuration)

	raw_rows = query.run(as_dict=True)

	rows = []
	for r in raw_rows:
		total = cint(r.get("total_runs"))
		errors = cint(r.get("errors"))
		retried = cint(r.get("retried"))
		series = cstr(r.get("group_key")) or ("Unattributed" if group_by == "agent" else "")
		rows.append({
			"model": series,
			"bpmn_id": cstr(r.get("bpmn_id")),
			"bpmn_label": cstr(r.get("bpmn_label")) or cstr(r.get("bpmn_id")),
			"total_runs": total,
			"successes": cint(r.get("successes")),
			"errors": errors,
			"success_rate": flt((cint(r.get("successes")) / total) * 100, 1) if total else 0.0,
			"retry_rate": flt((retried / total) * 100, 1) if total else 0.0,
			"retry_recovered": cint(r.get("retry_recovered")),
			"avg_duration_ms": cint(r.get("avg_duration_ms")),
		})

	# --- Error breakdown ---
	error_query = (
		frappe.qb.from_(Run)
		.select(Run.error_code, fn.Count("*").as_("count"))
		.where(fn.Date(Run.started_at) >= from_d)
		.where(fn.Date(Run.started_at) <= to_d)
		.where(Run.status == "Error")
		.where(Run.error_code.isnotnull())
		.where(_origin_condition(Run, origin))
		.groupby(Run.error_code)
		.orderby(fn.Count("*"), order=frappe.qb.desc)
	)
	if model:
		error_query = error_query.where(Run.model == model)
	if error_code:
		error_query = error_query.where(Run.error_code == error_code)
	if process_model:
		error_query = error_query.where(Run.process_model == process_model)
	if agent_configuration:
		error_query = error_query.where(Run.agent_configuration == agent_configuration)

	error_breakdown = [
		{"error_code": cstr(r.get("error_code")), "count": cint(r.get("count"))}
		for r in error_query.run(as_dict=True)
	]

	# --- Summary ---
	total_errors = sum(r["errors"] for r in rows)
	most_common = error_breakdown[0]["error_code"] if error_breakdown else ""
	worst_element = ""
	worst_rate = 100.0
	for r in rows:
		if r["total_runs"] >= 1 and r["success_rate"] < worst_rate:
			worst_rate = r["success_rate"]
			worst_element = r["bpmn_label"] or r["bpmn_id"]

	total_retried = sum(1 for r in rows if cint(r.get("retry_rate")) > 0)
	total_recovered = sum(r["retry_recovered"] for r in rows)
	# Recovery rate: of all runs that had retries, how many ended up succeeding
	retried_runs = sum(
		cint(r["total_runs"] * r["retry_rate"] / 100) for r in rows
	)
	recovery_rate = flt((total_recovered / retried_runs) * 100, 1) if retried_runs else 0.0

	return {
		"rows": rows,
		"error_breakdown": error_breakdown,
		"summary": {
			"total_errors": total_errors,
			"most_common_error": most_common,
			"worst_element": worst_element,
			"retry_recovery_rate": recovery_rate,
		},
	}


# ---------------------------------------------------------------------------
# 4. Performance report
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_performance_report(
	from_date: str = None,
	to_date: str = None,
	model: str = None,
	bpmn_id: str = None,
	process_model: str = None,
	agent_configuration: str = None,
	origin: str = "production",
	group_by: str = "model",
) -> dict:
	"""Return latency/throughput data with percentiles, grouped by model +
	bpmn_id — or by the run's AI Agent Configuration + bpmn_id when
	``group_by="agent"`` (WI-001608)."""
	frappe.only_for("System Manager")
	group_by = group_by if group_by in ("model", "agent") else "model"
	from_d, to_d = _default_dates(from_date, to_date)

	Run = DocType("AI Agent Run")
	Step = DocType("AI Agent Step")
	group_field = Run.agent_configuration if group_by == "agent" else Run.model
	unattributed = "Unattributed" if group_by == "agent" else ""

	# --- Fetch all successful run durations for percentile calculation ---
	duration_query = (
		frappe.qb.from_(Run)
		.select(group_field.as_("group_key"), Run.bpmn_id, Run.bpmn_label, Run.duration_ms, Run.total_tokens, fn.Date(Run.started_at).as_("date"))
		.where(fn.Date(Run.started_at) >= from_d)
		.where(fn.Date(Run.started_at) <= to_d)
		.where(Run.status == "Success")
		.where(Run.duration_ms.isnotnull())
		.where(_origin_condition(Run, origin))
		.orderby(Run.model, Run.bpmn_id)
	)
	if model:
		duration_query = duration_query.where(Run.model == model)
	if bpmn_id:
		duration_query = duration_query.where(Run.bpmn_id == bpmn_id)
	if process_model:
		duration_query = duration_query.where(Run.process_model == process_model)
	if agent_configuration:
		duration_query = duration_query.where(Run.agent_configuration == agent_configuration)

	raw_durations = duration_query.run(as_dict=True)

	# --- Step counts per run (avg_steps) ---
	step_counts_query = (
		frappe.qb.from_(Step)
		.join(Run).on(Step.run == Run.name)
		.select(group_field.as_("group_key"), Run.bpmn_id, Step.run, fn.Count("*").as_("step_count"))
		.where(fn.Date(Run.started_at) >= from_d)
		.where(fn.Date(Run.started_at) <= to_d)
		.where(Run.status == "Success")
		.where(_origin_condition(Run, origin))
		.groupby(Step.run, group_field, Run.bpmn_id)
	)
	if model:
		step_counts_query = step_counts_query.where(Run.model == model)
	if bpmn_id:
		step_counts_query = step_counts_query.where(Run.bpmn_id == bpmn_id)
	if process_model:
		step_counts_query = step_counts_query.where(Run.process_model == process_model)

	step_count_rows = step_counts_query.run(as_dict=True)
	# Build map: (series, bpmn_id) -> list of step counts
	step_map = defaultdict(list)
	for s in step_count_rows:
		key = (cstr(s.get("group_key")) or unattributed, cstr(s.get("bpmn_id")))
		step_map[key].append(cint(s.get("step_count")))

	# --- Group durations by the series dimension + bpmn_id, compute percentiles ---
	grouped = defaultdict(list)
	token_grouped = defaultdict(list)
	label_map = {}
	for r in raw_durations:
		key = (cstr(r.get("group_key")) or unattributed, cstr(r.get("bpmn_id")))
		grouped[key].append(cint(r.get("duration_ms")))
		token_grouped[key].append(cint(r.get("total_tokens")))
		# Keep first non-empty label per key
		if key not in label_map and r.get("bpmn_label"):
			label_map[key] = cstr(r.get("bpmn_label"))

	rows = []
	for (m, b), durations in sorted(grouped.items()):
		durations_sorted = sorted(durations)
		n = len(durations_sorted)
		tokens = token_grouped.get((m, b), [])
		steps = step_map.get((m, b), [])
		# Resolve label: pick the first non-empty bpmn_label for this key
		label = label_map.get((m, b), b)
		rows.append({
			"model": m,
			"bpmn_id": b,
			"bpmn_label": label,
			"runs": n,
			"avg_duration_ms": cint(sum(durations_sorted) / n) if n else 0,
			"p50_duration_ms": durations_sorted[int(n * 0.5)] if n else 0,
			"p95_duration_ms": durations_sorted[min(int(n * 0.95), n - 1)] if n else 0,
			"max_duration_ms": durations_sorted[-1] if n else 0,
			"avg_steps": flt(sum(steps) / len(steps), 1) if steps else 0.0,
			"avg_tokens": cint(sum(tokens) / len(tokens)) if tokens else 0,
		})

	# --- Trend: daily p50/p95 across all filtered runs ---
	daily_durations = defaultdict(list)
	for r in raw_durations:
		daily_durations[cstr(r.get("date"))].append(cint(r.get("duration_ms")))

	all_dates = []
	d = from_d
	while d <= to_d:
		all_dates.append(cstr(d))
		d = getdate(add_days(cstr(d), 1))

	p50_trend = []
	p95_trend = []
	for d in all_dates:
		vals = sorted(daily_durations.get(d, []))
		n = len(vals)
		p50_trend.append(vals[int(n * 0.5)] if n else 0)
		p95_trend.append(vals[min(int(n * 0.95), n - 1)] if n else 0)

	return {
		"rows": rows,
		"trend": {
			"labels": all_dates,
			"p50": p50_trend,
			"p95": p95_trend,
		},
	}


# ---------------------------------------------------------------------------
# 5. Run step detail (drill-down)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_run_steps(run_name: str) -> list:
	"""Return steps for a single AI Agent Run.

	WI-001360: each step carries its AI Agent Tool Call child rows so the
	instance detail view can render subprocess runs as Run → expandable
	Steps (one per LLM turn) → the individual tool calls that turn made —
	instead of the flat single-call view built for plain AI Agent Tasks.
	Per-tool analytics must aggregate through these rows, not the flat
	tool_name column (a single turn can contain several calls).
	"""
	frappe.only_for("System Manager")

	steps = frappe.get_list(
		"AI Agent Step",
		filters={"run": run_name},
		fields=[
			"name", "step_index", "role", "tool_name", "content",
			"latency_ms", "prompt_tokens", "completion_tokens", "cost",
		],
		order_by="step_index asc",
		limit_page_length=100,
	)

	step_names = [s.name for s in steps]
	calls_by_step = {}
	if step_names and frappe.db.exists("DocType", "AI Agent Tool Call"):
		for call in frappe.get_all(
			"AI Agent Tool Call",
			filters={"parent": ["in", step_names], "parenttype": "AI Agent Step"},
			fields=["parent", "tool_name", "tool_source", "tool_args", "tool_result", "status"],
			order_by="idx asc",
		):
			calls_by_step.setdefault(call.pop("parent"), []).append(call)

	for step in steps:
		step["tool_calls"] = calls_by_step.get(step.name, [])
	return steps


@frappe.whitelist()
def get_run_totals_crosscheck(run_name: str) -> dict:
	"""WI-001360 Scenario 4: verify a run's rolled-up totals against the sum
	of its Step rows — cross-checked, not just trusted."""
	frappe.only_for("System Manager")

	run = frappe.db.get_value(
		"AI Agent Run", run_name, ["total_tokens", "estimated_cost"], as_dict=True
	)
	if not run:
		frappe.throw(_("AI Agent Run '{0}' not found").format(run_name))

	Step = DocType("AI Agent Step")
	sums = (
		frappe.qb.from_(Step)
		.select(
			fn.Sum(Step.prompt_tokens + Step.completion_tokens).as_("tokens"),
			fn.Sum(Step.cost).as_("cost"),
		)
		.where(Step.run == run_name)
		.run(as_dict=True)
	)[0]

	step_tokens = cint(sums.get("tokens"))
	step_cost = flt(sums.get("cost"), 4)
	return {
		"run_total_tokens": cint(run.total_tokens),
		"step_total_tokens": step_tokens,
		"tokens_match": cint(run.total_tokens) == step_tokens,
		"run_estimated_cost": flt(run.estimated_cost, 4),
		"step_total_cost": step_cost,
		"cost_match": abs(flt(run.estimated_cost, 4) - step_cost) < 0.0001,
	}


# ---------------------------------------------------------------------------
# 6. Cost allocation (WI-001668)
# ---------------------------------------------------------------------------
#
# Finance needs monthly AI spend attributed to a person and their department:
#   * non-chat  -> per process, via the process's Process Owner
#   * chat      -> per conversation, via the conversation's owner
#
# A run is a chat run when its BPMN instance's context is a Chat Conversation
# (set in utils/chat_persistence.py); anything else — including runs with no
# instance — is non-chat. Eval-origin runs are included, per WI-001668.

ALLOCATION_AXES = ("process_owner", "chat_user")


def _month_expr(Run):
	return DateFormat(Run.started_at, "%Y-%m")


def _departments_for(users: list) -> dict:
	"""Map user -> Employee.department for the given users (one bulk query)."""
	users = [u for u in set(users) if u]
	if not users:
		return {}
	rows = frappe.get_all(
		"Employee",
		filters={"user_id": ["in", users]},
		fields=["user_id", "department"],
	)
	return {r["user_id"]: r["department"] for r in rows if r.get("department")}


def _allocation_rows(axis: str, from_d, to_d) -> list:
	"""Monthly usage rows for the requested allocation axis."""
	Run = DocType("AI Agent Run")
	Inst = DocType("BPMN Process Instance")
	month = _month_expr(Run)
	in_range = (fn.Date(Run.started_at) >= from_d) & (fn.Date(Run.started_at) <= to_d)

	if axis == "chat_user":
		Conv = DocType("Chat Conversation")
		# LEFT join, and group on the instance's context_docname rather than
		# Conv.name: a run whose Chat Conversation has since been deleted is
		# still a chat run, so it must not vanish. An inner join dropped it
		# from this axis while the process-owner axis already excluded it for
		# being chat — leaving its spend unallocated in both views.
		q = (
			frappe.qb.from_(Run)
			.inner_join(Inst).on(Inst.name == Run.instance)
			.left_join(Conv).on(Conv.name == Inst.context_docname)
			.select(
				month.as_("month"),
				Conv.owner.as_("person"),
				Inst.context_docname.as_("subject"),
				Conv.title.as_("subject_label"),
				fn.Count("*").as_("runs"),
				fn.Sum(Run.total_tokens).as_("tokens"),
				fn.Sum(Run.estimated_cost).as_("cost"),
			)
			.where(in_range)
			.where(Inst.context_doctype == "Chat Conversation")
			.groupby(month, Conv.owner, Inst.context_docname, Conv.title)
		)
	else:
		Model = DocType("BPMN Process Model")
		Proc = DocType("Process")
		q = (
			frappe.qb.from_(Run)
			.left_join(Inst).on(Inst.name == Run.instance)
			.left_join(Model).on(Model.name == Run.process_model)
			.left_join(Proc).on(Proc.name == Model.process_name)
			.select(
				month.as_("month"),
				Proc.process_owner.as_("person"),
				Run.process_model.as_("subject"),
				Model.process_name.as_("subject_label"),
				fn.Count("*").as_("runs"),
				fn.Sum(Run.total_tokens).as_("tokens"),
				fn.Sum(Run.estimated_cost).as_("cost"),
			)
			.where(in_range)
			.where(Inst.context_doctype.isnull() | (Inst.context_doctype != "Chat Conversation"))
			.groupby(month, Proc.process_owner, Run.process_model, Model.process_name)
		)

	raw = q.run(as_dict=True)
	departments = _departments_for([r.get("person") for r in raw])
	rows = []
	for r in raw:
		person = cstr(r.get("person"))
		rows.append({
			"month": cstr(r.get("month")),
			"person": person,
			"department": departments.get(person) or "",
			"subject": cstr(r.get("subject")),
			"subject_label": cstr(r.get("subject_label")) or cstr(r.get("subject")),
			"runs": cint(r.get("runs")),
			"tokens": cint(r.get("tokens")),
			"cost": flt(r.get("cost"), 6),
		})
	rows.sort(key=lambda x: (x["month"], x["department"], x["person"], x["subject_label"]), reverse=False)
	return rows


def _period_totals(from_d, to_d) -> dict:
	"""Unfiltered totals for the whole period, across both allocation axes.

	Each axis shows only its own slice (non-chat vs chat), so the axis totals
	are not the period's AI spend. The UI needs this to say so plainly instead
	of labelling a slice "Total".
	"""
	Run = DocType("AI Agent Run")
	row = (
		frappe.qb.from_(Run)
		.select(
			fn.Count("*").as_("runs"),
			fn.Sum(Run.total_tokens).as_("tokens"),
			fn.Sum(Run.estimated_cost).as_("cost"),
		)
		.where(fn.Date(Run.started_at) >= from_d)
		.where(fn.Date(Run.started_at) <= to_d)
	).run(as_dict=True)
	r = row[0] if row else {}
	return {
		"runs": cint(r.get("runs")),
		"tokens": cint(r.get("tokens")),
		"cost": flt(r.get("cost"), 6),
	}


def _models_missing_pricing(from_d, to_d) -> list:
	"""Models used in the period that have no rate card on their AI Model, so
	their spend silently counts as 0 — finance needs to know."""
	from one_bpmn.agents.pricing import get_model_pricing

	Run = DocType("AI Agent Run")
	used = (
		frappe.qb.from_(Run)
		.select(Run.model)
		.distinct()
		.where(fn.Date(Run.started_at) >= from_d)
		.where(fn.Date(Run.started_at) <= to_d)
		.where(Run.model.isnotnull())
		.where(Run.model != "")
	).run(as_dict=True)
	return sorted({r["model"] for r in used if not get_model_pricing(r["model"])})


@frappe.whitelist()
def get_cost_allocation(from_date: str = None, to_date: str = None, axis: str = "process_owner") -> dict:
	"""Monthly AI spend allocated by Process Owner (non-chat) or chat user
	(WI-001668), with department, totals, and a pricing-gap warning."""
	frappe.only_for("System Manager")
	if axis not in ALLOCATION_AXES:
		frappe.throw(_("axis must be one of {0}").format(", ".join(ALLOCATION_AXES)))
	from_d, to_d = _default_dates(from_date, to_date, days=30)

	rows = _allocation_rows(axis, from_d, to_d)
	return {
		"axis": axis,
		"from_date": cstr(from_d),
		"to_date": cstr(to_d),
		"rows": rows,
		# Totals for THIS axis only — the chat and process-owner axes each
		# cover half the runs. Compare against period_totals below.
		"totals": {
			"runs": sum(r["runs"] for r in rows),
			"tokens": sum(r["tokens"] for r in rows),
			"cost": flt(sum(r["cost"] for r in rows), 6),
			"people": len({r["person"] for r in rows if r["person"]}),
			"departments": len({r["department"] for r in rows if r["department"]}),
		},
		"period_totals": _period_totals(from_d, to_d),
		"models_missing_pricing": _models_missing_pricing(from_d, to_d),
	}


@frappe.whitelist()
def export_cost_allocation(
	from_date: str = None, to_date: str = None, axis: str = "process_owner", fmt: str = "xlsx"
):
	"""Download the cost allocation as XLSX or CSV (WI-001668). Returns a file
	response, so the client navigates to this endpoint rather than fetching it."""
	frappe.only_for("System Manager")
	if axis not in ALLOCATION_AXES:
		frappe.throw(_("axis must be one of {0}").format(", ".join(ALLOCATION_AXES)))
	if fmt not in ("xlsx", "csv"):
		frappe.throw(_("fmt must be 'xlsx' or 'csv'"))
	from_d, to_d = _default_dates(from_date, to_date, days=30)

	subject_header = _("Chat") if axis == "chat_user" else _("Process")
	person_header = _("User") if axis == "chat_user" else _("Process Owner")
	data = [[_("Month"), _("Department"), person_header, subject_header,
			 _("Runs"), _("Tokens"), _("Cost")]]
	for r in _allocation_rows(axis, from_d, to_d):
		data.append([
			r["month"], r["department"], r["person"], r["subject_label"],
			r["runs"], r["tokens"], flt(r["cost"], 6),
		])

	stem = f"cost-allocation-{axis}-{from_d}-to-{to_d}"
	if fmt == "xlsx":
		from frappe.utils.xlsxutils import make_xlsx

		content = make_xlsx(data, "Cost Allocation").getvalue()
		filename = f"{stem}.xlsx"
	else:
		import csv
		import io

		buf = io.StringIO()
		csv.writer(buf).writerows(data)
		content = buf.getvalue().encode("utf-8-sig")  # BOM so Excel reads UTF-8
		filename = f"{stem}.csv"

	frappe.response["type"] = "binary"
	frappe.response["filename"] = filename
	frappe.response["filecontent"] = content
