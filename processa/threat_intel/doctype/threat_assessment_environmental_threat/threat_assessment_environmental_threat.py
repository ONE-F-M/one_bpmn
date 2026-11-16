# Copyright (c) 2025, Kartik Sharma and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class ThreatAssessmentEnvironmentalThreat(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		location: DF.Data | None
		name_field: DF.Link | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		threat_level: DF.Data | None
	# end: auto-generated types
	pass