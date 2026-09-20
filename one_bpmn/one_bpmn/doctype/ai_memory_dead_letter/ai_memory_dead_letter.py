# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AIMemoryDeadLetter(Document):
	"""A distillation that could not be completed, kept so the work is not lost.

	Memory writeback runs in the background and never raises, because a failure
	there must not reach the person who was talking to the agent. Before this
	existed that meant a failed distillation vanished: no memory, no record, and
	nothing to look at afterwards. A row here is what a silent failure leaves
	behind, carrying the payload so the work can be read or retried once the
	cause is fixed.
	"""

	pass
