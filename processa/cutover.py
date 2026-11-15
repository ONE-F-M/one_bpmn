"""Move a site's records from the one_bpmn app name to processa before its first migrate on processa.

Runs from the deploy workflows through bench execute, ahead of migrate, because migrate cannot load hooks for an
installed app whose package is gone. A site already on processa is left as it is.
"""

import json

import frappe

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


def rename_app():
	installed = json.loads(frappe.db.get_global("installed_apps") or "[]")
	if OLD_APP in installed:
		frappe.db.set_global("installed_apps", json.dumps([NEW_APP if app == OLD_APP else app for app in installed]))
	for name in frappe.get_all("Installed Application", filters={"app_name": OLD_APP}, pluck="name"):
		frappe.db.set_value("Installed Application", name, "app_name", NEW_APP)
	for name in frappe.get_all("Module Def", filters={"app_name": OLD_APP}, pluck="name"):
		frappe.db.set_value("Module Def", name, "app_name", NEW_APP)
	rows = frappe.get_all("Patch Log", filters={"patch": ["like", f"{OLD_PATCH_PREFIX}%"]}, fields=["name", "patch"])
	for row in rows:
		frappe.db.set_value("Patch Log", row.name, "patch", patch_line(row.patch), update_modified=False)
	frappe.clear_cache()
	print(f"processa cutover: {len(rows)} Patch Log rows rewritten")


def patch_line(old: str) -> str:
	"""The patches.txt line that replaced ``old``, comment included, since Patch Log matches the whole line."""
	new = old.replace(OLD_PATCH_PREFIX, f"{NEW_APP}.patches.", 1)
	for before, after in RENAMED_PATCHES.items():
		new = new.replace(before, after)
	return new.replace(KEPT_NAME, "\0").replace(OLD_APP, NEW_APP).replace("\0", KEPT_NAME)
