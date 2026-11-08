# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
#
# Processa Legacy Migration is driven by the "Processa Legacy Migration - v2"
# BPMN process: creating a record triggers the process (After Insert), which sets
# the workflow_state, waits at the "Review" user task, and — when the owner takes
# the "Run Migration" action — runs the migration via the "Action Processa Legacy
# Migration" Server Script, then marks the record Completed.

from frappe.model.document import Document


class ProcessaLegacyMigration(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from one_bpmn.processa_engine.doctype.legacy_migration_error_log.legacy_migration_error_log import (
			LegacyMigrationErrorLog,
		)
		from one_bpmn.processa_engine.doctype.legacy_migration_state_map.legacy_migration_state_map import (
			LegacyMigrationStateMap,
		)

		batches_done: DF.Int
		completed_at: DF.Datetime | None
		error_logs: DF.Table[LegacyMigrationErrorLog]
		failed_count: DF.Int
		from_model: DF.Link
		migrated_count: DF.Int
		run_by: DF.Link | None
		started_at: DF.Datetime | None
		state_map: DF.Table[LegacyMigrationStateMap]
		status: DF.Literal["Draft", "Queued", "Running", "Completed", "Failed"]
		target_doctype: DF.Link
		to_model: DF.Link
		total_batches: DF.Int
		total_records: DF.Int
		workflow_state: DF.Link | None
	# end: auto-generated types
	"""Configuration and progress record for moving open records from an old process map to a new one."""
