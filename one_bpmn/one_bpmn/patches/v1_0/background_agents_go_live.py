"""
WI-001652: Background agents go Live on save (apply_background_lifecycle).

Re-save every enabled Background-type AI Agent Configuration so the new
controller rule runs on the existing provider grants (Platform Prompt
Engineer, the WI-001650 backfills). The deployment gate now requires linked
agents to be Live — without this, the AI Agent Creation Process itself could
not be recompiled. Idempotent.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "AI Agent Configuration"):
		return
	for name in frappe.get_all(
		"AI Agent Configuration", filters={"agent_type": "Background"}, pluck="name"
	):
		try:
			doc = frappe.get_doc("AI Agent Configuration", name)
			doc.flags.ignore_permissions = True
			doc.save()
		except Exception:
			frappe.log_error(
				title=f"WI-001652 background go-live failed: {name}",
				message=frappe.get_traceback(),
			)
	frappe.db.commit()
