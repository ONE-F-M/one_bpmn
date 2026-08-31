# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Remove what the AI Provider / AI Model consolidation left behind.

Deleting a DocType removes the definition, not the table. So after credentials
and the rate card folded into AI Provider and AI Model, two orphan tables stayed
on every site holding the old rows — including, in the case of credentials, API
keys. A secret nobody can see and nobody will rotate is worse than one in plain
view, because it is still valid and nothing will ever prompt anyone to change it.

Frappe also never drops a column, so `tabAI Provider` still carries the fields it
had under its former name: `provider_name` (superseded by `provider`, which is
now the record name) and `default_model` (a model is chosen per agent, not per
provider). Both read as live schema to anyone inspecting the table.

SAFE TO RUN ONLY AFTER THE DATA HAS MOVED
-----------------------------------------
This refuses to drop anything until it can see the destination populated: the
new AI Provider table has to exist and hold at least one row, and the same for
AI Model. If the consolidation patch has not run, or ran and produced nothing,
this leaves everything alone rather than destroying the only remaining copy.

The secrets are removed from `__Auth` too. They are keyed by doctype and name,
so the legacy rows survive the table drop and would otherwise sit there for good.
"""

import frappe

LEGACY_TABLES = ("AI Provider Credentials", "AI Model Pricing")

# Columns on tabAI Provider that belong to the doctype's former shape.
STALE_COLUMNS = ("provider_name", "default_model")


def _has_table(doctype: str) -> bool:
	return bool(frappe.db.sql("SHOW TABLES LIKE %s", f"tab{doctype}"))


def _destination_is_populated() -> bool:
	"""Has the consolidation actually landed on this site?"""
	for doctype in ("AI Provider", "AI Model"):
		if not frappe.db.exists("DocType", doctype) or not _has_table(doctype):
			return False
		if not frappe.db.sql(f"SELECT 1 FROM `tab{doctype}` LIMIT 1"):
			return False
	return True


def execute():
	if not _destination_is_populated():
		frappe.log_error(
			title="Legacy AI tables kept",
			message=(
				"AI Provider or AI Model is missing or empty, so the legacy "
				"credential and pricing tables were left in place. Run the "
				"consolidation patch first."
			),
		)
		return

	for doctype in LEGACY_TABLES:
		# A DocType that still exists is a live one, not a leftover — somebody
		# has reinstated it, and dropping its table would break them.
		if frappe.db.exists("DocType", doctype):
			continue

		if _has_table(doctype):
			# DDL goes through sql_ddl; plain sql refuses it as an implicit commit.
			frappe.db.sql_ddl(f"DROP TABLE `tab{doctype}`")

		# Kept out of the branch above on purpose. Secrets live in __Auth, keyed
		# by doctype and name, so they outlive the table — and a site that had
		# already dropped the table by hand would otherwise keep its orphaned
		# API keys for good. __Auth is not a DocType table, so this is plain SQL
		# rather than frappe.db.delete, which would look for `tab__Auth`.
		frappe.db.sql("DELETE FROM `__Auth` WHERE doctype = %s", (doctype,))
		frappe.db.commit()

	for column in STALE_COLUMNS:
		if frappe.db.has_column("AI Provider", column):
			frappe.db.sql_ddl(f"ALTER TABLE `tabAI Provider` DROP COLUMN `{column}`")

	frappe.db.commit()
	frappe.clear_cache()
