# Copyright (c) 2026, one-fm and contributors
"""Process map endpoints for the process list and the editor; the work is in processa_engine.maps."""

import frappe

from processa.processa_engine.agent_runtime import dry_run
from processa.processa_engine.maps import listing, readiness, saving


@frappe.whitelist()
def save_process_model(
	model_name: str, xml_content: str, process: str = None, description: str = None
) -> dict:
	"""Save or update a BPMN process model; returns its name, title, version and is_active."""
	return saving.save_model(model_name, xml_content, process, description)


@frappe.whitelist()
def import_bpmn(
	xml_content: str,
	title: str = None,
	process: str = None,
) -> dict:
	"""Import BPMN XML as a new model, or update the model with the same process_id, then compile it."""
	return saving.import_model(xml_content, title, process)


@frappe.whitelist()
def validate_bpmn_readiness(xml_content: str, model_name: str = None) -> dict:
	"""Check everything the map refers to against this site; returns the readiness categories and totals."""
	return readiness.check_readiness(xml_content, model_name)


@frappe.whitelist(methods=["POST"])
def update_call_activity_references(references: str) -> dict:
	"""Point Call Activities in other maps at the model being deployed; returns the updated count."""
	frappe.only_for(["System Manager", "Process Owner"])
	return saving.retarget_call_activities(references)


@frappe.whitelist()
def get_process_model(name: str) -> dict:
	"""Get a process model by name, with its XML ready for the viewer."""
	return listing.model_details(name)


@frappe.whitelist()
def resolve_process_model_by_id(process_id: str) -> dict:
	"""The BPMN Process Model that owns a process_id, or an empty dict."""
	return listing.find_model_by_process_id(process_id)


@frappe.whitelist()
def list_processes() -> list:
	"""List the Process records the user can read, with diagram counts and status."""
	return listing.processes_with_status()


@frappe.whitelist()
def get_process_diagrams(process: str) -> dict:
	"""Get a Process and all its diagrams."""
	return listing.process_diagrams(process)


@frappe.whitelist()
def delete_diagram(name: str) -> dict:
	"""Delete a BPMN process model diagram."""
	return saving.delete_model(name)


@frappe.whitelist()
def rename_process_model(name: str, new_title: str) -> dict:
	"""Rename a BPMN Process Model without running its validate hooks."""
	return saving.rename_model(name, new_title)


@frappe.whitelist(methods=["POST"])
def preview_ai_task(
	model_name: str,
	bpmn_xml: str,
	bpmn_id: str,
	form: str | None = None,
	sample_variables: str | None = None,
	sample_message: str | None = None,
) -> dict:
	"""The prompts and tools an AI Agent Task would send, from the diagram as it stands in the editor."""
	frappe.has_permission("BPMN Process Model", "write", model_name, throw=True)
	return dry_run.preview_task(bpmn_xml, bpmn_id, form, sample_variables, sample_message or "")


@frappe.whitelist(methods=["POST"])
def dry_run_ai_task(
	model_name: str,
	bpmn_xml: str,
	bpmn_id: str,
	form: str | None = None,
	sample_variables: str | None = None,
	sample_message: str | None = None,
	sample_results: str | None = None,
) -> dict:
	"""Run one sample turn of an AI Agent Task with tools that return sample results; nothing is saved."""
	frappe.has_permission("BPMN Process Model", "write", model_name, throw=True)
	return dry_run.dry_run_task(
		bpmn_xml, bpmn_id, form, sample_variables, sample_message or "", sample_results
	)
