# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-002010: the delegation toggle changed meaning, so its old column goes.

``delegates_to_agents`` meant "this agent hands work to others, show me the
delegation fields". It has been replaced by ``restrict_delegates``, which
means the opposite kind of thing: "narrow delegation to a named few".
Exposure is now what grants an agent delegated work, because the tools
drawn on a map already decide who an agent calls — a second copy of that
list on the configuration was bookkeeping, not control.

The values are deliberately NOT carried over: True under the old field
meant "delegates", True under the new one means "restricted", so migrating
them would silently lock agents down. Dropping the column leaves every
agent unrestricted, which matches the new default.

Never released outside a local bench, so this only tidies up a bench that
migrated this branch mid-flight.
"""

import frappe

OLD_FIELD = "delegates_to_agents"


def execute():
	if frappe.db.has_column("AI Agent Configuration", OLD_FIELD):
		frappe.db.sql_ddl(f"ALTER TABLE `tabAI Agent Configuration` DROP COLUMN `{OLD_FIELD}`")
		print(f"Dropped stale AI Agent Configuration.{OLD_FIELD}")
	frappe.clear_cache(doctype="AI Agent Configuration")
