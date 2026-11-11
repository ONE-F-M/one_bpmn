"""Latency report: agent time percentiles over time, one row per element, prior-period change, time split."""
from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import cint, cstr, flt
from frappe.utils.csvutils import to_csv

from one_bpmn.ai_agent_observability.observability import classify_step, parse_sub_call
from one_bpmn.ai_agent_observability.reports.errors import (
	COUNTED_EXCLUDED_STATUSES,
	ISSUE_RUNS_MAX_LIMIT,
	p95,
	scoped,
	series_field,
)
from one_bpmn.ai_agent_observability.reports.periods import (
	bucket_start,
	default_dates,
	grain_for,
	list_bucket_labels,
	previous_period,
)
from one_bpmn.ai_agent_observability.reports.runs import percentile

SUB_CALL_CHARS = 200

ELEMENT_KEY_PARTS = 3

SPLIT_PARTS = ("model", "tool", "sub_call")


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
	process_model: str | None = None,
	agent_configuration: str | None = None,
	origin: str = "production",
	group_by: str = "model",
	provider: str | None = None,
) -> dict:
	"""Agent-time percentiles per bucket, elements sorted by total time, a summary against the prior period."""
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
			_time_split(_latency_steps(from_d, to_d, origin, filters)),
			_time_split(_latency_steps(previous_from, previous_to, origin, filters)),
		),
		"elements": _elements(current, previous, _step_counts(from_d, to_d, origin, filters), group_by),
	}


def get_step_latency_report(
	from_date: str | None = None,
	to_date: str | None = None,
	origin: str = "production",
	model: str | None = None,
	provider: str | None = None,
	process_model: str | None = None,
	agent_configuration: str | None = None,
	key: str | None = None,
	group_by: str = "model",
	limit: int = 3,
) -> dict:
	"""How step latency splits between model, tools and sub-calls, and the step labels that cost the most.
	key narrows both to one element, bpmn_id|process_model|series."""
	group_by = group_by if group_by in ("model", "agent") else "model"
	from_d, to_d = default_dates(from_date, to_date)
	filters = {
		"model": model,
		"provider": provider,
		"process_model": process_model,
		"agent_configuration": agent_configuration,
	}
	steps = _latency_steps(from_d, to_d, origin, filters, key, group_by)
	tool_names = _tool_names([s.name for s in steps if s.role == "tool"])
	return {
		"split": _time_split(steps),
		"rows": _step_rows(steps, tool_names)[: _clamped(limit)],
	}


