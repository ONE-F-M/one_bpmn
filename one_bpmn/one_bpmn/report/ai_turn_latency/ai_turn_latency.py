import statistics

import frappe
from frappe import _
from frappe.utils import cint

DEFAULT_RUNS = 20
TURN_KINDS = ("model_call", "tool_turn")
SUMMARY_KEYS = (
	("queue_ms", "Median Queue (ms)"),
	("engine_ms", "Median Engine (ms)"),
	("model_ms", "Median Model (ms)"),
	("tool_llm_ms", "Median Model in Tools (ms)"),
	("tool_ms", "Median Tool (ms)"),
	("wall_ms", "Median Wall (ms)"),
	("turn", "Median Turns"),
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	runs = get_runs(filters)
	steps = get_steps_by_run([run.name for run in runs])
	data, run_rows = [], []
	for run in runs:
		run_row, turn_rows = break_down(run, steps.get(run.name, []))
		run_rows.append(run_row)
		data.append(run_row)
		data.extend(turn_rows)
	return get_columns(), data, None, None, get_summary(run_rows)


def get_runs(filters):
	run_filters = {
		"agent_configuration": filters.agent_configuration,
		"status": ["in", ["Success", "Error"]],
	}
	if filters.origin:
		run_filters["origin"] = filters.origin
	return frappe.get_list(
		"AI Agent Run",
		filters=run_filters,
		fields=["name", "started_at", "duration_ms", "human_wait_ms", "queue_wait_ms"],
		order_by="started_at desc",
		limit_page_length=cint(filters.runs) or DEFAULT_RUNS,
	)


def get_steps_by_run(run_names):
	steps = {}
	if not run_names:
		return steps
	for step in frappe.get_list(
		"AI Agent Step",
		filters={"run": ["in", run_names]},
		fields=["run", "step_kind", "latency_ms", "model_latency_ms", "started_at", "ended_at"],
		order_by="started_at asc",
		limit_page_length=0,
	):
		steps.setdefault(step.run, []).append(step)
	return steps


def break_down(run, steps):
	"""One row for the run and one per model turn, splitting each into queue,
	engine, model, model calls made inside tools, and the tools' own time."""
	sub_calls = [s for s in steps if s.step_kind == "sub_call"]
	turn_rows, prev_end = [], None
	for step in steps:
		if step.step_kind == "sub_call":
			continue
		if step.step_kind in TURN_KINDS:
			inside = sum(
				cint(s.latency_ms) for s in sub_calls if step.started_at <= s.ended_at <= step.ended_at
			)
			turn_rows.append(turn_row(run, len(turn_rows) + 1, step, prev_end, inside))
		prev_end = step.ended_at

	tool_llm = sum(r["tool_llm_ms"] for r in turn_rows)
	# Compaction runs between turns, so its model time sits outside every turn.
	between = sum(cint(s.latency_ms) for s in sub_calls) - tool_llm
	known = all(r["model_ms"] is not None for r in turn_rows)
	agent_wall = cint(run.duration_ms) - cint(run.human_wait_ms)
	run_row = {
		"indent": 0,
		"run": run.name,
		"turn": len(turn_rows),
		"started_at": run.started_at,
		"queue_ms": cint(run.queue_wait_ms),
		"engine_ms": agent_wall - sum(r["wall_ms"] for r in turn_rows) - between,
		"model_ms": sum(r["model_ms"] for r in turn_rows) + between if known else None,
		"tool_llm_ms": tool_llm,
		"tool_ms": sum(r["tool_ms"] for r in turn_rows) if known else None,
		"wall_ms": agent_wall,
	}
	return run_row, turn_rows


def turn_row(run, turn_no, step, prev_end, tool_llm):
	wall = cint(step.latency_ms)
	# A turn recorded before model latency was stored has 0 against a real wall time.
	model = cint(step.model_latency_ms) if step.model_latency_ms or not wall else None
	return {
		"indent": 1,
		"run": run.name,
		"turn": turn_no,
		"started_at": step.started_at,
		"queue_ms": None,
		"engine_ms": max(0, to_ms(step.started_at - prev_end)) if prev_end else None,
		"model_ms": model,
		"tool_llm_ms": tool_llm,
		"tool_ms": wall - model - tool_llm if model is not None else None,
		"wall_ms": wall,
	}


def to_ms(delta):
	return int(delta.total_seconds() * 1000)


def get_summary(run_rows):
	measured = [r for r in run_rows if r["model_ms"] is not None]
	if not measured:
		return []
	summary = [
		{"label": _(label), "value": statistics.median(r[key] for r in measured), "datatype": "Int"}
		for key, label in SUMMARY_KEYS
	]
	walls = [r["wall_ms"] for r in measured]
	if len(walls) > 1:
		summary.append(
			{"label": _("P90 Wall (ms)"), "value": statistics.quantiles(walls, n=10)[-1], "datatype": "Int"}
		)
	summary.append({"label": _("Runs Measured"), "value": len(measured), "datatype": "Int"})
	return summary


def get_columns():
	return [
		{"fieldname": "run", "label": _("Run"), "fieldtype": "Link", "options": "AI Agent Run", "width": 160},
		{"fieldname": "turn", "label": _("Turn"), "fieldtype": "Int", "width": 70},
		{"fieldname": "started_at", "label": _("Started At"), "fieldtype": "Datetime", "width": 170},
		{"fieldname": "queue_ms", "label": _("Queue (ms)"), "fieldtype": "Int", "width": 110},
		{"fieldname": "engine_ms", "label": _("Engine (ms)"), "fieldtype": "Int", "width": 110},
		{"fieldname": "model_ms", "label": _("Model (ms)"), "fieldtype": "Int", "width": 110},
		{"fieldname": "tool_llm_ms", "label": _("Model in Tools (ms)"), "fieldtype": "Int", "width": 150},
		{"fieldname": "tool_ms", "label": _("Tool (ms)"), "fieldtype": "Int", "width": 110},
		{"fieldname": "wall_ms", "label": _("Wall (ms)"), "fieldtype": "Int", "width": 110},
	]
