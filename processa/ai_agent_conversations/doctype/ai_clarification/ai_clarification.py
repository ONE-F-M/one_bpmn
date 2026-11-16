# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A question an agent asked a person, and the answer it got.

The record exists because the decision has to outlive the
conversation: a clarification that only lives in an agent's transcript cannot be
audited later, and "why was it built this way" is asked weeks after the run.

Read-only in the Desk on purpose. Every field is written by the machinery that
asked or answered the question, and a record of a decision that can be edited
afterwards is not a record of anything.
"""

from frappe.model.document import Document


class AIClarification(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		agent_configuration: DF.Link | None
		answer: DF.SmallText | None
		answered_at: DF.Datetime | None
		answered_by: DF.Link | None
		asked_at: DF.Datetime | None
		asked_by_agent_run: DF.Link | None
		escalated_at: DF.Datetime | None
		escalated_to: DF.Link | None
		follow_up_of: DF.Link | None
		human_task_id: DF.Data | None
		instance: DF.Link | None
		interpretations: DF.SmallText | None
		owner_asked: DF.Link | None
		question: DF.SmallText | None
		reference_doctype: DF.Link | None
		reference_name: DF.DynamicLink | None
		reminded_at: DF.Datetime | None
		round: DF.Int
		status: DF.Literal["Awaiting Answer", "Answered", "Escalated", "Abandoned"]
	# end: auto-generated types
	pass