def get_element_runs(
	key: str,
	from_date: str | None = None,
	to_date: str | None = None,
	origin: str = "production",
	model: str | None = None,
	provider: str | None = None,
	process_model: str | None = None,
	agent_configuration: str | None = None,
	group_by: str = "model",
	min_agent_latency_ms: int = 0,
	limit: int = 3,
	offset: int = 0,
) -> dict:
	"""Measured top-level runs of one element at or above min_agent_latency_ms, slowest first, paged."""
	group_by = group_by if group_by in ("model", "agent") else "model"
	from_d, to_d = default_dates(from_date, to_date)
	filters = {
		"model": model,
		"provider": provider,
		"process_model": process_model,
		"agent_configuration": agent_configuration,
	}
	Run = DocType("AI Agent Run")
	query = _element_query(_counted_query(Run, from_d, to_d, origin, filters), Run, key, group_by)
	query = query.where(Run.agent_latency_ms > 0).where(Run.agent_latency_ms >= cint(min_agent_latency_ms))

	total = query.select(fn.Count("*").as_("n")).run(as_dict=True)[0]["n"]
	runs = (
		query.select(Run.name, Run.started_at, Run.status, Run.error_code, Run.agent_latency_ms, Run.model)
		.orderby(Run.agent_latency_ms, order=frappe.qb.desc)
		.limit(_clamped(limit))
		.offset(max(cint(offset), 0))
		.run(as_dict=True)
	)
	steps = _run_steps([r.name for r in runs])
	return {
		"total": cint(total),
		"runs": [
			{
				"name": r.name,
				"started_at": cstr(r.started_at),
				"status": r.status,
				"error_code": cstr(r.error_code),
				"agent_latency_ms": cint(r.agent_latency_ms),
				"step_count": len(steps[r.name]),
				"slowest_step": _slowest_step(steps[r.name], r.model),
			}
			for r in runs
		],
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


def _latency_steps(from_d, to_d, origin: str, filters: dict, key: str | None = None, group_by: str = "model"):
	"""Steps with latency of the counted runs, prompts left out, each tagged with its kind and split part."""
	Run = DocType("AI Agent Run")
	Step = DocType("AI Agent Step")
	query = _counted_query(Run, from_d, to_d, origin, filters)
	if key:
		query = _element_query(query, Run, key, group_by)
	steps = (
		query.join(Step)
		.on(Step.run == Run.name)
		.select(
			Step.name,
			Step.role,
			Step.step_kind,
			Step.latency_ms,
			fn.Substring(Step.content, 1, SUB_CALL_CHARS).as_("content"),
			Run.model,
			Run.agent_configuration,
		)
		.where(Step.latency_ms > 0)
		.run(as_dict=True)
	)
	for s in steps:
		s.kind = s.step_kind or classify_step(s.role, s.content)
		s.part = _split_part(s.kind, s.role)
	return [s for s in steps if s.part != "prompt"]


def _time_split(steps: list) -> dict:
	"""Share of step latency spent in model calls, tools and sub-calls, 1 dp, and the average step of each."""
	totals = defaultdict(int)
	counts = defaultdict(int)
	for s in steps:
		totals[s.part] += cint(s.latency_ms)
		counts[s.part] += 1
	whole = sum(totals.values())
	split = {f"{part}_share": flt(totals[part] / whole * 100, 1) if whole else 0.0 for part in SPLIT_PARTS}
	for part in SPLIT_PARTS:
		split[f"{part}_avg_ms"] = cint(totals[part] / counts[part]) if counts[part] else 0
	return split


def _step_rows(steps: list, tool_names: dict) -> list:
	"""One row per step label and agent with its count, total, average, max and share, costliest first."""
	whole = sum(cint(s.latency_ms) for s in steps)
	groups = defaultdict(list)
	for s in steps:
		label = _step_label(s, tool_names.get(s.name, []), s.model)
		groups[(label, s.part, cstr(s.agent_configuration))].append(cint(s.latency_ms))
	rows = [
		{
			"step_kind": label,
			"kind": part,
			"agent_configuration": agent,
			"steps": len(values),
			"total_ms": sum(values),
			"avg_ms": cint(sum(values) / len(values)),
			"max_ms": max(values),
			"share": flt(sum(values) / whole * 100, 1),
		}
		for (label, part, agent), values in groups.items()
	]
	return sorted(rows, key=lambda r: r["total_ms"], reverse=True)


def _run_steps(run_names: list) -> dict:
	"""Every step of the given runs, keyed by run."""
	steps = defaultdict(list)
	if not run_names:
		return steps
	Step = DocType("AI Agent Step")
	rows = (
		frappe.qb.from_(Step)
		.select(
			Step.run,
			Step.name,
			Step.role,
			Step.step_kind,
			Step.latency_ms,
			fn.Substring(Step.content, 1, SUB_CALL_CHARS).as_("content"),
		)
		.where(Step.run.isin(run_names))
		.run(as_dict=True)
	)
	for r in rows:
		r.kind = r.step_kind or classify_step(r.role, r.content)
		steps[r.run].append(r)
	return steps


def _slowest_step(steps: list, model: str) -> dict | None:
	"""Label and latency of the run's slowest step, None for a run without steps."""
	if not steps:
		return None
	slowest = max(steps, key=lambda s: cint(s.latency_ms))
	names = _tool_names([slowest.name]) if slowest.role == "tool" else {}
	return {
		"label": _step_label(slowest, names.get(slowest.name, []), model),
		"latency_ms": cint(slowest.latency_ms),
	}


def _step_label(step, tool_names: list, model: str) -> str:
	sub_call = parse_sub_call(step.content) if step.kind == "sub_call" else None
	return step_kind(step.role, sub_call, tool_names, model)


def step_kind(role: str, sub_call: dict | None, tool_names: list, model: str | None = None) -> str:
	"""Readable label of a step: prompt, sub-call with its tool, tool with its names, or model call."""
	if role in ("system", "user"):
		return _("prompt: {0}").format(role)
	if sub_call:
		return _("sub-call: {0}").format(sub_call["tool"])
	if role == "tool":
		return _("tool: {0}").format(", ".join(tool_names)) if tool_names else _("tool")
	return _("model call: {0}").format(cstr(model))


def _tool_names(step_names: list) -> dict:
	"""Tool names called by each step, in call order."""
	names = defaultdict(list)
	if not step_names:
		return names
	Call = DocType("AI Agent Tool Call")
	rows = (
		frappe.qb.from_(Call)
		.select(Call.parent, Call.tool_name)
		.where(Call.parenttype == "AI Agent Step")
		.where(Call.parent.isin(step_names))
		.orderby(Call.idx)
		.run(as_dict=True)
	)
	for r in rows:
		names[r.parent].append(r.tool_name)
	return names


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


def _element_query(query, Run, key: str, group_by: str):
	"""Narrow a run query to one element; an empty key part matches null or empty."""
	parts = cstr(key).split("|")
	if len(parts) != ELEMENT_KEY_PARTS:
		frappe.throw(_("Element key must be bpmn_id|process_model|series"))
	fields = (Run.bpmn_id, Run.process_model, series_field(Run, group_by))
	for field, value in zip(fields, parts, strict=True):
		query = query.where(field == value) if value else query.where(field.isnull() | (field == ""))
	return query


def _clamped(limit) -> int:
	return min(max(cint(limit), 1), ISSUE_RUNS_MAX_LIMIT)


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
