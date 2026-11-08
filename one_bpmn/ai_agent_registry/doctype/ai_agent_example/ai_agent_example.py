# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AIAgentExample(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		context_summary: DF.SmallText | None
		enabled: DF.Check
		expected_output: DF.Text | None
		input: DF.SmallText
		note: DF.SmallText | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		trajectory: DF.JSON | None
	# end: auto-generated types
	pass
