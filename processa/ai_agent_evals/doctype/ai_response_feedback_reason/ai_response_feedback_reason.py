# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AIResponseFeedbackReason(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		reason: DF.Literal[
			"Inaccurate", "Incomplete", "Not relevant", "Didn't follow instructions", "Wrong tone"
		]
	# end: auto-generated types
	pass
