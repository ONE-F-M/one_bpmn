# Copyright (c) 2026, one-fm and contributors
# WI-001357 (3-04): registry-tool applicability toggling for the AI Task
# Selector configuration UI.

import frappe
from frappe import _


@frappe.whitelist()
def list_registry_tools(process_model: str) -> list:
	"""
	Enabled AI Agent Tool records with their applicability to one process,
	for the Registry Tools section of the selector configuration panel.
	"""
	frappe.has_permission("AI Agent Tool", "read", throw=True)

	tools = frappe.get_list(
		"AI Agent Tool",
		filters={"is_active": 1},
		fields=["name", "tool_name", "description", "handler_type"],
		order_by="tool_name asc",
	)
	for tool in tools:
		scoped = frappe.get_all(
			"AI Agent Tool Process",
			filters={"parent": tool.name, "parenttype": "AI Agent Tool"},
			pluck="process_model",
		)
		tool["is_global"] = not scoped
		tool["applies_here"] = not scoped or process_model in scoped
	return tools


@frappe.whitelist()
def set_tool_process_applicability(tool: str, process_model: str, applicable: int) -> dict:
	"""
	Include or exclude one AI Agent Tool for one BPMN Process Model by
	adding/removing the process from the tool's applicable_processes.

	Global tools (empty applicable_processes) stay global — scoping one is
	an explicit decision made on the tool record itself, not a side effect
	of a checkbox, so this call refuses to narrow a global tool.
	"""
	doc = frappe.get_doc("AI Agent Tool", tool)
	doc.check_permission("write")

	scoped = [row.process_model for row in (doc.applicable_processes or [])]
	if not scoped:
		frappe.throw(
			_(
				"'{0}' is a global tool (available to every process). "
				"To scope it, edit the tool record and add explicit processes."
			).format(doc.tool_name)
		)

	if frappe.utils.cint(applicable):
		if process_model not in scoped:
			doc.append("applicable_processes", {"process_model": process_model})
	else:
		doc.applicable_processes = [
			row for row in doc.applicable_processes if row.process_model != process_model
		]
		if not doc.applicable_processes:
			frappe.throw(
				_(
					"Removing the last process would make '{0}' global. "
					"Do that on the tool record itself if intended."
				).format(doc.tool_name)
			)

	doc.save()
	return {"tool": doc.name, "applies_here": frappe.utils.cint(applicable) == 1}
