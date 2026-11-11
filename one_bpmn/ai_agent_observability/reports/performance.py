"""Latency report: agent time percentiles over time, one row per element, prior-period change, time split."""
from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import add_days, cint, cstr, flt, getdate
from frappe.utils.csvutils import to_csv

from one_bpmn.ai_agent_observability.observability import classify_step
from one_bpmn.ai_agent_observability.reports.errors import (
	COUNTED_EXCLUDED_STATUSES,
	p95,
	scoped,
	series_field,
)
from one_bpmn.ai_agent_observability.reports.periods import (
	bucket_start,
	default_dates,
	grain_for,
	list_bucket_labels,
	origin_condition,
	previous_period,
)
from one_bpmn.ai_agent_observability.reports.runs import percentile

SUB_CALL_CHARS = 200


def export_latency_report(
	from_date: str | None = None,
	to_date: str | None = None,
	model: str | None = None,
	process_model: str | None = None,
	agent_configuration: str | None = None,
	origin: str = "production",
	group_by: str = "model",
	provider: str | None = None,
	fmt: str = "csv",
):
	"""Download the latency report's elements, one row per element with every field, as CSV or XLSX."""
	if fmt not in ("csv", "xlsx"):
		frappe.throw(_("fmt must be 'csv' or 'xlsx'"))

	report = get_performance_report(
		from_date=from_date,
		to_date=to_date,
		model=model,
		process_model=process_model,
		agent_configuration=agent_configuration,
		origin=origin,
		group_by=group_by,
		provider=provider,
	)
	columns = [
		("key", _("Key")),
		("bpmn_id", _("Element ID")),
		("bpmn_label", _("Element")),
		("process_model", _("Process")),
		("series", _("AI Agent") if group_by == "agent" else _("Model")),
		("runs", _("Runs")),
		("measured_runs", _("Measured runs")),
		("error_runs", _("Errored runs")),
		("p50_ms", _("P50 (ms)")),
		("p95_ms", _("P95 (ms)")),
		("avg_ms", _("Avg (ms)")),
		("max_ms", _("Max (ms)")),
		("total_ms", _("Total agent time (ms)")),
		("avg_steps", _("Avg steps")),
		("human_wait_runs", _("Runs with human wait")),
		("avg_human_wait_ms", _("Avg human wait (ms)")),
		("previous_p95_ms", _("Previous P95 (ms)")),
		("delta_p95_pct", _("P95 change (%)")),
		("is_new", _("New")),
	]
	data = [[label for _field, label in columns]]
	data += [[element[field] for field, _label in columns] for element in report["elements"]]

	stem = f"latency-{group_by}-{report['from_date']}-to-{report['to_date']}"
	if fmt == "xlsx":
		from frappe.utils.xlsxutils import make_xlsx

		content = make_xlsx(data, "Latency").getvalue()
	else:
		content = to_csv(data).encode("utf-8-sig")

	frappe.response["type"] = "binary"
	frappe.response["filename"] = f"{stem}.{fmt}"
	frappe.response["filecontent"] = content


def get_performance_report(
	from_date: str | None = None,
	to_date: str | None = None,
	model: str | None = None,
	bpmn_id: str | None = None,
	process_model: str | None = None,
	agent_configuration: str | None = None,
	origin: str = "production",
	group_by: str = "model",
	provider: str | None = None,
) -> dict:
	"""Agent-time percentiles per bucket, elements sorted by total time, a summary against the prior period.
	rows and trend are the old wall-clock keys the current tab still reads; bpmn_id narrows only those."""
	group_by = group_by if group_by in ("model", "agent") else "model"
	from_d, to_d = default_dates(from_date, to_date)
	previous_from, previous_to = previous_period(from_d, to_d)
	grain = grain_for(from_d, to_d)
	filters = {
		"model": model,
		"provider": provider,
		"process_model": process_model,
		"agent_configuration": agent_configuration,
	}

	current = _counted_runs(from_d, to_d, origin, filters, group_by)
	previous = _counted_runs(previous_from, previous_to, origin, filters, group_by)
	legacy = _legacy_report(
		from_d, to_d, model, bpmn_id, process_model, agent_configuration, origin, group_by, provider
	)
	return {
		"grain": grain,
		"from_date": cstr(from_d),
		"to_date": cstr(to_d),
		"previous_from": cstr(previous_from),
		"previous_to": cstr(previous_to),
		"timeseries": _timeseries(current, from_d, to_d, grain),
		"summary": _summary(
			current,
			previous,
			_time_split(from_d, to_d, origin, filters),
			_time_split(previous_from, previous_to, origin, filters),
		),
		"elements": _elements(current, previous, _step_counts(from_d, to_d, origin, filters), group_by),
		**legacy,
	}


