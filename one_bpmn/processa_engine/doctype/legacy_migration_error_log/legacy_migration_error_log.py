# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class LegacyMigrationErrorLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		document_doctype: DF.Link | None
		document_name: DF.DynamicLink | None
		error_message: DF.SmallText | None
		old_instance: DF.Link | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		reason: DF.Literal["", "Sub-process running", "Past a new step", "Waiting at removed step", "Already on new map", "No state mapping", "Replay stuck", "State not reached", "Timed out", "Error", "No longer open"]
		timestamp: DF.Datetime | None
	# end: auto-generated types
	pass
