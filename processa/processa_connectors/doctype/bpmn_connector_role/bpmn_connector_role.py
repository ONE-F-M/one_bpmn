# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class BPMNConnectorRole(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		role: DF.Link
	# end: auto-generated types
	"""One role permitted to use a connector.

	A child table rather than a comma-separated field so the roles are real
	Links — a renamed or deleted Role is caught by Frappe rather than silently
	leaving a gate that matches nothing.
	"""

	pass
