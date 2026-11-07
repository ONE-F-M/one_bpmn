# Copyright (c) 2026, one-fm and contributors
"""Deploy, disable, activate and deactivate a BPMN Process Model; the work is in processa_engine.compiler."""

import frappe
from frappe import _

from one_bpmn.processa_engine.compiler.compile_step import compile_model
from one_bpmn.processa_engine.compiler.lifecycle import (
	activate_non_executable,
	deactivate_non_executable,
	disable_model,
)


@frappe.whitelist()
def compile_process_model(model_name: str) -> dict:
	"""Compile and deploy a process model; returns success, model, version, subprocess_count and any warnings."""
	if not model_name:
		frappe.throw(_("Model name is required"))

	model = frappe.get_doc("BPMN Process Model", model_name)
	model.check_permission("write")
	return compile_model(model)


@frappe.whitelist()
def disable_process_model(model_name: str) -> dict:
	"""Disable a deployed process model; running instances continue. Returns the running instance count."""
	if not model_name:
		frappe.throw(_("Model name is required"))

	model = frappe.get_doc("BPMN Process Model", model_name)
	model.check_permission("write")
	return disable_model(model)


@frappe.whitelist(methods=["POST"])
def activate_non_executable_model(model_name: str) -> dict:
	"""Mark a non-executable process model Active; saving it deactivates its siblings."""
	model = frappe.get_doc("BPMN Process Model", model_name)
	model.check_permission("write")
	return activate_non_executable(model)


@frappe.whitelist(methods=["POST"])
def deactivate_non_executable_model(model_name: str) -> dict:
	"""Mark a non-executable process model Inactive."""
	model = frappe.get_doc("BPMN Process Model", model_name)
	model.check_permission("write")
	return deactivate_non_executable(model)
