# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-002010: "sub agent" was the wrong word, so the field is renamed.

Entries in this list are INDEPENDENT agents — own configuration, own map,
own lifecycle, callable by anyone approved to call them, listable by any
number of other agents. None of that is what "sub agent" means, and the
same doctype already uses ``sub_prompts.sub_agent_id`` for the thing that
IS encapsulated (a prompt persona inside one agent). Two different
meanings for one phrase on one form is a trap for whoever reads it next.

So: ``allowed_sub_agents`` → ``allowed_delegates``, and the child doctype
``AI Agent Allowed Sub Agent`` → ``AI Agent Allowed Delegate``.

Runs BEFORE the model sync so the rename moves the existing table and
rows, rather than the sync creating an empty new doctype beside the old
one. Idempotent, and a no-op on any site that never saw the interim name
— which is every site except a bench that migrated this branch mid-flight.
"""

import frappe

OLD_DOCTYPE = "AI Agent Allowed Sub Agent"
NEW_DOCTYPE = "AI Agent Allowed Delegate"
OLD_FIELD = "allowed_sub_agents"
NEW_FIELD = "allowed_delegates"


def execute():
	_rename_doctype()
	_repoint_rows()


def _rename_doctype():
	if not frappe.db.exists("DocType", OLD_DOCTYPE):
		return

	if frappe.db.exists("DocType", NEW_DOCTYPE):
		# Both exist: a sync already created the new one. Move any rows across,
		# then drop the old table and its DocType record.
		if frappe.db.table_exists(OLD_DOCTYPE):
			old_table = f"tab{OLD_DOCTYPE}"
			new_table = f"tab{NEW_DOCTYPE}"
			columns = "`name`, `creation`, `modified`, `modified_by`, `owner`, `docstatus`, `idx`, `parent`, `parentfield`, `parenttype`, `agent_configuration`, `purpose`"
			frappe.db.sql_ddl(
				f"INSERT IGNORE INTO `{new_table}` ({columns}) SELECT {columns} FROM `{old_table}`"
			)
		frappe.delete_doc("DocType", OLD_DOCTYPE, force=True, ignore_permissions=True)
		return

	# The frappe.* wrapper does not accept ignore_permissions; the model
	# function does, and a patch runs without a user context.
	from frappe.model.rename_doc import rename_doc

	rename_doc(
		"DocType",
		OLD_DOCTYPE,
		NEW_DOCTYPE,
		force=True,
		ignore_permissions=True,
		show_alert=False,
		rebuild_search=False,
	)


def _repoint_rows():
	"""Child rows carry the parent's fieldname; the rename has to follow."""
	if not frappe.db.table_exists(NEW_DOCTYPE):
		return
	rows = frappe.get_all(
		NEW_DOCTYPE, filters={"parentfield": OLD_FIELD, "parenttype": "AI Agent Configuration"}, pluck="name"
	)
	for name in rows:
		frappe.db.set_value(NEW_DOCTYPE, name, "parentfield", NEW_FIELD, update_modified=False)
	if rows:
		print(f"Repointed {len(rows)} delegate row(s) from {OLD_FIELD} to {NEW_FIELD}")

	# Drop the stale column on the parent if a sync already added the new one.
	if frappe.db.has_column("AI Agent Configuration", OLD_FIELD):
		frappe.db.sql_ddl(f"ALTER TABLE `tabAI Agent Configuration` DROP COLUMN `{OLD_FIELD}`")
