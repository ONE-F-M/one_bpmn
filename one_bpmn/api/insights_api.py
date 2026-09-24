# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
API endpoints for the AI Agent Insights dashboard.

All methods are whitelisted, require System Manager role, and use
frappe.qb (Query Builder) exclusively — no raw SQL.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta
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


def _previous_period(from_d, to_d):
	"""Same-length window ending the day before *from_d* (see work order)."""
	length = (to_d - from_d).days
	previous_to = add_days(from_d, -1)
	previous_from = add_days(previous_to, -length)
	return getdate(previous_from), getdate(previous_to)


def _grain_for(from_d, to_d) -> str:
	span = (to_d - from_d).days + 1
	if span <= 31:
		return "day"
	if span <= 120:
		return "week"
	return "month"


def _bucket_start(d, grain: str):
	d = getdate(d)
	if grain == "week":
		return d - timedelta(days=d.weekday())
	if grain == "month":
		return d.replace(day=1)
	return d


def _bucket_labels(from_d, to_d, grain: str) -> list:
	"""Ordered, de-duplicated bucket-start labels spanning the range."""
	labels = {}
	d = from_d
	while d <= to_d:
		labels[cstr(_bucket_start(d, grain))] = True
		d = getdate(add_days(cstr(d), 1))
	return list(labels)


def _apply_common_filters(query, Run, model=None, provider=None, process_model=None, agent_configuration=None):
	if model:
		query = query.where(Run.model == model)
	if provider:
		query = query.where(Run.provider == provider)
	if process_model:
		query = query.where(Run.process_model == process_model)
	if agent_configuration:
		query = query.where(Run.agent_configuration == agent_configuration)
	return query


def _usage_totals(
	from_d,
	to_d,
	origin: str = "production",
	model: str = None,
	provider: str = None,
	process_model: str = None,
	agent_configuration: str = None,
) -> dict:
	"""Aggregate usage metrics for one period, per the usage metric definitions."""
	Run = DocType("AI Agent Run")
	query = (
		frappe.qb.from_(Run)
		.select(
			fn.Count("*").as_("runs"),
			fn.Sum(Case().when(Run.status != "Running", 1).else_(0)).as_("decided"),
			fn.Sum(Case().when(Run.status == "Success", 1).else_(0)).as_("successes"),
			fn.Sum(Run.estimated_cost).as_("cost"),
			fn.Sum(Run.total_tokens).as_("tokens"),
			fn.Sum(Run.total_prompt_tokens).as_("prompt_tokens"),
			fn.Sum(Run.total_completion_tokens).as_("completion_tokens"),
			fn.Sum(Run.total_cache_read_tokens).as_("cache_read_tokens"),
			fn.Sum(Run.total_cache_write_tokens).as_("cache_write_tokens"),
		)
		.where(fn.Date(Run.started_at) >= from_d)
		.where(fn.Date(Run.started_at) <= to_d)
		.where(_origin_condition(Run, origin))
	)
	query = _apply_common_filters(query, Run, model, provider, process_model, agent_configuration)
	r = query.run(as_dict=True)[0]

	runs = cint(r.get("runs"))
	decided = cint(r.get("decided"))
	successes = cint(r.get("successes"))
	cost = flt(r.get("cost"), 6)
	tokens = cint(r.get("tokens"))
	prompt_tokens = cint(r.get("prompt_tokens"))
	completion_tokens = cint(r.get("completion_tokens"))
	cache_read_tokens = cint(r.get("cache_read_tokens"))
	cache_write_tokens = cint(r.get("cache_write_tokens"))

	success_rate = flt((successes / decided) * 100, 1) if decided else 0.0
	cache_hit_rate = flt((cache_read_tokens / prompt_tokens) * 100, 1) if prompt_tokens else 0.0
	input_tokens = prompt_tokens - cache_read_tokens - cache_write_tokens

	return {
		"runs": runs,
		"cost": cost,
		"tokens": tokens,
		"input_tokens": input_tokens,
		"output_tokens": completion_tokens,
		"cached_tokens": cache_read_tokens,
		"success_rate": success_rate,
		"cache_hit_rate": cache_hit_rate,
	}


def _compute_deltas(current: dict, previous: dict) -> dict:
	"""Percentage change per key; null when the previous period has no runs
	or the previous value for that key is 0."""
	delta = {}
	no_previous_activity = not previous or cint(previous.get("runs")) == 0
	for key, cur_val in current.items():
		if no_previous_activity:
			delta[key] = None
			continue
		prev_val = previous.get(key)
		if not prev_val:
			delta[key] = None
			continue
		delta[key] = flt(((cur_val - prev_val) / prev_val) * 100, 1)
	return delta


def _daily_metric_rows(
	from_d,
	to_d,
	origin: str = "production",
	model: str = None,
	provider: str = None,
	process_model: str = None,
	agent_configuration: str = None,
) -> list:
	"""One row per day with runs/cost/tokens, grouped by DATE(started_at)."""
	Run = DocType("AI Agent Run")
	query = (
		frappe.qb.from_(Run)
		.select(
			fn.Date(Run.started_at).as_("date"),
			fn.Count("*").as_("runs"),
			fn.Sum(Run.estimated_cost).as_("cost"),
			fn.Sum(Run.total_tokens).as_("tokens"),
		)
		.where(fn.Date(Run.started_at) >= from_d)
		.where(fn.Date(Run.started_at) <= to_d)
		.where(_origin_condition(Run, origin))
		.groupby(fn.Date(Run.started_at))
	)
	query = _apply_common_filters(query, Run, model, provider, process_model, agent_configuration)
	rows = query.run(as_dict=True)
	return [
		{
			"date": cstr(r.get("date")),
			"runs": cint(r.get("runs")),
			"cost": flt(r.get("cost"), 6),
			"tokens": cint(r.get("tokens")),
		}
		for r in rows
	]


def _bucketed_series(from_d, to_d, daily_rows: list, grain: str) -> dict:
	"""Bucket daily rows into day/week/month buckets; empty buckets are 0."""
	labels = _bucket_labels(from_d, to_d, grain)
	cost_by_bucket = defaultdict(float)
	tokens_by_bucket = defaultdict(int)
	runs_by_bucket = defaultdict(int)
	for row in daily_rows:
		bucket = cstr(_bucket_start(row["date"], grain))
		cost_by_bucket[bucket] += row["cost"]
		tokens_by_bucket[bucket] += row["tokens"]
		runs_by_bucket[bucket] += row["runs"]
	return {
		"labels": labels,
		"cost": [flt(cost_by_bucket.get(label, 0), 6) for label in labels],
		"tokens": [cint(tokens_by_bucket.get(label, 0)) for label in labels],
		"runs": [cint(runs_by_bucket.get(label, 0)) for label in labels],
	}


