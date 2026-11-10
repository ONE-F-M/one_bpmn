import frappe

# Old dotted path to new, for the Docu, notification and Server Script endpoint modules that were renamed.
RENAMED_MODULES = {
	"one_bpmn.api.docu_api": "one_bpmn.api.docu",
	"one_bpmn.api.notification_api": "one_bpmn.api.notifications",
	"one_bpmn.api.server_script_api": "one_bpmn.api.server_scripts",
}


def execute():
	"""Point Server Script imports at the renamed endpoint modules. Approval fields are left for a normal review."""
	for old in RENAMED_MODULES:
		for name in frappe.get_all("Server Script", filters={"script": ["like", f"%{old}%"]}, pluck="name"):
			script = frappe.db.get_value("Server Script", name, "script")
			for old_path, new_path in RENAMED_MODULES.items():
				script = script.replace(old_path, new_path)
			frappe.db.set_value("Server Script", name, "script", script, update_modified=False)
	frappe.clear_cache(doctype="Server Script")
