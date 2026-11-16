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
	"""Rename the app in the site records. Query builder only: get_all loads every app's hooks, and one_bpmn's are gone."""
	installed = json.loads(frappe.db.get_global("installed_apps") or "[]")
	default_value = DocType("DefaultValue")
	(
		frappe.qb.update(default_value)
		.set(default_value.defvalue, json.dumps([NEW_APP if app == OLD_APP else app for app in installed]))
		.where((default_value.parent == "__global") & (default_value.defkey == "installed_apps"))
	).run()
	for doctype in ("Installed Application", "Module Def"):
		table = DocType(doctype)
		frappe.qb.update(table).set(table.app_name, NEW_APP).where(table.app_name == OLD_APP).run()
	patch_log = DocType("Patch Log")
	rows = frappe.qb.from_(patch_log).select(patch_log.name, patch_log.patch).where(patch_log.patch.like(f"{OLD_PATCH_PREFIX}%")).run()
	for name, patch in rows:
		frappe.qb.update(patch_log).set(patch_log.patch, patch_line(patch)).where(patch_log.name == name).run()
	frappe.cache.hdel("defaults", "__global")
	# Frappe v16 keeps the global defaults, installed_apps included, under this key instead.
	frappe.cache.delete_value("defaults::__global")
	frappe.cache.delete_value(["app_hooks", "app_modules", "installed_app_modules"])


def patch_line(old: str) -> str:
	"""The patches.txt line that replaced ``old``, comment included, since Patch Log matches the whole line."""
	new = old.replace(OLD_PATCH_PREFIX, f"{NEW_APP}.patches.", 1)
	for before, after in RENAMED_PATCHES.items():
		new = new.replace(before, after)
	return new.replace(KEPT_NAME, "\0").replace(OLD_APP, NEW_APP).replace("\0", KEPT_NAME)
