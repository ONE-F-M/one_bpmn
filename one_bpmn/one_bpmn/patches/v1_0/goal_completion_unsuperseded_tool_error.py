"""WI-001823 follow-up: a tool failure that was never retried successfully is
not achievement, even when the run went on to call finalize.

determine() now catches this going forward (agents/goal_completion.py); this
repairs the Achieved runs recorded before that fix. The executor trace is not
stored on the AI Agent Run itself, so it is rebuilt here from the AI Agent
Step / AI Agent Tool Call rows each run already has, in step order \u2014 the same
ordering record_selector_turns() wrote them in.

Scope: AI Agent Run rows with goal_completion = "Achieved". Applies the same
last-call-per-tool rule as determine(): if a tool's LAST call (across the
whole run, not just one step) failed, the run is reclassified Not Achieved.
A tool that failed and later succeeded on retry is left untouched.
"""

import frappe
from frappe.query_builder import DocType

from one_bpmn.agents.goal_completion import NOT_ACHIEVED, _excerpt, unsuperseded_tool_failure


def execute():
	frappe.reload_doc("one_bpmn", "doctype", "ai_agent_step")
	frappe.reload_doc("one_bpmn", "doctype", "ai_agent_tool_call")
	frappe.reload_doc("one_bpmn", "doctype", "ai_agent_run")

	achieved_runs = frappe.get_all(
		"AI Agent Run",
		filters={"goal_completion": "Achieved"},
		pluck="name",
	)

	fixed = 0
	for run_name in achieved_runs:
		calls = _ordered_tool_calls(run_name)
		if not calls:
			continue
		hit = unsuperseded_tool_failure(calls)
		if not hit:
			continue
		name, result = hit
		frappe.db.set_value(
			"AI Agent Run",
			run_name,
			{
				"goal_completion": NOT_ACHIEVED,
				"completion_basis": (
					f"Tool '{name}' failed and was not retried successfully: {_excerpt(result)}"
				),
			},
			update_modified=False,
		)
		fixed += 1

	frappe.logger("one_bpmn").info(
		f"WI-001823 unsuperseded-tool-error patch: reclassified {fixed} of "
		f"{len(achieved_runs)} Achieved runs as Not Achieved"
	)


def _ordered_tool_calls(run_name: str) -> list:
	"""Every tool call on *run_name*, in the order it really happened: step
	order, then call order within a step."""
	Step = DocType("AI Agent Step")
	steps = (
		frappe.qb.from_(Step)
		.select(Step.name)
		.where(Step.run == run_name)
		.orderby(Step.step_index)
	).run(as_dict=True)
	if not steps:
		return []

	ToolCall = DocType("AI Agent Tool Call")
	calls = []
	for step in steps:
		rows = (
			frappe.qb.from_(ToolCall)
			.select(ToolCall.tool_name, ToolCall.tool_result)
			.where(ToolCall.parent == step["name"])
			.orderby(ToolCall.idx)
		).run(as_dict=True)
		for row in rows:
			if not row.get("tool_name"):
				continue
			calls.append({"name": row["tool_name"], "result": row.get("tool_result")})
	return calls
