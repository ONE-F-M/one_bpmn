# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Every existing AI Agent Step gets a kind and a time window.

Steps were written after the loop finished, so their creation time says when
the run ended, not when the step ran. The window is rebuilt backwards from the
run's end through each step's latency, oldest step first, so a run reads as a
sequence again. A run with no end uses the last step's creation.
"""

from __future__ import annotations

from datetime import timedelta

import frappe
from frappe.query_builder import DocType
from frappe.utils import cint, get_datetime

from one_bpmn.agents.observability import classify_step


def execute():
	Step = DocType("AI Agent Step")
	frappe.qb.update(Step).set(Step.step_kind, "prompt").where(
		Step.role.isin(["system", "user"]) & (Step.step_kind.isnull() | (Step.step_kind == ""))
	).run()
	frappe.qb.update(Step).set(Step.step_kind, "tool_turn").where(
		(Step.role == "tool") & (Step.step_kind.isnull() | (Step.step_kind == ""))
	).run()
	frappe.qb.update(Step).set(Step.step_kind, "sub_call").where(
		(Step.role == "assistant") & Step.content.like("[sub-call:%")
		& (Step.step_kind.isnull() | (Step.step_kind == ""))
	).run()
	frappe.qb.update(Step).set(Step.step_kind, "model_call").where(
		Step.step_kind.isnull() | (Step.step_kind == "")
	).run()
	frappe.db.commit()

	runs = frappe.get_all(
		"AI Agent Step", filters={"started_at": ["is", "not set"]}, fields=["run"], distinct=True,
		limit_page_length=0,
	)
	for row in runs:
		_window_run(row.run)
	frappe.db.commit()


def _window_run(run_name: str) -> None:
	steps = frappe.get_all(
		"AI Agent Step",
		filters={"run": run_name, "started_at": ["is", "not set"]},
		fields=["name", "latency_ms", "creation"],
		order_by="step_index asc, creation asc",
	)
	if not steps:
		return
	ended_at = frappe.db.get_value("AI Agent Run", run_name, "ended_at")
	cursor = get_datetime(ended_at) if ended_at else get_datetime(steps[-1].creation)
	for step in reversed(steps):
		start = cursor - timedelta(milliseconds=cint(step.latency_ms))
		frappe.db.set_value(
			"AI Agent Step", step.name, {"started_at": start, "ended_at": cursor}, update_modified=False
		)
		cursor = start
