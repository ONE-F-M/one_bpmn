# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
import re


class BPMNProcessModel(Document):
	def validate(self):
		self.extract_process_id_from_xml()

	def before_save(self):
		if not self.is_new():
			self.version = (self.version or 0) + 1

	def extract_process_id_from_xml(self):
		"""Auto-extract process_id from BPMN XML if not manually set."""
		if self.bpmn_xml and not self.process_id:
			try:
				import xml.etree.ElementTree as ET

				root = ET.fromstring(self.bpmn_xml)
				ns = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}
				process = root.find(".//bpmn:process", ns)
				if process is not None:
					self.process_id = process.get("id", "")
			except Exception:
				pass  # XML parsing failures are non-fatal here