def _series_rows(
	from_d,
	to_d,
	origin: str,
	group_by: str,
	model: str = None,
	provider: str = None,
	process_model: str = None,
	agent_configuration: str = None,
) -> list:
	"""Per-group usage totals for the cost/token report's ``series`` array."""
	Run = DocType("AI Agent Run")
	group_fields = [Run.agent_configuration] if group_by == "agent" else [Run.model, Run.provider]
	query = (
		frappe.qb.from_(Run)
		.select(
			group_fields[0].as_("group_key"),
			fn.Min(Run.provider).as_("provider_min"),
			fn.Max(Run.provider).as_("provider_max"),
			fn.Count("*").as_("runs"),
			fn.Sum(Run.estimated_cost).as_("cost"),
			fn.Sum(Run.total_tokens).as_("tokens"),
			fn.Sum(Run.total_prompt_tokens).as_("prompt_tokens"),
			fn.Sum(Run.total_completion_tokens).as_("completion_tokens"),
			fn.Sum(Run.total_cache_read_tokens).as_("cache_read_tokens"),
			fn.Sum(Run.total_cache_write_tokens).as_("cache_write_tokens"),
		)
		.where(fn.Date(Run.started_at) >= from_d)
		.where(fn.Date(Run.started_at) <= to_d)
		.where(_origin_condition(Run, origin))
		.groupby(*group_fields)
	)
	query = _apply_common_filters(query, Run, model, provider, process_model, agent_configuration)
	raw_rows = query.run(as_dict=True)

	unattributed = "Unattributed" if group_by == "agent" else ""
	series = []
	for r in raw_rows:
		name = cstr(r.get("group_key")) or unattributed
		provider_min = cstr(r.get("provider_min"))
		# An agent row names its provider only when all its runs share one; Unattributed never does.
		row_provider = provider_min if provider_min == cstr(r.get("provider_max")) else ""
		if group_by == "agent" and not r.get("group_key"):
			row_provider = ""
		prompt_tokens = cint(r.get("prompt_tokens"))
		cache_read_tokens = cint(r.get("cache_read_tokens"))
		cache_write_tokens = cint(r.get("cache_write_tokens"))
		series.append({
			"name": name,
			"provider": row_provider or None,
			"runs": cint(r.get("runs")),
			"cost": flt(r.get("cost"), 6),
			"tokens": cint(r.get("tokens")),
			"input_tokens": prompt_tokens - cache_read_tokens - cache_write_tokens,
			"output_tokens": cint(r.get("completion_tokens")),
			"cached_tokens": cache_read_tokens,
		})
	return series


def _filter_options(from_d, to_d, origin: str) -> dict:
	"""Distinct filter values in the range, filtered by range and origin only.
	The other filters are not applied, so a narrowed query still lists every value."""
	Run = DocType("AI Agent Run")

	def _distinct(field):
		query = (
			frappe.qb.from_(Run)
			.select(field.as_("value"))
			.distinct()
			.where(fn.Date(Run.started_at) >= from_d)
			.where(fn.Date(Run.started_at) <= to_d)
			.where(_origin_condition(Run, origin))
			.where(field.isnotnull())
			.where(field != "")
		)
		return sorted({cstr(r.get("value")) for r in query.run(as_dict=True)})

	return {
		"models": _distinct(Run.model),
		"providers": _distinct(Run.provider),
		"agents": _distinct(Run.agent_configuration),
		"processes": _distinct(Run.process_model),
	}


# ---------------------------------------------------------------------------
# 1. Overview cards
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_agent_overview(
	days: int = None,
	from_date: str = None,
	to_date: str = None,
	agent_configuration: str = None,
	model: str = None,
	provider: str = None,
	process_model: str = None,
	origin: str = "production",
) -> dict:
	"""Return the overview number cards for the from_date/to_date range and filters.
	runs_today and active_errors always cover today only. The days parameter is ignored."""
	frappe.only_for("System Manager")
	if days is not None:
		frappe.logger("one_bpmn").warning(
			"get_agent_overview: 'days' parameter is deprecated and ignored; use from_date/to_date instead."
		)

	from_d, to_d = _default_dates(from_date, to_date)
	previous_from, previous_to = _previous_period(from_d, to_d)
	grain = _grain_for(from_d, to_d)

	Run = DocType("AI Agent Run")
	today_date = getdate(today())

	def _today_filter(status_value=None):
		query = (
			frappe.qb.from_(Run)
			.select(fn.Count("*"))
			.where(fn.Date(Run.started_at) == today_date)
			.where(_origin_condition(Run, origin))
		)
		query = _apply_common_filters(query, Run, model, provider, process_model, agent_configuration)
		if status_value:
			query = query.where(Run.status == status_value)
		return cint(query.run()[0][0])

	runs_today = _today_filter()
	active_errors = _today_filter("Error")

	current = _usage_totals(from_d, to_d, origin, model, provider, process_model, agent_configuration)
	previous = _usage_totals(previous_from, previous_to, origin, model, provider, process_model, agent_configuration)
	delta = _compute_deltas(current, previous)

	# Avg latency of successful runs over the range; legacy key, not part of _usage_totals.
	avg_latency_query = (
		frappe.qb.from_(Run)
		.select(fn.Avg(Run.duration_ms))
		.where(fn.Date(Run.started_at) >= from_d)
		.where(fn.Date(Run.started_at) <= to_d)
		.where(_origin_condition(Run, origin))
		.where(Run.status == "Success")
	)
	avg_latency_query = _apply_common_filters(avg_latency_query, Run, model, provider, process_model, agent_configuration)
	avg_latency = cint(avg_latency_query.run()[0][0])

	daily_rows = _daily_metric_rows(from_d, to_d, origin, model, provider, process_model, agent_configuration)
	sparklines = _bucketed_series(from_d, to_d, daily_rows, grain)

	return {
		# Legacy keys, unchanged shape:
		"runs_today": runs_today,
		"success_rate": current["success_rate"],
		"total_cost": current["cost"],
		"active_errors": active_errors,
		"avg_latency_ms": avg_latency,
		"total_tokens": current["tokens"],
		# New range/comparison data:
		"from_date": cstr(from_d),
		"to_date": cstr(to_d),
		"previous_from": cstr(previous_from),
		"previous_to": cstr(previous_to),
		"grain": grain,
		"current": current,
		"previous": previous,
		"delta": delta,
		"sparklines": sparklines,
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
	previous_from, previous_to = _previous_period(from_d, to_d)
	grain = _grain_for(from_d, to_d)

	Run = DocType("AI Agent Run")

	# The series dimension: model (classic) or the run's agent.
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
	query = _apply_common_filters(query, Run, model, provider, process_model, agent_configuration)

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

	# Pivot chart_data by the grouped dimension per day, week or month bucket.
	bucket_labels = _bucket_labels(from_d, to_d, grain)

	series_bucket_cost = defaultdict(lambda: defaultdict(float))
	series_bucket_tokens = defaultdict(lambda: defaultdict(int))
	series_seen = set()
	for r in rows:
		bucket = cstr(_bucket_start(r["date"], grain))
		series_bucket_cost[r["series"]][bucket] += r["total_cost"]
		series_bucket_tokens[r["series"]][bucket] += r["total_tokens"]
		series_seen.add(r["series"])

	datasets = []
	for m in sorted(series_seen):
		datasets.append({
			"model": m,  # legacy key the chart legend binds to
			"label": m,
			"values": [flt(series_bucket_cost[m].get(b, 0), 6) for b in bucket_labels],
			"tokens": [cint(series_bucket_tokens[m].get(b, 0)) for b in bucket_labels],
		})

	# Summary keeps the legacy shape.
	summary_cost = sum(r["total_cost"] for r in rows)
	summary_runs = sum(r["total_runs"] for r in rows)
	summary_tokens = sum(r["total_tokens"] for r in rows)

	current = _usage_totals(from_d, to_d, origin, model, provider, process_model, agent_configuration)
	previous = _usage_totals(previous_from, previous_to, origin, model, provider, process_model, agent_configuration)
	delta = _compute_deltas(current, previous)
	series = _series_rows(from_d, to_d, origin, group_by, model, provider, process_model, agent_configuration)
	filter_options = _filter_options(from_d, to_d, origin)

	return {
		"rows": rows,
		"chart_data": {
			"labels": bucket_labels,
			"datasets": datasets,
		},
		"summary": {
			"total_cost": flt(summary_cost, 6),
			"total_runs": summary_runs,
			"total_tokens": summary_tokens,
		},
		"from_date": cstr(from_d),
		"to_date": cstr(to_d),
		"previous_from": cstr(previous_from),
		"previous_to": cstr(previous_to),
		"grain": grain,
		"current": current,
		"previous": previous,
		"delta": delta,
		"total": {
			"cost": current["cost"],
			"runs": current["runs"],
			"tokens": current["tokens"],
			"input_tokens": current["input_tokens"],
			"output_tokens": current["output_tokens"],
			"cached_tokens": current["cached_tokens"],
		},
		"series": series,
		"filter_options": filter_options,
	}


@frappe.whitelist()
def export_cost_token_report(
	from_date: str = None,
	to_date: str = None,
	model: str = None,
	provider: str = None,
	process_model: str = None,
	agent_configuration: str = None,
	origin: str = "production",
	group_by: str = "model",
	fmt: str = "csv",
):
	"""Download the cost/token report's daily rows as CSV or XLSX. Returns a
	file response, so the client navigates to this endpoint rather than
	fetching it."""
	frappe.only_for("System Manager")
	if fmt not in ("csv", "xlsx"):
		frappe.throw(_("fmt must be 'csv' or 'xlsx'"))

	report = get_cost_token_report(
		from_date=from_date,
		to_date=to_date,
		model=model,
		provider=provider,
		process_model=process_model,
		agent_configuration=agent_configuration,
		origin=origin,
		group_by=group_by,
	)

	header = [
		_("Date"), _("Series"), _("Provider"), _("Runs"), _("Total Tokens"),
		_("Avg Tokens"), _("Total Cost"), _("Avg Cost"), _("Input Cost"), _("Output Cost"),
	]
	data = [header]
	for r in report["rows"]:
		data.append([
			r["date"], r["series"], r["provider"], r["total_runs"], r["total_tokens"],
			r["avg_tokens"], r["total_cost"], r["avg_cost"], r["input_cost"], r["output_cost"],
		])

	stem = f"usage-{group_by}-{report['from_date']}-to-{report['to_date']}"
	if fmt == "xlsx":
		from frappe.utils.xlsxutils import make_xlsx

		content = make_xlsx(data, "Usage").getvalue()
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


# ---------------------------------------------------------------------------
# 3. Error report
# ---------------------------------------------------------------------------

COUNTED_EXCLUDED_STATUSES = ("Running", "Suspended")
ISSUE_KEY_PARTS = 4
ISSUE_RUNS_MAX_LIMIT = 50
MESSAGE_CHARS = 200


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
	provider: str | None = None,
) -> dict:
	"""Error rate over time, errors by code, one issue per code and element, and a summary.

	The error_code filter narrows issues only; timeseries, codes and summary always cover every code.
	"""
	frappe.only_for("System Manager")
	group_by = group_by if group_by in ("model", "agent") else "model"
	from_d, to_d = _default_dates(from_date, to_date)
	previous_from, previous_to = _previous_period(from_d, to_d)
	grain = _grain_for(from_d, to_d)
	filters = {
		"model": model,
		"provider": provider,
		"process_model": process_model,
		"agent_configuration": agent_configuration,
	}

	current = _error_period(from_d, to_d, origin, filters, group_by)
	previous = _error_period(previous_from, previous_to, origin, filters, group_by)
	codes = _error_codes(current, from_d, origin)
	issues = _error_issues(current, previous, from_d, to_d, origin, filters, group_by, error_code)
	summary = _error_summary(current, previous)

	rows, error_breakdown, legacy_summary = _legacy_error_report(
		from_d, to_d, origin, group_by, model, error_code, process_model, agent_configuration
	)
	summary.update(legacy_summary)

	return {
		"grain": grain,
		"from_date": cstr(from_d),
		"to_date": cstr(to_d),
		"timeseries": _error_timeseries(from_d, to_d, origin, filters, grain),
		"codes": codes,
		"issues": issues,
		"summary": summary,
		"rows": rows,
		"error_breakdown": error_breakdown,
	}


