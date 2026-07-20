# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
#
# Processa Legacy Migration is driven by the "Processa Legacy Migration - v2"
# BPMN process: creating a record triggers the process (After Insert), which sets
# the workflow_state, waits at the "Review" user task, and — when the owner takes
# the "Run Migration" action — runs the migration via the "Action Processa Legacy
# Migration" Server Script, then marks the record Completed.
#
# All actioning therefore lives in that Server Script / the BPMN diagram, not
# here: this controller only validates the configuration while it is editable.

import frappe
from frappe import _
from frappe.model.document import Document


class ProcessaLegacyMigration(Document):
	"""Configuration + progress record for a legacy-document migration.

	The migration itself is performed by the BPMN process; this controller only
	validates the configuration while the record is still in Draft.
	"""

	def validate(self):
		if self.status not in ("Draft", ""):
			return

		if not self.process_model:
			frappe.throw(_("Process Model is required."))
		if not self.target_doctype:
			frappe.throw(_("Target DocType is required."))
		if not self.old_status:
			frappe.throw(_("Old Status is required."))
		if not self.target_status:
			frappe.throw(_("Target Status is required."))

		if self.old_status == self.target_status:
			frappe.throw(_("Old Status and Target Status cannot be the same."))
