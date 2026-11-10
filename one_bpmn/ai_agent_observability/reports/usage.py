"""Overview tiles and the cost and token report."""
from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import cint, cstr, flt
from pypika.terms import Case

from one_bpmn.ai_agent_observability.reports.periods import (
	apply_common_filters,
	bucket_start,
	default_dates,
	grain_for,
	list_bucket_labels,
	origin_condition,
	previous_period,
)


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
		.where(origin_condition(Run, origin))
	)
	query = apply_common_filters(query, Run, model, provider, process_model, agent_configuration)
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
	input_tokens = prompt_tokens - cache_write_tokens

	return {
		"runs": runs,
		"cost": cost,
		"avg_cost": flt(cost / runs, 6) if runs else 0.0,
		"tokens": tokens,
		"input_tokens": input_tokens,
		"output_tokens": completion_tokens,
		"cached_tokens": cache_read_tokens,
		"success_rate": success_rate,
		"cache_hit_rate": cache_hit_rate,
	}


def _compute_deltas(current: dict, previous: dict) -> dict:
	"""Percentage change per key, points for the rates; null when the previous
	period has no runs or the previous value for a non-rate key is 0."""
	delta = {}
	no_previous_activity = not previous or cint(previous.get("runs")) == 0
	for key, cur_val in current.items():
		if no_previous_activity:
			delta[key] = None
			continue
		prev_val = previous.get(key)
		if key in ("success_rate", "cache_hit_rate"):
			delta[key] = flt(cur_val - flt(prev_val), 1)
			continue
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
			fn.Sum(Case().when(Run.status != "Running", 1).else_(0)).as_("decided"),
			fn.Sum(Case().when(Run.status == "Success", 1).else_(0)).as_("successes"),
			fn.Sum(Run.estimated_cost).as_("cost"),
			fn.Sum(Run.total_tokens).as_("tokens"),
			fn.Sum(Run.total_prompt_tokens).as_("prompt_tokens"),
			fn.Sum(Run.total_cache_read_tokens).as_("cache_read_tokens"),
		)
		.where(fn.Date(Run.started_at) >= from_d)
		.where(fn.Date(Run.started_at) <= to_d)
		.where(origin_condition(Run, origin))
		.groupby(fn.Date(Run.started_at))
	)
	query = apply_common_filters(query, Run, model, provider, process_model, agent_configuration)
	rows = query.run(as_dict=True)
	return [
		{
			"date": cstr(r.get("date")),
			"runs": cint(r.get("runs")),
			"decided": cint(r.get("decided")),
			"successes": cint(r.get("successes")),
			"cost": flt(r.get("cost"), 6),
			"tokens": cint(r.get("tokens")),
			"prompt_tokens": cint(r.get("prompt_tokens")),
			"cache_read_tokens": cint(r.get("cache_read_tokens")),
		}
		for r in rows
	]


