import frappe
from frappe.query_builder import DocType


def execute():
	"""Name HD Ticket as the ticket DocType on change requests saved before hd_ticket became a Dynamic Link."""
	table = DocType("Process Change Request")
	(
		frappe.qb.update(table)
		.set(table.hd_ticket_doctype, "HD Ticket")
		.where(table.hd_ticket.isnotnull())
		.where(table.hd_ticket != "")
		.where(table.hd_ticket_doctype.isnull() | (table.hd_ticket_doctype == ""))
	).run()
