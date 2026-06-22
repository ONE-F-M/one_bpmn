import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from one_bpmn.one_bpmn.custom.custom_field.email_queue import get_email_queue_custom_fields


def execute():
	create_custom_fields(get_email_queue_custom_fields())
