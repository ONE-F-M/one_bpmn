# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class AIAgentTool(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		description: DF.SmallText | None
		json_schema: DF.Code | None
		script: DF.Link | None
		tool_name: DF.Data
	# end: auto-generated types
	pass
