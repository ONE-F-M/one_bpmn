"""Processa Legacy Migration: process_model becomes to_model and the dropped fields' columns go."""

import frappe
from frappe.model.meta import trim_table
from frappe.model.utils.rename_field import rename_field

DOCTYPE = "Processa Legacy Migration"


def execute():
	frappe.reload_doc("processa_engine", "doctype", "legacy_migration_state_map")
	frappe.reload_doc("processa_engine", "doctype", "processa_legacy_migration")
	rename_field(DOCTYPE, "process_model", "to_model")
	trim_table(DOCTYPE, dry_run=False)
