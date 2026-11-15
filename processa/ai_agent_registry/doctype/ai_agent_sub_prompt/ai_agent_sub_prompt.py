# Copyright (c) 2026, Kartik Sharma and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AIAgentSubPrompt(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		prompt_text: DF.Code | None
		sub_agent_id: DF.Data
		sub_agent_name: DF.Data | None
		temperature: DF.Float
	# end: auto-generated types

	pass