@frappe.whitelist()
def get_issue_runs(
	key: str,
	from_date: str | None = None,
	to_date: str | None = None,
	origin: str = "production",
	limit: int = 3,
	offset: int = 0,
	group_by: str = "model",
) -> dict:
	"""The failed top-level runs of one issue in the range, newest first, paged by limit and offset."""
	frappe.only_for("System Manager")
	parts = cstr(key).split("|")
	if len(parts) != ISSUE_KEY_PARTS:
		frappe.throw(_("Issue key must be error_code|bpmn_id|process_model|series"))
	group_by = group_by if group_by in ("model", "agent") else "model"
	from_d, to_d = _default_dates(from_date, to_date)
	limit = min(max(cint(limit), 1), ISSUE_RUNS_MAX_LIMIT)
	offset = max(cint(offset), 0)

	Run = DocType("AI Agent Run")
	fields = (Run.error_code, Run.bpmn_id, Run.process_model, _series_field(Run, group_by))
	query = _in_range(frappe.qb.from_(Run), Run, from_d, to_d, origin).where(Run.status == "Error")
	query = query.where(Run.parent_run.isnull() | (Run.parent_run == ""))
	for field, value in zip(fields, parts, strict=True):
		query = query.where(field == value) if value else query.where(field.isnull() | (field == ""))

	total = query.select(fn.Count("*").as_("n")).run(as_dict=True)[0]["n"]
	runs = (
		query.select(Run.name, Run.started_at, Run.error_message, Run.retry_count, Run.duration_ms)
		.orderby(Run.started_at, order=frappe.qb.desc)
		.limit(limit)
		.offset(offset)
		.run(as_dict=True)
	)
	return {
		"total": cint(total),
		"runs": [
			{
				"name": r.name,
				"started_at": cstr(r.started_at),
				"error_message": cstr(r.error_message)[:MESSAGE_CHARS],
				"retry_count": cint(r.retry_count),
				"duration_ms": cint(r.duration_ms),
			}
			for r in runs
		],
	}


@frappe.whitelist()
def export_error_report(
	from_date: str | None = None,
	to_date: str | None = None,
	model: str | None = None,
	error_code: str | None = None,
	process_model: str | None = None,
	agent_configuration: str | None = None,
	origin: str = "production",
	group_by: str = "model",
	provider: str | None = None,
	fmt: str = "csv",
):
	"""Download the error report's issues, one row per issue with every column, as CSV or XLSX."""
	frappe.only_for("System Manager")
	if fmt not in ("csv", "xlsx"):
		frappe.throw(_("fmt must be 'csv' or 'xlsx'"))

	report = get_error_report(
		from_date=from_date,
		to_date=to_date,
		model=model,
		error_code=error_code,
		process_model=process_model,
		agent_configuration=agent_configuration,
		origin=origin,
		group_by=group_by,
		provider=provider,
	)
	columns = [
		("error_code", _("Error type")),
		("bpmn_label", _("Element")),
		("process_model", _("Process")),
		("series", _("AI Agent") if group_by == "agent" else _("Model")),
		("errors", _("Errors")),
		("runs", _("Runs")),
		("error_rate", _("Error rate")),
		("previous_error_rate", _("Previous error rate")),
		("delta_pt", _("Change (pt)")),
		("first_seen", _("First seen")),
		("last_seen", _("Last seen")),
		("is_new", _("New")),
		("retried", _("Retried")),
		("retry_recovered", _("Recovered by retry")),
		("p95_duration_ms", _("P95 duration (ms)")),
		("last_message", _("Last message")),
	]
	data = [[label for _field, label in columns]]
	data += [[issue[field] for field, _label in columns] for issue in report["issues"]]

	stem = f"errors-{group_by}-{report['from_date']}-to-{report['to_date']}"
	if fmt == "xlsx":
		from frappe.utils.xlsxutils import make_xlsx

		content = make_xlsx(data, "Errors").getvalue()
		filename = f"{stem}.xlsx"
	else:
		import csv
		import io

		buf = io.StringIO()
		csv.writer(buf).writerows(data)
		content = buf.getvalue().encode("utf-8-sig")
		filename = f"{stem}.csv"

	frappe.response["type"] = "binary"
	frappe.response["filename"] = filename
	frappe.response["filecontent"] = content


