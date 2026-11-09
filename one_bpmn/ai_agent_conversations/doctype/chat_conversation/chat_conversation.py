# Copyright (c) 2025, Kartik Sharma and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class ChatConversation(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from one_bpmn.ai_agent_conversations.doctype.chat_participant.chat_participant import ChatParticipant

		agent_mode: DF.Data | None
		is_eval: DF.Check
		last_message: DF.Link | None
		last_updated: DF.Datetime | None
		participants: DF.Table[ChatParticipant]
		status: DF.Literal["Open", "Closed", "Archived"]
		title: DF.Data | None
	# end: auto-generated types
	pass
