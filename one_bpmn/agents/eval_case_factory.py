# Copyright (c) 2026, one-fm and contributors
# WI-001363 (5-03): convert a production AI Agent Run into a regression
# test case — the concrete link between observability (4-01) and the eval
# system. AI Eval Case.source_run was designed for exactly this; until now
# nothing populated it.

import frappe
from frappe import _
from frappe.utils import get_datetime


def _assert_may_read_run(run_name: str):
	"""A run's contents are visible to its process owner, or a System Manager.

	AI Agent Run itself is System-Manager-only at the doctype level; this is the
	narrower grant that lets a process owner work with their own runs without
	opening every run on the platform to the role.
	"""
	from one_bpmn.agents.eval_permissions import _is_system_manager, _process_model_owned_by

	user = frappe.session.user
	if _is_system_manager(user):
		return
	process_model = frappe.db.get_value("AI Agent Run", run_name, "process_model")
	if not (process_model and _process_model_owned_by(process_model, user)):
		frappe.throw(
			_("You can only work with runs of a process you own."),
			frappe.PermissionError,
		)


def _assert_may_author_case(run_name: str, suite: str | None):
	"""Gate the create-from-run path without widening access to AI Agent Run.

	This action used to be only_for("System Manager") while the UI calling it —
	the Evals "From run" dialog and the AI Agent Run desk buttons — was not
	role-gated, so a Process Owner saw the button and got a PermissionError.

	Two things have to hold for a non-System-Manager, and they are separate:

	1. The DESTINATION. Permission on an eval case comes from its suite
	   (eval_permissions: suite -> process_model -> Process.process_owner,
	   falling back to the suite's owner), so writing the suite is the right
	   test — the same one eval_api.create_eval_case applies. A case with NO
	   suite has no anchor at all: nothing scopes it and the suite views cannot
	   see it, so that stays System-Manager-only.

	2. The SOURCE. AI Agent Run is readable only by System Manager, and it holds
	   every prompt and response on the platform — so check_permission("read")
	   would simply block process owners, and granting the role read on the
	   doctype would expose far more than their own work. Instead a process
	   owner is allowed through only for runs belonging to a process they own,
	   reusing the same ownership chain. Runs with no process_model (a direct
	   eval, or a run predating attribution) have nothing to scope on and stay
	   System-Manager-only.
	"""
	from one_bpmn.agents.eval_permissions import _is_system_manager

	if _is_system_manager(frappe.session.user):
		return

	if not suite:
		frappe.throw(
			_("Building a case from a run without choosing a suite requires the "
			  "System Manager role. Pick a suite to add the case to."),
			frappe.PermissionError,
		)
	frappe.get_doc("AI Eval Suite", suite).check_permission("write")
	_assert_may_read_run(run_name)


@frappe.whitelist()
def get_run_steps_for_case_picker(run_name: str) -> list:
	"""
	Steps of a subprocess Run for the "which Step / which tool call" picker
	(Scenario 2) — a subprocess Run has no single input/output the way a
	plain task Run does.

	Gated the same way as authoring the case itself, minus the suite: the picker
	is opened from the Evals page by process owners who may never be System
	Managers, but it exposes a run's full step content, so a process owner sees
	it only for a process they own.
	"""
	_assert_may_read_run(run_name)

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

	Requires read on the run, plus write on ``suite`` when one is given —
	System Manager only when it is not. See _assert_may_author_case.
	"""
	_assert_may_author_case(run_name, suite)

	run = frappe.get_doc("AI Agent Run", run_name)
	if run.status not in ("Success", "Error"):
		frappe.throw(_("Only finished runs (Success or Error) can become eval cases."))

	steps = frappe.get_all(
		"AI Agent Step",
		filters={"run": run_name},
		fields=["name", "role", "content"],
		order_by="step_index asc",
	)
	# Only the user turn is carried onto the case: the system prompt comes from
	# the suite's agent configuration at run time (WI-001751).
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


@frappe.whitelist()
def list_runs_for_case_picker(suite: str, limit: int = 40) -> list:
	"""Runs the suite's agent has produced, newest first, for the "From run" picker.

	The dialog used to ask for an AI Agent Run name as free text, which meant
	knowing a hash id before you could use the feature at all. The candidates
	are knowable: a suite tests one agent (AI Eval Suite.agent_configuration,
	mandatory since WI-001743), so the runs worth turning into a case are that
	agent's runs and no others.

	Returns ``[]`` — not an error — for a suite with no agent, so the dialog can
	say so plainly instead of failing.

	Eval-origin runs are excluded: they were produced BY the eval system, so
	turning one into a case would be a test of a test. Failed runs are kept —
	capturing an Error as a regression case is the point of WI-001363.

	Visibility follows _assert_may_read_run rather than the doctype: AI Agent
	Run is System-Manager-only and holds every prompt on the platform, so a
	process owner sees only runs of a process they own. Ownership is resolved
	once per process model rather than once per run.
	"""
	from one_bpmn.agents.eval_permissions import _is_system_manager, _process_model_owned_by

	suite_doc = frappe.get_doc("AI Eval Suite", suite)  # 404s if missing
	suite_doc.check_permission("read")

	agent = suite_doc.agent_configuration
	if not agent:
		return []

	runs = frappe.get_all(
		"AI Agent Run",
		filters={"agent_configuration": agent, "origin": ("!=", "eval")},
		fields=[
			"name", "status", "started_at", "creation",
			"bpmn_label", "bpmn_id", "process_model",
		],
		order_by="COALESCE(started_at, creation) desc",
		limit_page_length=frappe.utils.cint(limit) or 40,
	)

	if not _is_system_manager(frappe.session.user):
		owned = {
			pm
			for pm in {r.process_model for r in runs if r.process_model}
			if _process_model_owned_by(pm, frappe.session.user)
		}
		runs = [r for r in runs if r.process_model in owned]

	return [
		{
			"name": r.name,
			"status": r.status,
			"when": frappe.utils.format_datetime(r.started_at or r.creation, "d MMM, HH:mm"),
			# What produced it, most specific first. A direct (map-less) run has
			# none of these, and "Direct call" beats a blank column.
			"source": r.bpmn_label or r.bpmn_id or r.process_model or _("Direct call"),
		}
		for r in runs
	]
