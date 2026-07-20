# Copyright (c) 2026, ONE BPMN and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class UserTaskAssignmentLog(Document):
	"""Immutable audit trail of User Task assignment changes made through the
	'Reassign User Task' action on a locked/deployed process map."""

	pass
