"""Move each site's records from the one_bpmn app name to processa before its first migrate on processa.

The deploy workflows call run() from the bench sites folder ahead of migrate. bench execute cannot be used: it
refuses a method from an app the site does not list as installed yet. A site already on processa is left alone.
"""

import json

import frappe
from frappe.query_builder import DocType
from frappe.utils import get_sites

OLD_APP = "one_bpmn"
NEW_APP = "processa"
OLD_PATCH_PREFIX = "one_bpmn.one_bpmn.patches."
RENAMED_PATCHES = {
	"wi_002204_error_log_ticket_triage_setup": "set_up_error_log_ticket_triage",
	"move_agent_chat_doctypes_to_one_bpmn": "move_agent_chat_doctypes_to_processa",
	"move_threat_intel_doctypes_to_one_bpmn": "move_threat_intel_doctypes_to_processa",
	"move_threat_assessment_doctypes_to_one_bpmn": "move_threat_assessment_doctypes_to_processa",
	"move_threat_feed_doctypes_to_one_bpmn": "move_threat_feed_doctypes_to_processa",
}
KEPT_NAME = "delete_one_bpmn_module"


def run():
	for site in get_sites():
		frappe.init(site=site)
		frappe.connect()
		try:
			if OLD_APP in json.loads(frappe.db.get_global("installed_apps") or "[]"):
				rename_app()
				frappe.db.commit()
				print(f"{site}: moved to {NEW_APP}")
		finally:
			frappe.destroy()


def rename_app():
	"""Rename the app in the site records. Direct updates only, since app hooks cannot load while one_bpmn is listed."""
	installed = json.loads(frappe.db.get_global("installed_apps") or "[]")
	default_value = DocType("DefaultValue")
	(
		frappe.qb.update(default_value)
		.set(default_value.defvalue, json.dumps([NEW_APP if app == OLD_APP else app for app in installed]))
		.where((default_value.parent == "__global") & (default_value.defkey == "installed_apps"))
	).run()
	for doctype in ("Installed Application", "Module Def"):
		for name in frappe.get_all(doctype, filters={"app_name": OLD_APP}, pluck="name"):
			frappe.db.set_value(doctype, name, "app_name", NEW_APP, update_modified=False)
	for row in frappe.get_all("Patch Log", filters={"patch": ["like", f"{OLD_PATCH_PREFIX}%"]}, fields=["name", "patch"]):
		frappe.db.set_value("Patch Log", row.name, "patch", patch_line(row.patch), update_modified=False)
	frappe.cache.hdel("defaults", "__global")
	frappe.cache.delete_value("app_hooks")


def patch_line(old: str) -> str:
	"""The patches.txt line that replaced ``old``, comment included, since Patch Log matches the whole line."""
	new = old.replace(OLD_PATCH_PREFIX, f"{NEW_APP}.patches.", 1)
	for before, after in RENAMED_PATCHES.items():
		new = new.replace(before, after)
	return new.replace(KEPT_NAME, "\0").replace(OLD_APP, NEW_APP).replace("\0", KEPT_NAME)
