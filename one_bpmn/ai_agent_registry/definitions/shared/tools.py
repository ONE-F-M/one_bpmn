"""Tool functions the Server Scripts of more than one agent call."""

import json

import frappe

from one_bpmn.ai_agent_registry.definitions.shared.helpers import tool_envelope


@tool_envelope(
	"Logix Tool - get_doctype_fields",
	lambda doctype: json.dumps({"error": f"Failed to fetch fields for DocType '{doctype}'."}),
)
def get_doctype_fields(doctype: str) -> str:
	"""The fieldname, fieldtype, label and reqd of each data field on a DocType, as JSON."""
	if not frappe.db.exists("DocType", doctype):
		return json.dumps({"error": f"DocType '{doctype}' does not exist."})

	meta = frappe.get_meta(doctype)
	fields = [
		{
			"fieldname": f.fieldname,
			"fieldtype": f.fieldtype,
			"label": f.label or f.fieldname,
			"reqd": bool(f.reqd),
		}
		for f in meta.fields
		if f.fieldtype not in ("Section Break", "Column Break", "HTML", "Heading")
	]
	return json.dumps(fields)
