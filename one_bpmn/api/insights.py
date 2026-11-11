"""Insights HTTP endpoints. Each checks the role, then calls ai_agent_observability/reports."""
from __future__ import annotations

import frappe

from one_bpmn.ai_agent_observability.reports import (
	allocation,
	errors,
	performance,
	runs,
	usage,
	work_item_cost,
)


@frappe.whitelist()
def get_agent_overview(
	days: int = None,
	from_date: str = None,
	to_date: str = None,
	agent_configuration: str = None,
	model: str = None,
	provider: str = None,
	process_model: str = None,
	origin: str = "production",
) -> dict:
	"""Return the overview tiles for the from_date/to_date range and filters, with the previous period."""
	frappe.only_for("System Manager")
	return usage.get_agent_overview(
		days=days,
		from_date=from_date,
		to_date=to_date,
		agent_configuration=agent_configuration,
		model=model,
		provider=provider,
		process_model=process_model,
		origin=origin,
	)


@frappe.whitelist()
def get_cost_token_report(
	from_date: str = None,
	to_date: str = None,
	model: str = None,
	provider: str = None,
	process_model: str = None,
	agent_configuration: str = None,
	origin: str = "production",
	group_by: str = "model",
) -> dict:
	"""Get cost token report."""
	frappe.only_for("System Manager")
	return usage.get_cost_token_report(
		from_date=from_date,
		to_date=to_date,
		model=model,
		provider=provider,
		process_model=process_model,
		agent_configuration=agent_configuration,
		origin=origin,
		group_by=group_by,
	)


@frappe.whitelist()
def export_cost_token_report(
	from_date: str = None,
	to_date: str = None,
	model: str = None,
	provider: str = None,
	process_model: str = None,
	agent_configuration: str = None,
	origin: str = "production",
	group_by: str = "model",
	fmt: str = "csv",
):
	"""Download the cost/token report's daily rows as CSV or XLSX."""
	frappe.only_for("System Manager")
	return usage.export_cost_token_report(
		from_date=from_date,
		to_date=to_date,
		model=model,
		provider=provider,
		process_model=process_model,
		agent_configuration=agent_configuration,
		origin=origin,
		group_by=group_by,
		fmt=fmt,
	)


