# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
#
# Processa Legacy Migration is a self-hosted Processa (BPMN) process: this record
# is only the *context document* holding the migration configuration and progress.
# All actioning — "Preview Records" and "Run Migration" — lives in the BPMN model
# "Processa Legacy Migration V1" as user-task actions backed by the Server Scripts
# "Legacy Migration – Preview Records" and "Legacy Migration – Run Migration".
# Start the process from Processa (start_process) against this document; there is
# deliberately no backend action code or form button left here.

import frappe
from frappe import _
from frappe.model.document import Document


class ProcessaLegacyMigration(Document):
	"""Configuration + progress record for a legacy-document migration.

	The migration itself is driven by the BPMN process; this controller only
	validates the configuration while the record is still editable.
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
