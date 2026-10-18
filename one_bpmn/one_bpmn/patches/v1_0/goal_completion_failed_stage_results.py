"""Reclassify Achieved runs whose stored stage tool results report a failed stage.

The trace is not stored on the run, so it is rebuilt from AI Agent Step and AI Agent Tool Call in step order.
"""

from itertools import groupby

import frappe

from one_bpmn.agents.goal_completion import ACHIEVED, NOT_ACHIEVED, stage_failure


def execute():
	run = frappe.qb.DocType("AI Agent Run")
	step = frappe.qb.DocType("AI Agent Step")
	call = frappe.qb.DocType("AI Agent Tool Call")
	rows = (
		frappe.qb.from_(call)
		.join(step)
		.on(call.parent == step.name)
		.join(run)
		.on(step.run == run.name)
		.select(run.name.as_("run"), call.tool_name.as_("name"), call.tool_result.as_("result"))
		.where(call.parenttype == "AI Agent Step")
		.where(run.goal_completion == ACHIEVED)
		.orderby(run.name)
		.orderby(step.step_index)
		.orderby(call.idx)
	).run(as_dict=True)

	for run_name, calls in groupby(rows, key=lambda row: row.run):
		hit = stage_failure(list(calls))
		if not hit:
			continue
		frappe.db.set_value(
			"AI Agent Run",
			run_name,
			{"goal_completion": NOT_ACHIEVED, "completion_basis": hit[1]},
			update_modified=False,
		)
