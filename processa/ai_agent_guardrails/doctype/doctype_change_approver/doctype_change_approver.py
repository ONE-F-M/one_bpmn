# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""One person or role eligible to approve a Doctype Change Request."""

from frappe.model.document import Document


class DoctypeChangeApprover(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		approver: DF.Link | None
		approver_role: DF.Link | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		process_name: DF.Link | None
		source: DF.Literal["Listed", "Fallback"]
	# end: auto-generated types
	pass