def _counted_runs(from_d, to_d, origin: str, filters: dict, group_by: str) -> list:
	Run = DocType("AI Agent Run")
	return (
		_counted_query(Run, from_d, to_d, origin, filters)
		.select(
			Run.name,
			Run.bpmn_id,
			Run.bpmn_label,
			Run.process_model,
			series_field(Run, group_by).as_("series"),
			Run.status,
			Run.agent_latency_ms,
			Run.human_wait_ms,
			fn.Date(Run.started_at).as_("day"),
		)
		.run(as_dict=True)
	)


def _step_counts(from_d, to_d, origin: str, filters: dict) -> dict:
	"""Steps recorded per counted run."""
	Run = DocType("AI Agent Run")
	Step = DocType("AI Agent Step")
	rows = (
		_counted_query(Run, from_d, to_d, origin, filters)
		.join(Step)
		.on(Step.run == Run.name)
		.select(Run.name, fn.Count(Step.name).as_("steps"))
		.groupby(Run.name)
		.run(as_dict=True)
	)
	return {r.name: cint(r.steps) for r in rows}


def _timeseries(runs: list, from_d, to_d, grain: str) -> dict:
	"""P50, P95 and measured runs per bucket; a bucket without measured runs reads null."""
	labels = list_bucket_labels(from_d, to_d, grain)
	measured = defaultdict(list)
	for r in runs:
		if cint(r.agent_latency_ms) > 0:
			measured[cstr(bucket_start(r.day, grain))].append(cint(r.agent_latency_ms))
	figures = [_latency_figures(measured[label]) for label in labels]
	return {
		"labels": labels,
		"p50_ms": [f["p50_ms"] for f in figures],
		"p95_ms": [f["p95_ms"] for f in figures],
		"runs": [len(measured[label]) for label in labels],
	}


def _summary(current: list, previous: list, split: dict, previous_split: dict) -> dict:
	"""Tile figures against the prior period; deltas are null when the prior period measured nothing."""
	values = [cint(r.agent_latency_ms) for r in current if cint(r.agent_latency_ms) > 0]
	previous_values = [cint(r.agent_latency_ms) for r in previous if cint(r.agent_latency_ms) > 0]
	figures = _latency_figures(values)
	previous_figures = _latency_figures(previous_values)
	time_in_tools = flt(split["tool_share"] + split["sub_call_share"], 1)
	previous_time_in_tools = (
		flt(previous_split["tool_share"] + previous_split["sub_call_share"], 1) if previous_values else None
	)
	return {
		"runs": len(current),
		"measured_runs": len(values),
		**figures,
		"total_ms": sum(values),
		"previous_p50_ms": previous_figures["p50_ms"],
		"previous_p95_ms": previous_figures["p95_ms"],
		"delta_p50_pct": _pct_change(figures["p50_ms"], previous_figures["p50_ms"]),
		"delta_p95_pct": _pct_change(figures["p95_ms"], previous_figures["p95_ms"]),
		**split,
		"time_in_tools": time_in_tools,
		"previous_time_in_tools": previous_time_in_tools,
		"delta_time_in_tools_pt": flt(time_in_tools - previous_time_in_tools, 1)
		if previous_time_in_tools is not None
		else None,
	}


