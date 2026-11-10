# Copyright (c) 2025, Kartik Sharma and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class ThreatKeyword(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		date_added: DF.Date
		is_active: DF.Check
		keyword: DF.Data
		language: DF.Literal["English", "Arabic"]
		source_type: DF.Literal["Manual", "AI Generated"]
		usage_count: DF.Int
	# end: auto-generated types
	pass