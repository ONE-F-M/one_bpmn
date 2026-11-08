from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from one_bpmn.security.script_gate import SERVER_SCRIPT_APPROVAL_FIELDS


def execute():
	create_custom_fields(SERVER_SCRIPT_APPROVAL_FIELDS)
