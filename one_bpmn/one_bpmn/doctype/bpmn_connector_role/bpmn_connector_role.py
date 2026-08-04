# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class BPMNConnectorRole(Document):
	"""One role permitted to use a connector.

	A child table rather than a comma-separated field so the roles are real
	Links — a renamed or deleted Role is caught by Frappe rather than silently
	leaving a gate that matches nothing.
	"""

	pass
