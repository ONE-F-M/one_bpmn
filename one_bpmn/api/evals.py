"""Whitelisted endpoints for the Processa Evals pages; each checks permission and calls ai_agent_evals."""

from typing import Any

import frappe

from one_bpmn.ai_agent_evals import case_authoring, feedback, overview, run_compare, run_review, suites


@frappe.whitelist()
def list_eval_suites() -> dict:
	"""Eval suites the user can see, each with its latest run."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return suites.list_eval_suites()


@frappe.whitelist()
def get_evals_overview(from_date: str | None = None, to_date: str | None = None) -> dict:
	"""Portfolio metrics for the Evals dashboard."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return overview.get_evals_overview(from_date=from_date, to_date=to_date)


@frappe.whitelist()
def get_suite_detail(suite: str, start: int = 0, page_length: int = 25) -> dict:
	"""One suite with its cases, runs and thresholds."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return suites.get_suite_detail(suite=suite, start=start, page_length=page_length)


@frappe.whitelist(methods=["POST"])
def create_eval_case(
	suite: str,
	title: str,
	input_user_prompt: str,
	expected_output: str = "",
	assertions: Any = None,
	expected_tool_calls: Any = None,
	case_type: str | None = None,
	target_skill: str | None = None,
	input_context: Any = None,
) -> str:
	"""Create an eval case on a suite."""
	frappe.has_permission("AI Eval Case", "create", throw=True)
	return case_authoring.create_eval_case(
		suite=suite,
		title=title,
		input_user_prompt=input_user_prompt,
		expected_output=expected_output,
		assertions=assertions,
		expected_tool_calls=expected_tool_calls,
		case_type=case_type,
		target_skill=target_skill,
		input_context=input_context,
	)


@frappe.whitelist()
def get_eval_case(name: str) -> dict:
	"""One eval case with its assertions and expected tool calls."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return case_authoring.get_eval_case(name=name)


@frappe.whitelist()
def list_conversations_for_case(suite: str, search: str = "", limit: int = 30) -> list:
	"""Conversations a case can start from."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return case_authoring.list_conversations_for_case(suite=suite, search=search, limit=limit)


@frappe.whitelist()
def get_conversation_for_case(suite: str, conversation: str) -> list:
	"""The messages of a conversation a case can start from."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return case_authoring.get_conversation_for_case(suite=suite, conversation=conversation)


@frappe.whitelist()
def conversation_context_for_case(
	suite: str,
	conversation: str,
	message: str,
	include_message: int = 0,
) -> dict:
	"""Context of a conversation up to a chosen message."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return case_authoring.conversation_context_for_case(
		suite=suite,
		conversation=conversation,
		message=message,
		include_message=include_message,
	)


@frappe.whitelist(methods=["POST"])
def update_eval_case(
	name: str,
	title: str | None = None,
	input_user_prompt: str | None = None,
	expected_output: str | None = None,
	assertions: Any = None,
	expected_tool_calls: Any = None,
	case_type: str | None = None,
	target_skill: str | None = None,
	input_context: Any = None,
) -> str:
	"""Update an eval case."""
	frappe.has_permission("AI Eval Case", "write", throw=True)
	return case_authoring.update_eval_case(
		name=name,
		title=title,
		input_user_prompt=input_user_prompt,
		expected_output=expected_output,
		assertions=assertions,
		expected_tool_calls=expected_tool_calls,
		case_type=case_type,
		target_skill=target_skill,
		input_context=input_context,
	)


@frappe.whitelist()
def get_run_review(run: str, baseline: str | None = None) -> dict:
	"""One run reviewed case by case, optionally against a baseline run."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return run_review.get_run_review(run=run, baseline=baseline)


@frappe.whitelist()
def list_assignable_agents(include_all: int = 0) -> list:
	"""Agent configurations a suite can be assigned to."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return suites.list_assignable_agents(include_all=include_all)


@frappe.whitelist()
def list_owned_processes() -> list:
	"""Process models the user may attach a suite to."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return suites.list_owned_processes()


@frappe.whitelist()
def case_consistency(suite: str, days: int = 7, limit: int = 100) -> dict:
	"""Per-case pass consistency over recent runs of a suite."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return case_authoring.case_consistency(suite=suite, days=days, limit=limit)


@frappe.whitelist(methods=["POST"])
def update_suite_thresholds(
	suite: str,
	pass_k: Any = None,
	min_pass_rate: Any = None,
	gate_deployment: Any = None,
	ci_role: Any = None,
) -> dict:
	"""Update a suite's pass thresholds and gate settings."""
	frappe.has_permission("AI Eval Suite", "write", throw=True)
	return suites.update_suite_thresholds(
		suite=suite,
		pass_k=pass_k,
		min_pass_rate=min_pass_rate,
		gate_deployment=gate_deployment,
		ci_role=ci_role,
	)


@frappe.whitelist(methods=["POST"])
def reassign_suite(suite: str, agent_configuration: str | None = None) -> str:
	"""Assign a suite to another agent configuration."""
	frappe.has_permission("AI Eval Suite", "write", throw=True)
	return suites.reassign_suite(suite=suite, agent_configuration=agent_configuration)


@frappe.whitelist(methods=["POST"])
def create_suite(
	title: str,
	process_model: str | None = None,
	agent_configuration: str | None = None,
	eval_type: str = "Direct",
	description: str = "",
) -> str:
	"""Create a suite and assign it to an agent."""
	frappe.has_permission("AI Eval Suite", "create", throw=True)
	return suites.create_suite(
		title=title,
		process_model=process_model,
		agent_configuration=agent_configuration,
		eval_type=eval_type,
		description=description,
	)


@frappe.whitelist()
def get_run_comparison(run_a: str, run_b: str | None = None) -> dict:
	"""Compare two runs side by side."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return run_compare.get_run_comparison(run_a=run_a, run_b=run_b)


@frappe.whitelist()
def list_comparable_runs(run: str) -> list:
	"""Runs that can be compared with the given run."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return run_compare.list_comparable_runs(run=run)


@frappe.whitelist()
def list_response_feedback(
	rating: str = "Negative",
	status: str = "New",
	agent: str | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	limit: int = 100,
) -> list:
	"""Feedback rows with the context needed to judge them."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return feedback.list_response_feedback(
		rating=rating,
		status=status,
		agent=agent,
		from_date=from_date,
		to_date=to_date,
		limit=limit,
	)


@frappe.whitelist()
def get_feedback_overview(
	from_date: str | None = None, to_date: str | None = None, agent: str | None = None
) -> dict:
	"""Feedback counts for the triage dashboard."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return feedback.get_feedback_overview(from_date=from_date, to_date=to_date, agent=agent)


@frappe.whitelist()
def scheduled_results(
	days: int = 7,
	triggered_by: str = "",
	agent: str = "",
	failures_only: int = 0,
	limit: int = 60,
) -> dict:
	"""Recent eval runs across suites, newest first."""
	frappe.has_permission("AI Eval Suite", "read", throw=True)
	return overview.scheduled_results(
		days=days,
		triggered_by=triggered_by,
		agent=agent,
		failures_only=failures_only,
		limit=limit,
	)
