# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AIEvalResult(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		actual_output: DF.LongText | None
		assertion_results: DF.JSON | None
		cost: DF.Currency
		error_message: DF.LongText | None
		eval_case: DF.Link
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		status: DF.Literal["Passed", "Failed", "Error"]
		tokens_used: DF.Int
	# end: auto-generated types
	pass
