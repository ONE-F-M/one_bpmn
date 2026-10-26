"""Reclassify Achieved runs whose stored tool calls show a failure that was never retried successfully.

The trace is not stored on the run, so it is rebuilt from AI Agent Step and AI Agent Tool Call in step order.
"""

from itertools import groupby

import frappe

from one_bpmn.agents.goal_completion import ACHIEVED, NOT_ACHIEVED, _excerpt, unsuperseded_tool_failure


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
		hit = unsuperseded_tool_failure(list(calls))
		if not hit:
			continue
		name, result = hit
		frappe.db.set_value(
			"AI Agent Run",
			run_name,
			{
				"goal_completion": NOT_ACHIEVED,
				"completion_basis": f"Tool '{name}' failed and was not retried successfully: {_excerpt(result)}",
			},
			update_modified=False,
		)
