# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class LegacyMigrationStateMap(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		new_state: DF.Link
		old_state: DF.Link
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		record_count: DF.Int
	# end: auto-generated types
	pass