def _series_field(Run, group_by: str):
	return Run.agent_configuration if group_by == "agent" else Run.model


def _in_range(query, Run, from_d, to_d, origin: str):
	return (
		query.where(fn.Date(Run.started_at) >= from_d)
		.where(fn.Date(Run.started_at) <= to_d)
		.where(_origin_condition(Run, origin))
	)


def _scoped(query, Run, from_d, to_d, origin: str, filters: dict):
	return _apply_common_filters(_in_range(query, Run, from_d, to_d, origin), Run, **filters)


def _rate(part, whole) -> float:
	return flt(part / whole * 100, 1) if whole else 0.0


def _issue_key(error_code, bpmn_id, process_model, series) -> str:
	return "|".join(cstr(v) for v in (error_code, bpmn_id, process_model, series))


def _error_period(from_d, to_d, origin: str, filters: dict, group_by: str) -> dict:
	"""Counted-run and error aggregates for one period, keyed by element and by issue."""
	Run = DocType("AI Agent Run")
	series = _series_field(Run, group_by)
	elements = _scoped(frappe.qb.from_(Run), Run, from_d, to_d, origin, filters)
	elements = (
		elements.select(
			Run.bpmn_id,
			Run.process_model,
			series.as_("series"),
			fn.Max(Run.bpmn_label).as_("bpmn_label"),
			fn.Count("*").as_("runs"),
			fn.Sum(Case().when(Run.retry_count > 0, 1).else_(0)).as_("retried"),
			fn.Sum(Case().when((Run.retry_count > 0) & (Run.status == "Success"), 1).else_(0)).as_(
				"recovered"
			),
		)
		.where(Run.status.notin(COUNTED_EXCLUDED_STATUSES))
		.groupby(Run.bpmn_id, Run.process_model, series)
		.run(as_dict=True)
	)
	errors = (
		_scoped(frappe.qb.from_(Run), Run, from_d, to_d, origin, filters)
		.select(
			Run.error_code, Run.bpmn_id, Run.process_model, series.as_("series"), fn.Count("*").as_("errors")
		)
		.where(Run.status == "Error")
		.groupby(Run.error_code, Run.bpmn_id, Run.process_model, series)
		.run(as_dict=True)
	)
	suspended = (
		_scoped(frappe.qb.from_(Run), Run, from_d, to_d, origin, filters)
		.select(fn.Count("*").as_("n"))
		.where(Run.status == "Suspended")
		.run(as_dict=True)[0]["n"]
	)
	return {
		"elements": {(r.bpmn_id, r.process_model, r.series): r for r in elements},
		"errors": {(r.error_code, r.bpmn_id, r.process_model, r.series): cint(r.errors) for r in errors},
		"suspended": cint(suspended),
	}


def _error_summary(current: dict, previous: dict) -> dict:
	"""Tile figures for the range and the period before it, computed from counts."""

	def totals(period):
		elements = period["elements"].values()
		runs = sum(cint(e.runs) for e in elements)
		errors = sum(period["errors"].values())
		retried = sum(cint(e.retried) for e in elements)
		return runs, errors, retried, sum(cint(e.recovered) for e in elements)

	runs, errors, retried, recovered = totals(current)
	previous_runs, previous_errors, previous_retried, previous_recovered = totals(previous)
	error_rate = _rate(errors, runs)
	previous_error_rate = _rate(previous_errors, previous_runs) if previous_runs else None
	return {
		"runs": runs,
		"errors": errors,
		"error_rate": error_rate,
		"previous_errors": previous_errors,
		"previous_error_rate": previous_error_rate,
		"delta_pt": flt(error_rate - previous_error_rate, 1) if previous_runs else None,
		"suspended": current["suspended"],
		"retried": retried,
		"retry_recovered": recovered,
		"retry_recovery_rate": _rate(recovered, retried),
		"previous_retry_recovery_rate": _rate(previous_recovered, previous_retried)
		if previous_runs
		else None,
		"affected_elements": len({(key[1], key[2]) for key in current["errors"]}),
		"elements_with_runs": len({(key[0], key[1]) for key in current["elements"]}),
	}


def _error_codes(current: dict, from_d, origin: str) -> list:
	"""Each error code in the range with its count and whether it first appeared in the range."""
	counts = defaultdict(int)
	for key, errors in current["errors"].items():
		counts[key[0]] += errors
	if not counts:
		return []
	Run = DocType("AI Agent Run")
	first_seen = {
		r.error_code: r.first_seen
		for r in frappe.qb.from_(Run)
		.select(Run.error_code, fn.Min(Run.started_at).as_("first_seen"))
		.where(Run.status == "Error")
		.where(_origin_condition(Run, origin))
		.groupby(Run.error_code)
		.run(as_dict=True)
	}
	codes = [
		{"error_code": cstr(code), "count": count, "is_new": _seen_since(first_seen.get(code), from_d)}
		for code, count in counts.items()
	]
	return sorted(codes, key=lambda c: c["count"], reverse=True)


def _seen_since(first_seen, from_d) -> bool:
	return bool(first_seen) and getdate(first_seen) >= from_d


def _error_issues(current, previous, from_d, to_d, origin, filters, group_by, error_code) -> list:
	"""One row per (error_code, bpmn_id, process_model, series) with its counts, history and P95."""
	keys = [k for k in current["errors"] if not error_code or k[0] == error_code]
	if not keys:
		return []
	history = _issue_history(keys, from_d, to_d, origin, filters, group_by)
	issues = []
	for key in keys:
		element_key = key[1:]
		element = current["elements"].get(element_key) or frappe._dict()
		previous_element = previous["elements"].get(element_key) or frappe._dict()
		runs = cint(element.runs)
		previous_runs = cint(previous_element.runs)
		error_rate = _rate(current["errors"][key], runs)
		previous_error_rate = _rate(previous["errors"].get(key, 0), previous_runs) if previous_runs else None
		seen = history["seen"].get(key) or frappe._dict()
		issues.append(
			{
				"key": _issue_key(*key),
				"error_code": cstr(key[0]),
				"bpmn_id": cstr(key[1]),
				"bpmn_label": cstr(element.bpmn_label) or cstr(key[1]),
				"process_model": cstr(key[2]),
				"series": cstr(key[3]) or ("Unattributed" if group_by == "agent" else ""),
				"errors": current["errors"][key],
				"runs": runs,
				"error_rate": error_rate,
				"first_seen": cstr(seen.first_seen),
				"last_seen": cstr(seen.last_seen),
				"last_message": history["messages"].get(key, ""),
				"is_new": _seen_since(seen.first_seen, from_d),
				"retried": cint(element.retried),
				"retry_recovered": cint(element.recovered),
				"p95_duration_ms": _p95(history["durations"].get(element_key, [])),
				"previous_error_rate": previous_error_rate,
				"delta_pt": flt(error_rate - previous_error_rate, 1) if previous_runs else None,
			}
		)
	return sorted(issues, key=lambda i: i["errors"], reverse=True)


