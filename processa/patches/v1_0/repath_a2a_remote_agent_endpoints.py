import frappe

OLD_RPC = "one_bpmn.api.a2a_api.rpc"
NEW_RPC = "processa.api.a2a.rpc"


def execute():
	"""Point A2A Remote Agent endpoints that call a site's old one_bpmn rpc method at processa's."""
	for row in frappe.get_all(
		"A2A Remote Agent",
		filters={"endpoint_url": ["like", f"%{OLD_RPC}%"]},
		fields=["name", "endpoint_url"],
	):
		frappe.db.set_value(
			"A2A Remote Agent",
			row.name,
			"endpoint_url",
			row.endpoint_url.replace(OLD_RPC, NEW_RPC),
			update_modified=False,
		)