def _elements(current: list, previous: list, step_counts: dict, group_by: str) -> list:
	"""One row per bpmn_id, process model and series, sorted by total agent time."""
	groups = defaultdict(list)
	for r in current:
		groups[(cstr(r.bpmn_id), cstr(r.process_model), cstr(r.series))].append(r)
	previous_values = defaultdict(list)
	for r in previous:
		if cint(r.agent_latency_ms) > 0:
			previous_values[(cstr(r.bpmn_id), cstr(r.process_model), cstr(r.series))].append(
				cint(r.agent_latency_ms)
			)

	elements = []
	for key, runs in groups.items():
		values = [cint(r.agent_latency_ms) for r in runs if cint(r.agent_latency_ms) > 0]
		waits = [cint(r.human_wait_ms) for r in runs if cint(r.human_wait_ms) > 0]
		steps = [step_counts[r.name] for r in runs if r.name in step_counts]
		figures = _latency_figures(values)
		previous_p95 = p95(previous_values[key]) if previous_values[key] else None
		elements.append(
			{
				"key": "|".join(key),
				"bpmn_id": key[0],
				"bpmn_label": next((cstr(r.bpmn_label) for r in runs if r.bpmn_label), key[0]),
				"process_model": key[1],
				"series": key[2] or (_("Unattributed") if group_by == "agent" else ""),
				"runs": len(runs),
				"measured_runs": len(values),
				"error_runs": sum(1 for r in runs if r.status == "Error"),
				**figures,
				"avg_ms": cint(sum(values) / len(values)) if values else None,
				"max_ms": max(values) if values else None,
				"total_ms": sum(values),
				"avg_steps": flt(sum(steps) / len(steps), 1) if steps else 0.0,
				"human_wait_runs": len(waits),
				"avg_human_wait_ms": cint(sum(waits) / len(waits)) if waits else 0,
				"previous_p95_ms": previous_p95,
				"delta_p95_pct": _pct_change(figures["p95_ms"], previous_p95),
				"is_new": previous_p95 is None,
			}
		)
	return sorted(elements, key=lambda e: e["total_ms"], reverse=True)


def _time_split(from_d, to_d, origin: str, filters: dict) -> dict:
	"""Share of step latency spent in model calls, tools and sub-calls over the counted runs, 1 dp."""
	Run = DocType("AI Agent Run")
	Step = DocType("AI Agent Step")
	steps = (
		_counted_query(Run, from_d, to_d, origin, filters)
		.join(Step)
		.on(Step.run == Run.name)
		.select(
			Step.role,
			Step.step_kind,
			Step.latency_ms,
			fn.Substring(Step.content, 1, SUB_CALL_CHARS).as_("content"),
		)
		.where(Step.latency_ms > 0)
		.run(as_dict=True)
	)
	totals = defaultdict(int)
	for s in steps:
		kind = s.step_kind or classify_step(s.role, s.content)
		totals[_split_part(kind, s.role)] += cint(s.latency_ms)
	totals.pop("prompt", None)
	whole = sum(totals.values())
	return {
		f"{part}_share": flt(totals[part] / whole * 100, 1) if whole else 0.0
		for part in ("model", "tool", "sub_call")
	}


def _split_part(kind: str, role: str) -> str:
	"""A tool turn counts as tool time only on the tool's own step; the assistant's call is model time."""
	if kind in ("sub_call", "prompt"):
		return kind
	if kind == "tool_turn":
		return "tool" if role == "tool" else "model"
	return "model"


def _counted_query(Run, from_d, to_d, origin: str, filters: dict):
	"""Top-level runs in range that finished, under the header filters."""
	return (
		scoped(frappe.qb.from_(Run), Run, from_d, to_d, origin, filters)
		.where(Run.status.notin(COUNTED_EXCLUDED_STATUSES))
		.where(Run.parent_run.isnull() | (Run.parent_run == ""))
	)


def _latency_figures(values: list) -> dict:
	"""P50 and P95 of measured agent latencies, None when nothing was measured."""
	return {
		"p50_ms": percentile(values, 0.5) if values else None,
		"p95_ms": p95(values) if values else None,
	}


def _pct_change(current, previous):
	if current is None or not previous:
		return None
	return flt((current - previous) / previous * 100, 0)


def _legacy_report(
	from_d, to_d, model, bpmn_id, process_model, agent_configuration, origin, group_by, provider
) -> dict:
	"""Wall-clock rows and daily trend of Success runs, the shape the current Latency tab reads."""
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
		.where(origin_condition(Run, origin))
		.orderby(Run.model, Run.bpmn_id)
	)
	if model:
		duration_query = duration_query.where(Run.model == model)
	if provider:
		duration_query = duration_query.where(Run.provider == provider)
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
		.where(origin_condition(Run, origin))
		.groupby(Step.run, group_field, Run.bpmn_id)
	)
	if model:
		step_counts_query = step_counts_query.where(Run.model == model)
	if provider:
		step_counts_query = step_counts_query.where(Run.provider == provider)
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