def _issue_history(keys, from_d, to_d, origin, filters, group_by) -> dict:
	"""All-time first and last seen, the latest message in range, and counted-run durations per element."""
	Run = DocType("AI Agent Run")
	series = _series_field(Run, group_by)
	bpmn_ids = list({k[1] for k in keys if k[1]})
	element_filter = Run.bpmn_id.isin(bpmn_ids) if bpmn_ids else Run.bpmn_id.isnull()
	seen_rows = (
		frappe.qb.from_(Run)
		.select(
			Run.error_code,
			Run.bpmn_id,
			Run.process_model,
			series.as_("series"),
			fn.Min(Run.started_at).as_("first_seen"),
			fn.Max(Run.started_at).as_("last_seen"),
		)
		.where(Run.status == "Error")
		.where(_origin_condition(Run, origin))
		.where(element_filter)
		.groupby(Run.error_code, Run.bpmn_id, Run.process_model, series)
		.run(as_dict=True)
	)
	message_rows = (
		_scoped(frappe.qb.from_(Run), Run, from_d, to_d, origin, filters)
		.select(Run.error_code, Run.bpmn_id, Run.process_model, series.as_("series"), Run.error_message)
		.where(Run.status == "Error")
		.where(element_filter)
		.orderby(Run.started_at, order=frappe.qb.desc)
		.run(as_dict=True)
	)
	duration_rows = (
		_scoped(frappe.qb.from_(Run), Run, from_d, to_d, origin, filters)
		.select(Run.bpmn_id, Run.process_model, series.as_("series"), Run.duration_ms)
		.where(Run.status.notin(COUNTED_EXCLUDED_STATUSES))
		.where(element_filter)
		.run(as_dict=True)
	)
	messages = {}
	for r in message_rows:
		messages.setdefault(
			(r.error_code, r.bpmn_id, r.process_model, r.series), cstr(r.error_message)[:MESSAGE_CHARS]
		)
	durations = defaultdict(list)
	for r in duration_rows:
		durations[(r.bpmn_id, r.process_model, r.series)].append(cint(r.duration_ms))
	return {
		"seen": {(r.error_code, r.bpmn_id, r.process_model, r.series): r for r in seen_rows},
		"messages": messages,
		"durations": durations,
	}


def _p95(values: list) -> int:
	"""Nearest-rank 95th percentile; MariaDB has no percentile function."""
	if not values:
		return 0
	ordered = sorted(values)
	return ordered[max(math.ceil(0.95 * len(ordered)) - 1, 0)]


def _error_timeseries(from_d, to_d, origin: str, filters: dict, grain: str) -> dict:
	"""Error rate, counted runs and errors per code for every bucket in the range; empty buckets are 0."""
	Run = DocType("AI Agent Run")
	day = fn.Date(Run.started_at)
	rows = (
		_scoped(frappe.qb.from_(Run), Run, from_d, to_d, origin, filters)
		.select(day.as_("day"), Run.status, Run.error_code, fn.Count("*").as_("n"))
		.where(Run.status.notin(COUNTED_EXCLUDED_STATUSES))
		.groupby(day, Run.status, Run.error_code)
		.run(as_dict=True)
	)
	labels = _bucket_labels(from_d, to_d, grain)
	runs = defaultdict(int)
	errors = defaultdict(int)
	by_code = defaultdict(lambda: defaultdict(int))
	for r in rows:
		bucket = cstr(_bucket_start(r.day, grain))
		runs[bucket] += cint(r.n)
		if r.status == "Error":
			errors[bucket] += cint(r.n)
			by_code[cstr(r.error_code)][bucket] += cint(r.n)
	ordered_codes = sorted(by_code, key=lambda code: sum(by_code[code].values()), reverse=True)
	return {
		"labels": labels,
		"error_rate": [_rate(errors[label], runs[label]) for label in labels],
		"runs": [runs[label] for label in labels],
		"by_code": [
			{"error_code": code, "values": [by_code[code][label] for label in labels]}
			for code in ordered_codes
		],
	}