@frappe.whitelist()
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
	"""Error rate over time, errors by code, one issue per code and element, and a summary."""
	frappe.only_for("System Manager")
	return errors.get_error_report(
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


@frappe.whitelist()
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
	frappe.only_for("System Manager")
	return errors.get_issue_runs(
		key=key,
		from_date=from_date,
		to_date=to_date,
		origin=origin,
		limit=limit,
		offset=offset,
		group_by=group_by,
	)


@frappe.whitelist()
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
	frappe.only_for("System Manager")
	return errors.export_error_report(
		from_date=from_date,
		to_date=to_date,
		model=model,
		error_code=error_code,
		process_model=process_model,
		agent_configuration=agent_configuration,
		origin=origin,
		group_by=group_by,
		provider=provider,
		fmt=fmt,
	)


@frappe.whitelist()
def get_performance_report(
	from_date: str = None,
	to_date: str = None,
	model: str = None,
	bpmn_id: str = None,
	process_model: str = None,
	agent_configuration: str = None,
	origin: str = "production",
	group_by: str = "model",
	provider: str | None = None,
) -> dict:
	"""Get performance report."""
	frappe.only_for("System Manager")
	return performance.get_performance_report(
		from_date=from_date,
		to_date=to_date,
		model=model,
		bpmn_id=bpmn_id,
		process_model=process_model,
		agent_configuration=agent_configuration,
		origin=origin,
		group_by=group_by,
		provider=provider,
	)


@frappe.whitelist()
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
	frappe.only_for("System Manager")
	return performance.export_latency_report(
		from_date=from_date,
		to_date=to_date,
		model=model,
		process_model=process_model,
		agent_configuration=agent_configuration,
		origin=origin,
		group_by=group_by,
		provider=provider,
		fmt=fmt,
	)


@frappe.whitelist()
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
	"""Time split and costliest step labels, for all counted runs or one element."""
	frappe.only_for("System Manager")
	return performance.get_step_latency_report(
		from_date=from_date,
		to_date=to_date,
		origin=origin,
		model=model,
		provider=provider,
		process_model=process_model,
		agent_configuration=agent_configuration,
		key=key,
		group_by=group_by,
		limit=limit,
	)


@frappe.whitelist()
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
	"""Slowest measured runs of one element, paged by limit and offset."""
	frappe.only_for("System Manager")
	return performance.get_element_runs(
		key=key,
		from_date=from_date,
		to_date=to_date,
		origin=origin,
		model=model,
		provider=provider,
		process_model=process_model,
		agent_configuration=agent_configuration,
		group_by=group_by,
		min_agent_latency_ms=min_agent_latency_ms,
		limit=limit,
		offset=offset,
	)


@frappe.whitelist()
def get_run_tree(run_name: str) -> dict:
	"""Get run tree."""
	frappe.only_for("System Manager")
	return runs.get_run_tree(run_name=run_name)


@frappe.whitelist()
def get_recent_runs(
	model: str = None,
	bpmn_id: str = None,
	agent_configuration: str = None,
	status: str = "Success",
	limit: int = 10,
) -> list:
	"""Get recent runs."""
	frappe.only_for("System Manager")
	return runs.get_recent_runs(
		model=model,
		bpmn_id=bpmn_id,
		agent_configuration=agent_configuration,
		status=status,
		limit=limit,
	)


@frappe.whitelist()
def get_cost_allocation(
	from_date: str = None,
	to_date: str = None,
	axis: str = "process_owner",
	group_by: str = None,
	origin: str = "production",
	process_model: str = None,
) -> dict:
	"""Get cost allocation."""
	frappe.only_for("System Manager")
	return allocation.get_cost_allocation(
		from_date=from_date,
		to_date=to_date,
		axis=axis,
		group_by=group_by,
		origin=origin,
		process_model=process_model,
	)


@frappe.whitelist()
def export_cost_allocation(
	from_date: str = None,
	to_date: str = None,
	axis: str = "process_owner",
	group_by: str = None,
	origin: str = "production",
	process_model: str = None,
	fmt: str = "xlsx",
) -> dict:
	"""The cost allocation as an XLSX or CSV file, base64 encoded, with its filename."""
	frappe.only_for("System Manager")
	return allocation.export_cost_allocation(
		from_date=from_date,
		to_date=to_date,
		axis=axis,
		group_by=group_by,
		origin=origin,
		process_model=process_model,
		fmt=fmt,
	)


@frappe.whitelist()
def search_orchestrator_work_items(query: str | None = None) -> list:
	"""Search orchestrator work items."""
	frappe.only_for("System Manager")
	return work_item_cost.search_orchestrator_work_items(query=query)


@frappe.whitelist()
def get_work_item_delegation_cost(work_item_name: str) -> dict:
	"""Get work item delegation cost."""
	frappe.only_for("System Manager")
	return work_item_cost.get_work_item_delegation_cost(work_item_name=work_item_name)


@frappe.whitelist()
def list_runs(
	agent_configuration: str = None,
	status: str = None,
	origin: str = "production",
	user: str = None,
	model: str = None,
	instance: str = None,
	from_date: str = None,
	to_date: str = None,
	errors_only: int = 0,
	search: str = None,
	order: str = "newest",
	start: int = 0,
	page_length: int = 25,
) -> dict:
	"""A page of top-level runs for /processa/runs, with the six tile numbers for the same filter."""
	frappe.only_for("System Manager")
	return runs.list_runs(
		agent_configuration=agent_configuration,
		status=status,
		origin=origin,
		user=user,
		model=model,
		instance=instance,
		from_date=from_date,
		to_date=to_date,
		errors_only=errors_only,
		search=search,
		order=order,
		start=start,
		page_length=page_length,
	)


@frappe.whitelist()
def run_filter_options(origin: str = "production") -> dict:
	"""The agents, people and models that actually have runs, for the filters."""
	frappe.only_for("System Manager")
	return runs.run_filter_options(origin=origin)


@frappe.whitelist()
def get_turn_steps(run_name: str) -> dict:
	"""Get turn steps."""
	frappe.only_for("System Manager")
	return runs.get_turn_steps(run_name=run_name)


@frappe.whitelist()
def get_run_detail(run_name: str) -> dict:
	"""Get run detail."""
	frappe.only_for("System Manager")
	return runs.get_run_detail(run_name=run_name)
