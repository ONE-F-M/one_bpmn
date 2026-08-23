# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A question an agent asked a person, and the answer it got.

WI-002050. The record exists because the decision has to outlive the
conversation: a clarification that only lives in an agent's transcript cannot be
audited later, and "why was it built this way" is asked weeks after the run.

Read-only in the Desk on purpose. Every field is written by the machinery that
asked or answered the question, and a record of a decision that can be edited
afterwards is not a record of anything.
"""

from frappe.model.document import Document


class AIClarification(Document):
	pass
