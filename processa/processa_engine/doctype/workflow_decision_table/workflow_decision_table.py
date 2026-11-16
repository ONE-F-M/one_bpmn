# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class WorkflowDecisionTable(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		decision_id: DF.Data
		decision_name: DF.Data | None
		dmn_xml: DF.Code | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
	# end: auto-generated types
	# Child table — inherits permissions from parent BPMN Process Model.
	pass