def _legacy_error_report(from_d, to_d, origin, group_by, model, error_code, process_model, agent_configuration):
	"""The rows, error_breakdown and summary keys the current ErrorReport.vue reads; removed in story 4.5."""
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

	return rows, error_breakdown, {
		"total_errors": total_errors,
		"most_common_error": most_common,
		"worst_element": worst_element,
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

_RUN_FIELDS = [
	"name", "status", "model", "agent_configuration", "bpmn_id", "bpmn_label",
	"instance", "parent_run", "started_at", "duration_ms", "total_prompt_tokens",
	"total_completion_tokens", "total_tokens", "estimated_cost", "error_code",
	"error_message", "prompt_hash",
]
_STEP_FIELDS = [
	"name", "step_index", "role", "step_kind", "content", "latency_ms", "started_at", "ended_at",
	"prompt_tokens", "completion_tokens", "cache_read_tokens", "cache_write_tokens", "cost",
	"error_code", "error_message",
]
_TREE_MAX_DEPTH = 4


def _step_rows(run_name: str) -> list:
	"""The steps of one run, oldest first, each carrying its AI Agent Tool Call
	child rows, the names of the tools it called, and its sub-call tag when
	the step is a model call made from inside a tool (WI-002190).

	The step doctype has no tool_name column of its own: the child table is
	the only record of what a turn called. The Insights step table read a
	field that did not exist, which is why its Tool column never showed one.
	"""
	from one_bpmn.agents.observability import parse_sub_call

	steps = frappe.get_list(
		"AI Agent Step",
		filters={"run": run_name},
		fields=_STEP_FIELDS,
		order_by="step_index asc, creation asc",
		limit_page_length=200,
	)

	step_names = [s.name for s in steps]
	calls_by_step: dict = {}
	if step_names and frappe.db.exists("DocType", "AI Agent Tool Call"):
		for call in frappe.get_all(
			"AI Agent Tool Call",
			filters={"parent": ["in", step_names], "parenttype": "AI Agent Step"},
			fields=[
				"parent", "tool_name", "tool_source", "tool_args", "tool_result", "status",
				"outcome", "tool_artifact", "artifact_file",
			],
			order_by="idx asc",
		):
			calls_by_step.setdefault(call.pop("parent"), []).append(call)

	for step in steps:
		step["tool_calls"] = calls_by_step.get(step.name, [])
		step["tool_names"] = [c.get("tool_name") for c in step["tool_calls"] if c.get("tool_name")]
		step["sub_call"] = parse_sub_call(step.get("content"))
		step["child_runs"] = []
	return steps


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
	return _step_rows(run_name)


def _own_rollup(run: dict) -> dict:
	return {
		"runs": 1,
		"total_tokens": cint(run.get("total_tokens")),
		"total_prompt_tokens": cint(run.get("total_prompt_tokens")),
		"total_completion_tokens": cint(run.get("total_completion_tokens")),
		"estimated_cost": flt(run.get("estimated_cost")),
	}


def _add_rollup(into: dict, other: dict) -> None:
	for key in ("runs", "total_tokens", "total_prompt_tokens", "total_completion_tokens"):
		into[key] = cint(into.get(key)) + cint(other.get(key))
	into["estimated_cost"] = flt(into.get("estimated_cost")) + flt(other.get("estimated_cost"))


def _run_node(run: dict, depth: int) -> dict:
	"""One run with its steps and the runs its tools started, nested under
	the step whose tool call started them.

	A child is attached to the first step still holding an unmatched call to
	the tool that started it, in order. A child that matches no step (older
	data, or a run started outside a tool call) is listed after the steps.
	"""
	steps = _step_rows(run["name"]) if depth > 0 else []
	children = _child_runs(run["name"]) if depth > 0 else []
	# The runs below arrive without their steps. A reader opens one at a time,
	# and get_turn_steps answers for that one; only its totals travel now.
	child_nodes = [_stub_node(child, depth - 1) for child in children]

	rollup = _own_rollup(run)
	for node in child_nodes:
		_add_rollup(rollup, node["rollup"])

	called_as = _tool_names_of_children(run["name"], children)
	unplaced = list(child_nodes)
	for step in steps:
		for tool_name in step["tool_names"]:
			match = next(
				(n for n in unplaced if called_as.get(n["run"]["name"]) == tool_name), None
			)
			if match is not None:
				step["child_runs"].append(match)
				unplaced.remove(match)

	return {
		"run": run,
		"steps": steps,
		"steps_loaded": True,
		"unplaced_children": unplaced,
		"rollup": rollup,
	}


def _child_runs(parent: str) -> list:
	return frappe.get_list(
		"AI Agent Run",
		filters={"parent_run": parent},
		fields=_RUN_FIELDS,
		order_by="started_at asc, creation asc",
		limit_page_length=100,
	)


def _stub_node(run: dict, depth: int) -> dict:
	"""A run below the one being read: its row and what its tree cost, no steps."""
	rollup = _own_rollup(run)
	if depth > 0:
		for child in _child_runs(run["name"]):
			_add_rollup(rollup, _stub_node(child, depth - 1)["rollup"])
	return {"run": run, "steps": [], "steps_loaded": False, "unplaced_children": [], "rollup": rollup}


def _tool_names_of_children(parent: str, children: list) -> dict:
	"""The tool name each child run answers to, as the caller called it.

	A child run started in the same process carries the calling shape as its
	own bpmn_id, so it speaks for itself. A child reached over A2A does not:
	it carries the start shape of its own map, and the name the caller used
	lives on the A2A Task instead. Without that, delegated work never lands
	under the step that asked for it.
	"""
	names = {child["name"]: child.get("bpmn_id") for child in children}
	if not names:
		return names
	try:
		tasks = frappe.get_list(
			"A2A Task",
			filters={"caller_agent_run": parent},
			fields=["bpmn_id", "agent_run", "instance"],
			limit_page_length=0,
		)
	except frappe.PermissionError:
		return names
	by_instance = {}
	for child in children:
		by_instance.setdefault(child.get("instance"), []).append(child["name"])
	for task in tasks:
		if not task.get("bpmn_id"):
			continue
		child = task.get("agent_run")
		if not child:
			# Some tasks never had their agent_run written back, so the child
			# has to come from the instance the task does name, and only when
			# that instance produced exactly one of this run's children.
			candidates = by_instance.get(task.get("instance")) or []
			child = candidates[0] if len(candidates) == 1 else None
		if child in names:
			names[child] = task["bpmn_id"]
	return names


@frappe.whitelist()
def get_run_tree(run_name: str) -> dict:
	"""A run as the tree it really was (WI-002190): its steps, and under each
	step the runs that step's tool calls started, recursively, with tokens and
	cost rolled up over the whole tree. The parent's own totals cover only its
	own model calls; the rollup is what the turn cost.
	"""
	frappe.only_for("System Manager")
	run = frappe.db.get_value("AI Agent Run", run_name, _RUN_FIELDS, as_dict=True)
	if not run:
		frappe.throw(_("AI Agent Run {0} not found").format(run_name), frappe.DoesNotExistError)
	return _run_node(run, _TREE_MAX_DEPTH)


def _descendant_rollups(run_names: list) -> dict:
	"""{top-level run name: rollup over its descendants}, walking parent_run
	links breadth-first so grandchildren count as well as children."""
	totals = {name: {"runs": 0, "total_tokens": 0, "total_prompt_tokens": 0, "total_completion_tokens": 0, "estimated_cost": 0.0} for name in run_names}
	owner = {name: name for name in run_names}
	frontier = list(run_names)
	for _level in range(_TREE_MAX_DEPTH):
		if not frontier:
			break
		children = frappe.get_all(
			"AI Agent Run",
			filters={"parent_run": ["in", frontier]},
			fields=["name", "parent_run", "total_tokens", "total_prompt_tokens", "total_completion_tokens", "estimated_cost"],
			limit_page_length=0,
		)
		frontier = []
		for child in children:
			top = owner.get(child.parent_run)
			if not top:
				continue
			owner[child.name] = top
			_add_rollup(totals[top], _own_rollup(child))
			frontier.append(child.name)
	return totals


@frappe.whitelist()
def get_recent_runs(
	model: str = None,
	bpmn_id: str = None,
	agent_configuration: str = None,
	status: str = "Success",
	limit: int = 10,
) -> list:
	"""The latest top-level runs matching the filters, each with the tokens,
	cost and count of the runs its tools started (WI-002190). Child runs are
	not listed on their own: they appear under their parent in get_run_tree.
	"""
	frappe.only_for("System Manager")
	filters: dict = {"parent_run": ["is", "not set"]}
	if status:
		filters["status"] = status
	if model:
		filters["model"] = model
	if bpmn_id:
		filters["bpmn_id"] = bpmn_id
	if agent_configuration:
		filters["agent_configuration"] = agent_configuration
	runs = frappe.get_list(
		"AI Agent Run",
		filters=filters,
		fields=_RUN_FIELDS,
		order_by="started_at desc",
		limit_page_length=min(cint(limit) or 10, 100),
	)
	rollups = _descendant_rollups([r.name for r in runs])
	for run in runs:
		below = rollups.get(run.name) or {}
		run["child_runs"] = cint(below.get("runs"))
		run["tree_total_tokens"] = cint(run.total_tokens) + cint(below.get("total_tokens"))
		run["tree_estimated_cost"] = flt(run.estimated_cost) + flt(below.get("estimated_cost"))
	return runs


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


# ---------------------------------------------------------------------------
# 7. Work item delegation cost
# ---------------------------------------------------------------------------
#
# A Work Item can be worked by an Orchestrator that delegates part of the
# job to specialists over A2A: the caller's BPMN Process Instance parks on
# an A2A Task, whose `instance` is the specialist's own process instance.
# A specialist can itself delegate further, so the chain must be walked, not
# just read one level deep — the same shape get_run_tree walks for a single
# run's tool-started children, just following A2A Task rows instead of
# parent_run.

def _instances_for_work_item(work_item_name: str) -> list:
	"""BPMN Process Instance names whose context is the given Work Item."""
	return frappe.get_all(
		"BPMN Process Instance",
		filters={"context_doctype": "Work Item", "context_docname": work_item_name},
		pluck="name",
	)


def _delegated_instances(caller_instances: list) -> list:
	"""The specialist instances these instances handed work to over A2A."""
	if not caller_instances:
		return []
	return [
		t.instance
		for t in frappe.get_all(
			"A2A Task",
			filters={"caller_instance": ["in", caller_instances], "instance": ["is", "set"]},
			fields=["instance"],
			limit_page_length=0,
		)
		if t.instance
	]


def _delegation_chain_instances(root_instances: list) -> tuple[list, bool]:
	"""Every instance in the delegation chain starting from *root_instances*,
	following A2A Task rows from caller_instance (the instance that parked,
	waiting) to instance (the specialist instance doing the delegated work),
	repeatedly — so a specialist that itself delegates further is caught too.

	Depth is capped at _TREE_MAX_DEPTH, the same guard get_run_tree uses for
	its own recursion, so a bad or cyclic chain cannot loop forever.

	Returns the instances found and whether the cap stopped the walk with more
	chain still ahead. That second value matters here in a way it does not for
	get_run_tree: this walk feeds a cost total, and a total short by a level is
	an undercount that looks exactly like a correct answer.
	"""
	all_instances = list(dict.fromkeys(root_instances))
	frontier = list(root_instances)
	for _level in range(_TREE_MAX_DEPTH):
		if not frontier:
			break
		next_frontier = []
		for instance in _delegated_instances(frontier):
			if instance not in all_instances:
				all_instances.append(instance)
				next_frontier.append(instance)
		frontier = next_frontier
	# A leftover frontier only says those instances went unexpanded, not that
	# any chain continues past them — asking is what stops a complete total
	# from being flagged as short.
	truncated = any(i not in all_instances for i in _delegated_instances(frontier))
	return all_instances, truncated


@frappe.whitelist()
def get_work_item_delegation_cost(work_item_name: str) -> dict:
	"""Total AI cost for a Work Item, summed across every AI Agent Run in its
	delegation chain — every Orchestrator pass plus every specialist it handed
	work to over A2A, down to _TREE_MAX_DEPTH levels.

	Returns zero totals and an empty breakdown, not an error, for a work item
	with no BPMN Process Instance or no runs at all.

	chain_truncated says the depth cap was reached with chain still unwalked,
	so the totals are a floor rather than the whole figure. Read it before
	quoting the number: nothing else distinguishes a complete total from a
	short one.
	"""
	frappe.only_for("System Manager")

	root_instances = _instances_for_work_item(work_item_name)
	if not root_instances:
		return {"total_cost": 0.0, "total_tokens": 0, "breakdown": [], "chain_truncated": False}

	instances, chain_truncated = _delegation_chain_instances(root_instances)

	Run = DocType("AI Agent Run")
	rows = (
		frappe.qb.from_(Run)
		.select(
			Run.name,
			Run.agent_configuration,
			Run.model,
			Run.estimated_cost,
			Run.total_tokens,
		)
		.where(Run.instance.isin(instances))
		.orderby(Run.started_at)
		.run(as_dict=True)
	)

	breakdown = []
	total_cost = 0.0
	total_tokens = 0
	for r in rows:
		cost = flt(r.get("estimated_cost"), 6)
		tokens = cint(r.get("total_tokens"))
		total_cost += cost
		total_tokens += tokens
		breakdown.append({
			"run": r.get("name"),
			"agent_configuration": r.get("agent_configuration"),
			"model": r.get("model"),
			"cost": cost,
			"tokens": tokens,
		})

	return {
		"total_cost": flt(total_cost, 6),
		"total_tokens": total_tokens,
		"breakdown": breakdown,
		"chain_truncated": chain_truncated,
	}


# ---------------------------------------------------------------------------
# 8. Runs page: list, filter options, one run in full
# ---------------------------------------------------------------------------

RUNS_PAGE_MAX = 100

_LIST_RUN_FIELDS = (
	"name", "status", "model", "agent_configuration", "bpmn_id", "bpmn_label", "instance",
	"origin", "started_at", "ended_at", "duration_ms", "agent_latency_ms", "human_wait_ms",
	"total_prompt_tokens", "total_completion_tokens", "total_tokens", "total_cache_read_tokens",
	"estimated_cost", "error_code", "goal_completion",
)

_DETAIL_RUN_FIELDS = _LIST_RUN_FIELDS + (
	"process_model", "parent_run", "prompt_hash", "element_type", "eval_case", "eval_run",
	"backend", "provider", "error_message", "retry_count", "max_retries", "suspended_at",
	"total_cache_write_tokens", "total_input_cost", "total_output_cost", "total_cache_read_cost",
	"total_cache_write_cost", "completion_basis", "final_output", "no_terminal_tool",
	"correlation_id", "recall_query", "memory_injected_tokens", "pending_human_task",
)

_RUN_ORDERS = {
	"newest": ("started_at", "desc"),
	"oldest": ("started_at", "asc"),
	"slowest": ("agent_latency_ms", "desc"),
	"cost": ("estimated_cost", "desc"),
	"tokens": ("total_tokens", "desc"),
}


def _percentile(values: list, share: float) -> int:
	if not values:
		return 0
	values = sorted(values)
	return cint(values[min(len(values) - 1, int(len(values) * share))])


def _runs_conditions(Run, Inst, Step, *, agent_configuration=None, status=None, origin="production",
                     user=None, model=None, instance=None, from_date=None, to_date=None,
                     errors_only=0, search=None) -> list:
	"""The where clauses the list, the tiles and the filter options share.
	Top-level runs only: a run a tool started shows under its parent."""
	conditions = [Run.parent_run.isnull() | (Run.parent_run == ""), _origin_condition(Run, origin)]
	if agent_configuration:
		conditions.append(Run.agent_configuration == agent_configuration)
	if status:
		conditions.append(Run.status == status)
	if user:
		conditions.append(Inst.initiated_by == user)
	if model:
		conditions.append(Run.model == model)
	if instance:
		conditions.append(Run.instance == instance)
	if from_date:
		conditions.append(fn.Date(Run.started_at) >= getdate(from_date))
	if to_date:
		conditions.append(fn.Date(Run.started_at) <= getdate(to_date))
	if cint(errors_only):
		failed_steps = frappe.qb.from_(Step).select(Step.run).where(Step.error_code.isnotnull()).distinct()
		conditions.append((Run.status == "Error") | Run.name.isin(failed_steps))
	if search:
		term = f"%{search.strip()}%"
		conditions.append(
			Run.name.like(term) | Run.instance.like(term) | Run.bpmn_label.like(term)
			| Run.final_output.like(term) | Inst.initiated_by.like(term)
		)
	return conditions


def _apply(query, conditions):
	for condition in conditions:
		query = query.where(condition)
	return query


@frappe.whitelist()
def list_runs(
	agent_configuration: str = None,
	status: str = None,
	origin: str = "production",
	user: str = None,
	model: str = None,
	instance: str = None,
	from_date: str = None,
	to_date: str = None,
	errors_only: int = 0,
	search: str = None,
	order: str = "newest",
	start: int = 0,
	page_length: int = 25,
) -> dict:
	"""A page of top-level runs for /processa/runs, with the six tile numbers
	for the same filter. Each run carries its step count, tool-call count,
	failed-step count, the person who started its instance, and the tokens
	and cost of the whole tree its tools started."""
	frappe.only_for("System Manager")
	page_length = min(max(cint(page_length) or 25, 1), RUNS_PAGE_MAX)
	start = max(cint(start), 0)

	Run = DocType("AI Agent Run")
	Inst = DocType("BPMN Process Instance")
	Step = DocType("AI Agent Step")
	Call = DocType("AI Agent Tool Call")
	conditions = _runs_conditions(
		Run, Inst, Step, agent_configuration=agent_configuration, status=status, origin=origin,
		user=user, model=model, instance=instance, from_date=from_date, to_date=to_date,
		errors_only=errors_only, search=search,
	)

	steps_of = frappe.qb.from_(Step).select(fn.Count("*")).where(Step.run == Run.name)
	failed_of = (
		frappe.qb.from_(Step).select(fn.Count("*"))
		.where(Step.run == Run.name).where(Step.error_code.isnotnull())
	)
	calls_of = (
		frappe.qb.from_(Call).join(Step).on(Call.parent == Step.name)
		.select(fn.Count("*")).where(Step.run == Run.name)
	)
	from pypika import Order

	query = (
		frappe.qb.from_(Run).left_join(Inst).on(Run.instance == Inst.name)
		.select(
			*[Run[f] for f in _LIST_RUN_FIELDS],
			Inst.initiated_by.as_("user"),
			Inst.context_doctype, Inst.context_docname,
			steps_of.as_("steps"), failed_of.as_("failed_steps"), calls_of.as_("tool_calls"),
		)
	)
	if order == "steps":
		query = query.orderby(steps_of, order=Order.desc)
	else:
		order_field, direction = _RUN_ORDERS.get(order or "newest", _RUN_ORDERS["newest"])
		query = query.orderby(Run[order_field], order=Order.desc if direction == "desc" else Order.asc)
	query = query.orderby(Run.creation, order=Order.desc).limit(page_length).offset(start)
	runs = _apply(query, conditions).run(as_dict=True)

	rollups = _descendant_rollups([r.name for r in runs])
	for run in runs:
		below = rollups.get(run.name) or {}
		run["child_runs"] = cint(below.get("runs"))
		run["tree_total_tokens"] = cint(run.total_tokens) + cint(below.get("total_tokens"))
		run["tree_estimated_cost"] = flt(run.estimated_cost) + flt(below.get("estimated_cost"))
		run["conversation"] = (
			run.context_docname if run.context_doctype == "Chat Conversation" else None
		)

	base = _apply(frappe.qb.from_(Run).left_join(Inst).on(Run.instance == Inst.name), conditions)
	failed_runs = frappe.qb.from_(Step).select(Step.run).where(Step.error_code.isnotnull()).distinct()
	totals = base.select(
		fn.Count("*").as_("runs"),
		fn.Count(Run.instance).distinct().as_("instances"),
		fn.Sum(Run.estimated_cost).as_("cost"),
		fn.Sum(Run.total_tokens).as_("tokens"),
		fn.Sum(Run.total_cache_read_tokens).as_("cache_read_tokens"),
		fn.Sum(Case().when((Run.status == "Error") | Run.name.isin(failed_runs), 1).else_(0)).as_("error_runs"),
	).run(as_dict=True)[0]
	step_total = cint(
		frappe.qb.from_(Step).select(fn.Count("*"))
		.where(Step.run.isin(base.select(Run.name))).run()[0][0]
	)
	latencies = [
		cint(r[0]) for r in base.select(Run.agent_latency_ms).where(Run.agent_latency_ms > 0).run()
	]
	run_count = cint(totals.get("runs"))
	summary = {
		"runs": run_count,
		"conversations": cint(totals.get("instances")),
		"steps": step_total,
		"steps_per_run": round(step_total / run_count, 1) if run_count else 0,
		"median_latency_ms": _percentile(latencies, 0.5),
		"p95_latency_ms": _percentile(latencies, 0.95),
		"error_runs": cint(totals.get("error_runs")),
		"error_rate": round(cint(totals.get("error_runs")) * 100 / run_count, 1) if run_count else 0,
		"cost": flt(totals.get("cost")),
		"cost_per_run": flt(totals.get("cost")) / run_count if run_count else 0,
		"tokens": cint(totals.get("tokens")),
		"cache_read_share": (
			round(cint(totals.get("cache_read_tokens")) * 100 / cint(totals.get("tokens")), 1)
			if cint(totals.get("tokens")) else 0
		),
	}
	return {"runs": runs, "total": run_count, "start": start, "page_length": page_length, "summary": summary}


@frappe.whitelist()
def run_filter_options(origin: str = "production") -> dict:
	"""The agents, people and models that actually have runs, for the filters."""
	frappe.only_for("System Manager")
	Run = DocType("AI Agent Run")
	Inst = DocType("BPMN Process Instance")
	base = (
		frappe.qb.from_(Run).left_join(Inst).on(Run.instance == Inst.name)
		.where(Run.parent_run.isnull() | (Run.parent_run == ""))
		.where(_origin_condition(Run, origin))
	)
	def distinct(column):
		rows = base.select(column).distinct().run()
		return sorted({cstr(r[0]) for r in rows if r[0]})
	return {
		"agents": distinct(Run.agent_configuration),
		"users": distinct(Inst.initiated_by),
		"models": distinct(Run.model),
		"statuses": ["Running", "Suspended", "Success", "Error"],
	}


@frappe.whitelist()
def get_turn_steps(run_name: str) -> dict:
	"""One turn's steps, with the runs its tools started, for opening a turn
	inside a conversation without loading the conversation again."""
	frappe.only_for("System Manager")
	run = frappe.db.get_value("AI Agent Run", run_name, list(_DETAIL_RUN_FIELDS), as_dict=True)
	if not run:
		frappe.throw(_("AI Agent Run {0} not found").format(run_name), frappe.DoesNotExistError)
	return {**_run_node(dict(run), _TREE_MAX_DEPTH), "run": run}


@frappe.whitelist()
def get_run_detail(run_name: str) -> dict:
	"""One run in full: its record, the instance and conversation it belongs
	to, its steps as a tree (child runs under the step that started them),
	and the other top-level runs on the same instance in the order they
	happened, which is the conversation read turn by turn."""
	frappe.only_for("System Manager")
	run = frappe.db.get_value("AI Agent Run", run_name, list(_DETAIL_RUN_FIELDS), as_dict=True)
	if not run:
		frappe.throw(_("AI Agent Run {0} not found").format(run_name), frappe.DoesNotExistError)

	instance = None
	if run.instance:
		instance = frappe.db.get_value(
			"BPMN Process Instance", run.instance,
			["name", "process_model", "status", "initiated_by", "started_at", "completed_at",
			 "context_doctype", "context_docname"],
			as_dict=True,
		)
	conversation = None
	if instance and instance.context_doctype == "Chat Conversation" and instance.context_docname:
		conversation = frappe.db.get_value(
			"Chat Conversation", instance.context_docname, ["name", "title", "agent_mode", "status"], as_dict=True
		)

	tree = _run_node(dict(run), _TREE_MAX_DEPTH)
	system_prompt = next((s.get("content") for s in tree["steps"] if s.get("role") == "system"), "")

	siblings = []
	if run.instance:
		# A run started by another run's tool call is not a turn of the
		# conversation; its page reads that one run, and points at the caller.
		siblings = frappe.get_list(
			"AI Agent Run",
			filters={"name": run.name} if run.parent_run else {"instance": run.instance, "parent_run": ["is", "not set"]},
			fields=["name", "bpmn_label", "agent_configuration", "status", "started_at", "ended_at",
			        "agent_latency_ms", "duration_ms", "total_tokens", "estimated_cost", "final_output",
			        "error_code"],
			order_by="started_at asc, creation asc",
			limit_page_length=200,
		)
		for sibling in siblings:
			sibling["final_output"] = cstr(sibling.get("final_output"))[:600]

	agent_model = None
	if run.agent_configuration:
		agent_model = frappe.db.get_value("AI Agent Configuration", run.agent_configuration, "ai_model")

	return {
		"run": run,
		"agent_model": agent_model,
		"instance": instance,
		"conversation": conversation,
		"tree": tree,
		"system_prompt": system_prompt,
		"siblings": siblings,
	}
