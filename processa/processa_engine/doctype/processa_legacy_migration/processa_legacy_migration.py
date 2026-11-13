# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from processa.processa_engine.legacy_migration import validate_setup


class ProcessaLegacyMigration(Document):
	"""Configuration and progress record for moving open records from an old process map to a new one."""

	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from processa.processa_engine.doctype.legacy_migration_error_log.legacy_migration_error_log import (
			LegacyMigrationErrorLog,
		)
		from processa.processa_engine.doctype.legacy_migration_state_map.legacy_migration_state_map import (
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

	def validate(self):
		if self.status not in ("Draft", "Failed"):
			return
		# The PLM's own map saves it to move its workflow state; a setup change is still checked.
		if frappe.flags.bpmn_engine_action:
			if self._setup_unchanged():
				return
		# A blank map or DocType is left to Frappe's mandatory check, which runs after validate.
		if not all((self.from_model, self.to_model, self.target_doctype)):
			return
		validate_setup(self)

	def _setup_unchanged(self) -> bool:
		before = self.get_doc_before_save()
		if not before:
			return False

		def pairs(doc):
			return [(d.old_state, d.new_state) for d in doc.state_map]

		fields = ("from_model", "to_model", "target_doctype")
		if any(before.get(f) != self.get(f) for f in fields):
			return False
		return pairs(before) == pairs(self)
