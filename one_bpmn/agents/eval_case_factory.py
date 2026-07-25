# Copyright (c) 2026, one-fm and contributors
# WI-001363 (5-03): convert a production AI Agent Run into a regression
# test case — the concrete link between observability (4-01) and the eval
# system. AI Eval Case.source_run was designed for exactly this; until now
# nothing populated it.

import frappe
from frappe import _
from frappe.utils import get_datetime


@frappe.whitelist()
def get_run_steps_for_case_picker(run_name: str) -> list:
	"""
	Steps of a subprocess Run for the "which Step / which tool call" picker
	(Scenario 2) — a subprocess Run has no single input/output the way a
	plain task Run does.
	"""
	frappe.only_for("System Manager")

	steps = frappe.get_all(
		"AI Agent Step",
		filters={"run": run_name},
		fields=["name", "step_index", "role", "content"],
		order_by="step_index asc",
	)
	if frappe.db.exists("DocType", "AI Agent Tool Call"):
		for step in steps:
			step["tool_calls"] = frappe.get_all(
				"AI Agent Tool Call",
				filters={"parent": step.name, "parenttype": "AI Agent Step"},
				fields=["name", "tool_name", "tool_result"],
				order_by="idx asc",
			)
	else:
		for step in steps:
			step["tool_calls"] = []
	return steps


@frappe.whitelist()
def create_eval_case_from_run(
	run_name: str,
	step_name: str | None = None,
	tool_call_name: str | None = None,
	suite: str | None = None,
) -> str:
	"""
	Create an AI Eval Case pre-filled from an AI Agent Run (Scenario 1).

	Plain task Runs (element_type="task") need no extra arguments. For
	subprocess Runs the caller picks the Step — and, when that Step made
	several tool calls, the specific AI Agent Tool Call — to base the case
	on; its tool_result pre-fills expected_output (Scenario 3), giving the
	designer a starting point for an "equals" or "llm_judge" assertion.

	Returns the new AI Eval Case name; source_run links back to the
	originating Run (Scenario 4). No assertions are auto-generated beyond
	the expected_output pre-fill.
	"""
	frappe.only_for("System Manager")

	run = frappe.get_doc("AI Agent Run", run_name)
	if run.status not in ("Success", "Error"):
		frappe.throw(_("Only finished runs (Success or Error) can become eval cases."))

	steps = frappe.get_all(
		"AI Agent Step",
		filters={"run": run_name},
		fields=["name", "role", "content"],
		order_by="step_index asc",
	)
	system_prompt = next((s.content for s in steps if s.role == "system"), "")
	user_prompt = next((s.content for s in steps if s.role == "user"), "")

	expected_output = ""
	title_suffix = ""
	if run.element_type == "subprocess":
		if not step_name:
			frappe.throw(
				_(
					"Run '{0}' is a subprocess run with multiple Steps — pick the "
					"Step (and tool call) to base the case on."
				).format(run_name)
			)
		if tool_call_name:
			call = frappe.get_doc("AI Agent Tool Call", tool_call_name)
			if call.parent != step_name:
				frappe.throw(_("The tool call does not belong to the selected Step."))
			expected_output = call.tool_result or ""
			title_suffix = f" · {call.tool_name}"
		else:
			step_doc = frappe.get_doc("AI Agent Step", step_name)
			if step_doc.run != run_name:
				frappe.throw(_("The Step does not belong to this Run."))
			calls = frappe.get_all(
				"AI Agent Tool Call", filters={"parent": step_name}, pluck="name"
			)
			if len(calls) > 1:
				frappe.throw(
					_(
						"This Step made {0} tool calls — pick the specific call to "
						"base the case on."
					).format(len(calls))
				)
			if calls:
				expected_output = (
					frappe.db.get_value("AI Agent Tool Call", calls[0], "tool_result") or ""
				)
			else:
				expected_output = step_doc.content or ""
	else:
		expected_output = run.final_output or ""

	case = frappe.get_doc(
		{
			"doctype": "AI Eval Case",
			# Readable title (no raw run id); source_run keeps the link.
			"title": f"From run · {get_datetime(run.creation).strftime('%Y-%m-%d %H:%M')}{title_suffix}",
			"suite": suite or "",
			"source_run": run_name,
			"process_model": run.process_model or "",
			"bpmn_id": run.bpmn_id or "",
			# WI-001751: the case tests the suite's agent; it carries only the
			# prompt + expected output (provider/model/system prompt come from
			# the agent). ``system_prompt`` above is no longer stored on the case.
			"input_user_prompt": user_prompt,
			"expected_output": expected_output,
		}
	)
	case.flags.ignore_mandatory = True
	case.insert()
	return case.name