def _bucketed_series(from_d, to_d, daily_rows: list, grain: str) -> dict:
	"""Bucket daily rows into day/week/month buckets; empty buckets are 0."""
	labels = list_bucket_labels(from_d, to_d, grain)
	sums = defaultdict(lambda: defaultdict(float))
	for row in daily_rows:
		bucket = sums[cstr(bucket_start(row["date"], grain))]
		for key in ("runs", "decided", "successes", "cost", "tokens", "prompt_tokens", "cache_read_tokens"):
			bucket[key] += row[key]
	buckets = [sums[label] for label in labels]
	return {
		"labels": labels,
		"cost": [flt(b["cost"], 6) for b in buckets],
		"tokens": [cint(b["tokens"]) for b in buckets],
		"runs": [cint(b["runs"]) for b in buckets],
		"avg_cost": [flt(b["cost"] / b["runs"], 6) if b["runs"] else 0.0 for b in buckets],
		"success_rate": [
			flt(b["successes"] / b["decided"] * 100, 1) if b["decided"] else 0.0 for b in buckets
		],
		"cache_hit_rate": [
			flt(b["cache_read_tokens"] / b["prompt_tokens"] * 100, 1) if b["prompt_tokens"] else 0.0
			for b in buckets
		],
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
		.where(origin_condition(Run, origin))
		.groupby(*group_fields)
	)
	query = apply_common_filters(query, Run, model, provider, process_model, agent_configuration)
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
		runs = cint(r.get("runs"))
		cost = flt(r.get("cost"), 6)
		series.append({
			"name": name,
			"provider": row_provider or None,
			"runs": runs,
			"cost": cost,
			"avg_cost": flt(cost / runs, 6) if runs else 0.0,
			"tokens": cint(r.get("tokens")),
			"input_tokens": prompt_tokens - cache_write_tokens,
			"output_tokens": cint(r.get("completion_tokens")),
			"cached_tokens": cache_read_tokens,
			"cache_hit_rate": flt(cache_read_tokens / prompt_tokens * 100, 1) if prompt_tokens else 0.0,
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
			.where(origin_condition(Run, origin))
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
	"""Return the overview tiles for the from_date/to_date range and filters, with the previous period."""
	if days is not None:
		frappe.throw(_("days is not supported; pass from_date and to_date instead"))

	from_d, to_d = default_dates(from_date, to_date)
	previous_from, previous_to = previous_period(from_d, to_d)
	grain = grain_for(from_d, to_d)

	current = _usage_totals(from_d, to_d, origin, model, provider, process_model, agent_configuration)
	previous = _usage_totals(previous_from, previous_to, origin, model, provider, process_model, agent_configuration)
	delta = _compute_deltas(current, previous)

	daily_rows = _daily_metric_rows(from_d, to_d, origin, model, provider, process_model, agent_configuration)
	sparklines = _bucketed_series(from_d, to_d, daily_rows, grain)

	return {
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

def _daily_cost_rows(
	from_d,
	to_d,
	origin: str,
	group_by: str,
	model: str = None,
	provider: str = None,
	process_model: str = None,
	agent_configuration: str = None,
) -> list:
	"""One row per date, series and provider with runs, tokens and costs, for the chart and the export."""
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
		.where(origin_condition(Run, origin))
		# Running runs ARE included: selector runs stay "Running" for the
		# whole life of their subprocess and their token/cost rollups are
		# refreshed after every decision; excluding them hid all selector
		# spend until (if ever) the subprocess completed. Success-rate and
		# reliability reports still exclude Running, correctly.
		.orderby(fn.Date(Run.started_at))
	)
	query = query.groupby(fn.Date(Run.started_at), group_field, Run.provider)
	query = apply_common_filters(query, Run, model, provider, process_model, agent_configuration)

	raw_rows = query.run(as_dict=True)

	# "series" is the grouped dimension's display value.
	unattributed = "Unattributed"
	rows = []
	for r in raw_rows:
		series = cstr(r.get("group_key")) or (unattributed if group_by == "agent" else "")
		rows.append({
			"date": cstr(r.get("date")),
			"series": series,
			"provider": cstr(r.get("provider")),
			"total_runs": cint(r.get("total_runs")),
			"total_tokens": cint(r.get("total_tokens")),
			"avg_tokens": cint(r.get("avg_tokens")),
			"total_cost": flt(r.get("total_cost"), 6),
			"avg_cost": flt(r.get("avg_cost"), 6),
			"input_cost": flt(r.get("input_cost"), 6),
			"output_cost": flt(r.get("output_cost"), 6),
		})
	return rows


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
	"""Cost and tokens by model, or by the run's AI Agent Configuration when ``group_by="agent"``,
	as chart buckets, series rows and totals against the previous period.
	Runs recorded before agent attribution existed appear as "Unattributed"."""
	group_by = group_by if group_by in ("model", "agent") else "model"
	from_d, to_d = default_dates(from_date, to_date)
	previous_from, previous_to = previous_period(from_d, to_d)
	grain = grain_for(from_d, to_d)

	rows = _daily_cost_rows(from_d, to_d, origin, group_by, model, provider, process_model, agent_configuration)

	# Pivot chart_data by the grouped dimension per day, week or month bucket.
	bucket_labels = list_bucket_labels(from_d, to_d, grain)

	series_bucket_cost = defaultdict(lambda: defaultdict(float))
	series_bucket_tokens = defaultdict(lambda: defaultdict(int))
	series_seen = set()
	for r in rows:
		bucket = cstr(bucket_start(r["date"], grain))
		series_bucket_cost[r["series"]][bucket] += r["total_cost"]
		series_bucket_tokens[r["series"]][bucket] += r["total_tokens"]
		series_seen.add(r["series"])

	datasets = []
	for m in sorted(series_seen):
		datasets.append({
			"label": m,
			"values": [flt(series_bucket_cost[m].get(b, 0), 6) for b in bucket_labels],
			"tokens": [cint(series_bucket_tokens[m].get(b, 0)) for b in bucket_labels],
		})

	current = _usage_totals(from_d, to_d, origin, model, provider, process_model, agent_configuration)
	previous = _usage_totals(previous_from, previous_to, origin, model, provider, process_model, agent_configuration)
	delta = _compute_deltas(current, previous)
	series = _series_rows(from_d, to_d, origin, group_by, model, provider, process_model, agent_configuration)
	previous_cost = {
		(r["name"], r["provider"]): r["cost"]
		for r in _series_rows(
			previous_from, previous_to, origin, group_by, model, provider, process_model, agent_configuration
		)
	}
	for r in series:
		r["share"] = flt(r["cost"] / current["cost"] * 100, 1) if current["cost"] else 0.0
		r["previous_cost"] = previous_cost.get((r["name"], r["provider"]), 0.0)
		r["delta"] = (
			flt((r["cost"] - r["previous_cost"]) / r["previous_cost"] * 100, 1)
			if r["previous_cost"]
			else None
		)
	filter_options = _filter_options(from_d, to_d, origin)

	return {
		"chart_data": {
			"labels": bucket_labels,
			"datasets": datasets,
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
			"cache_hit_rate": current["cache_hit_rate"],
			"avg_cost": current["avg_cost"],
		},
		"series": series,
		"filter_options": filter_options,
	}


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
	if fmt not in ("csv", "xlsx"):
		frappe.throw(_("fmt must be 'csv' or 'xlsx'"))

	group_by = group_by if group_by in ("model", "agent") else "model"
	from_d, to_d = default_dates(from_date, to_date)
	rows = _daily_cost_rows(from_d, to_d, origin, group_by, model, provider, process_model, agent_configuration)

	header = [
		_("Date"), _("Series"), _("Provider"), _("Runs"), _("Total Tokens"),
		_("Avg Tokens"), _("Total Cost"), _("Avg Cost"), _("Input Cost"), _("Output Cost"),
	]
	data = [header]
	for r in rows:
		data.append([
			r["date"], r["series"], r["provider"], r["total_runs"], r["total_tokens"],
			r["avg_tokens"], r["total_cost"], r["avg_cost"], r["input_cost"], r["output_cost"],
		])

	stem = f"usage-{group_by}-{from_d}-to-{to_d}"
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
