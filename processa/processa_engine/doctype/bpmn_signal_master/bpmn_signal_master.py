# Copyright (c) 2026, ONE FM and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class BPMNSignalMaster(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		bpmn_signal_name: DF.Data
	# end: auto-generated types
	def validate(self):
		self.bpmn_signal_name = self.bpmn_signal_name.strip()
