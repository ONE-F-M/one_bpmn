import frappe
from frappe.utils import cint

from processa.ai_agent_security.code_checks.script_gate import script_hash

OLD_APP = "one_bpmn"
NEW_APP = "processa"
KEPT_NAME = "delete_one_bpmn_module"

STORED_PATHS = (
	("BPMN Connector Operation", "handler_path"),
	("BPMN Connector Field", "value_transform"),
	("BPMN Connector Field", "choices_source_path"),
)


def execute():
	"""Rename one_bpmn to processa in stored scripts, connector paths and maps, so the later repath patches find them."""
	for name in frappe.get_all("Server Script", filters={"script": ["like", f"%{OLD_APP}%"]}, pluck="name"):
		_rename_script(name)
	for doctype, fieldname in STORED_PATHS:
		for row in frappe.get_all(doctype, filters={fieldname: ["like", f"%{OLD_APP}%"]}, fields=["name", fieldname]):
			frappe.db.set_value(doctype, row.name, fieldname, renamed(row[fieldname]), update_modified=False)
	for row in frappe.get_all("BPMN Process Model", filters={"bpmn_xml": ["like", f"%{OLD_APP}%"]}, fields=["name", "bpmn_xml"]):
		frappe.db.set_value("BPMN Process Model", row.name, "bpmn_xml", renamed(row.bpmn_xml), update_modified=False)
	if frappe.db.get_single_value("Processa Settings", "connector_handler_app") == OLD_APP:
		frappe.db.set_single_value("Processa Settings", "connector_handler_app", NEW_APP)
	frappe.clear_cache()


def renamed(text: str) -> str:
	return text.replace(KEPT_NAME, "\0").replace(OLD_APP, NEW_APP).replace("\0", KEPT_NAME)


def _rename_script(name: str) -> None:
	script = frappe.db.get_value("Server Script", name, "script")
	values = {"script": renamed(script)}
	# The approval fields come from add_server_script_approval_fields, which runs after this patch on a site moving from one_bpmn.
	if frappe.db.has_column("Server Script", "processa_approved"):
		approved, approved_hash = frappe.db.get_value("Server Script", name, ["processa_approved", "processa_approved_hash"])
		if cint(approved) and approved_hash == script_hash(script):
			values["processa_approved_hash"] = script_hash(values["script"])
	frappe.db.set_value("Server Script", name, values, update_modified=False)
