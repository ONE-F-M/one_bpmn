"""Error report, issue drill-down and export."""
from __future__ import annotations

import math
from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import cint, cstr, flt, getdate
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


# ---------------------------------------------------------------------------
# 3. Error report
# ---------------------------------------------------------------------------

COUNTED_EXCLUDED_STATUSES = ("Running", "Suspended")

ISSUE_KEY_PARTS = 4

ISSUE_RUNS_MAX_LIMIT = 50

MESSAGE_CHARS = 200


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

	current = _error_period(from_d, to_d, origin, filters, group_by)
	previous = _error_period(previous_from, previous_to, origin, filters, group_by)
	codes = _error_codes(current, from_d, origin)
	issues = _error_issues(current, previous, from_d, to_d, origin, filters, group_by, error_code)
	summary = _error_summary(current, previous)

	return {
		"grain": grain,
		"from_date": cstr(from_d),
		"to_date": cstr(to_d),
		"previous_from": cstr(previous_from),
		"previous_to": cstr(previous_to),
		"timeseries": _error_timeseries(from_d, to_d, origin, filters, grain),
		"codes": codes,
		"issues": issues,
		"summary": summary,
	}


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
	parts = cstr(key).split("|")
	if len(parts) != ISSUE_KEY_PARTS:
		frappe.throw(_("Issue key must be error_code|bpmn_id|process_model|series"))
	group_by = group_by if group_by in ("model", "agent") else "model"
	from_d, to_d = default_dates(from_date, to_date)
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
		.where(origin_condition(Run, origin))
	)


def _scoped(query, Run, from_d, to_d, origin: str, filters: dict):
	return apply_common_filters(_in_range(query, Run, from_d, to_d, origin), Run, **filters)


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
	retry_recovery_rate = _rate(recovered, retried)
	previous_retry_recovery_rate = _rate(previous_recovered, previous_retried) if previous_runs else None
	return {
		"runs": runs,
		"errors": errors,
		"error_rate": error_rate,
		"previous_errors": previous_errors,
		"previous_error_rate": previous_error_rate,
		"delta_pt": flt(error_rate - previous_error_rate, 1) if previous_runs else None,
		"errors_delta": flt((errors - previous_errors) / previous_errors * 100, 1)
		if previous_errors
		else None,
		"suspended": current["suspended"],
		"retried": retried,
		"retry_recovered": recovered,
		"retry_recovery_rate": retry_recovery_rate,
		"previous_retry_recovery_rate": previous_retry_recovery_rate,
		"retry_recovery_delta_pt": flt(retry_recovery_rate - previous_retry_recovery_rate, 1)
		if previous_retried
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
		.where(origin_condition(Run, origin))
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
		.where(origin_condition(Run, origin))
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
	labels = list_bucket_labels(from_d, to_d, grain)
	runs = defaultdict(int)
	errors = defaultdict(int)
	by_code = defaultdict(lambda: defaultdict(int))
	for r in rows:
		bucket = cstr(bucket_start(r.day, grain))
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
