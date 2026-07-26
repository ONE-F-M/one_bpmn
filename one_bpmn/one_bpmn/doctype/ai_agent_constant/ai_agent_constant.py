# Copyright (c) 2026, Kartik Sharma and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AIAgentConstant(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		constant_name: DF.Data
		constant_type: DF.Literal["String", "Integer", "Float", "Boolean"]
		constant_value: DF.Data
		description: DF.SmallText | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
	# end: auto-generated types

	pass
