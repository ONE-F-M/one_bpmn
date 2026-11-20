# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ScriptApprovalRequestItem(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		category: DF.Data | None
		item_name: DF.Data | None
		library: DF.Data | None
		lines: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
	# end: auto-generated types
	pass
