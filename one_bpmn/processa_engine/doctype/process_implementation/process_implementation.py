# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class ProcessImplementation(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amended_from: DF.Link | None
		bpmn_process_model: DF.Link | None
		business_analyst: DF.Link
		editable: DF.Check
		goal_description: DF.SmallText
		naming_series: DF.Literal["PBR-IMP-.YYYY.-.MM.-.####"]
		process_name: DF.Link
		process_owner: DF.Link
		workflow_state: DF.Link | None
	# end: auto-generated types
	pass
