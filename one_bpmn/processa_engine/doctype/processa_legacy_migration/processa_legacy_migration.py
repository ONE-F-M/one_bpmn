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
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from one_bpmn.processa_engine.doctype.legacy_migration_error_log.legacy_migration_error_log import LegacyMigrationErrorLog

		completed_at: DF.Datetime | None
		create_process_instance: DF.Check
		error_logs: DF.Table[LegacyMigrationErrorLog]
		failed_count: DF.Int
		migrated_count: DF.Int
		old_status: DF.Data
		process_model: DF.Link
		run_by: DF.Link | None
		started_at: DF.Datetime | None
		status: DF.Literal["Draft", "Queued", "Running", "Completed", "Failed"]
		target_doctype: DF.Link
		target_status: DF.Data
		target_task_id: DF.Data | None
		target_task_name: DF.Data | None
		total_records: DF.Int
		workflow_state: DF.Link | None
	# end: auto-generated types
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
