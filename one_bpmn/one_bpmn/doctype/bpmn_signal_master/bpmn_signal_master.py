# Copyright (c) 2026, ONE FM and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class BPMNSignalMaster(Document):
	def validate(self):
		self.bpmn_signal_name = self.bpmn_signal_name.strip()
