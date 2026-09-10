# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AIEvalExpectedToolCall(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		argument: DF.Data | None
		call_order: DF.Int
		expected_value: DF.SmallText | None
		matcher: DF.Literal["equals", "regex", "contains"]
		tool_name: DF.Data
	# end: auto-generated types
	pass
