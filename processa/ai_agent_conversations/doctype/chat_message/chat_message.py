# Copyright (c) 2025, Kartik Sharma and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class ChatMessage(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		client_message_id: DF.Data | None
		conversation: DF.Link | None
		file: DF.Attach | None
		linked_message: DF.Link | None
		message_type: DF.Literal["User", "Bot", "Tool"]
		metadata: DF.Code | None
		receiver: DF.Data | None
		sender: DF.Data | None
		text: DF.SmallText | None
		tool_call_id: DF.Data | None
		tool_calls: DF.Code | None
	# end: auto-generated types
	pass
