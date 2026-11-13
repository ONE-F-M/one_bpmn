# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class AISkillResource(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		resource_name: DF.Data
		resource_type: DF.Literal["Script", "Reference", "Asset", "Template"]
		resource_value: DF.Text
	# end: auto-generated types
	pass
