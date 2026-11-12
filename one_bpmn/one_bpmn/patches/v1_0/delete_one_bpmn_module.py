import frappe

OLD_MODULE = "ONE BPMN"
NEW_MODULE = "Processa Engine"

MODULE_DOCTYPES = (
	"DocType",
	"Report",
	"Page",
	"Workspace",
	"Server Script",
	"Client Script",
	"Notification",
	"Custom Field",
	"Property Setter",
	"Print Format",
	"Web Form",
	"Dashboard Chart",
	"Number Card",
)


def execute():
	for doctype in MODULE_DOCTYPES:
		names = frappe.get_all(doctype, filters={"module": OLD_MODULE}, pluck="name")
		for name in names:
			frappe.db.set_value(doctype, name, "module", NEW_MODULE, update_modified=False)

	if frappe.db.exists("Module Def", OLD_MODULE):
		# Module Def is a system record, so the delete skips the permission check
		frappe.delete_doc("Module Def", OLD_MODULE, ignore_permissions=True)
