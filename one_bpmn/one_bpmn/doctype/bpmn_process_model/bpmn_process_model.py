# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
import re


class BPMNProcessModel(Document):
	def validate(self):
		self.extract_process_id_from_xml()
		self.enforce_single_active()

	def enforce_single_active(self):
		"""Ensure only one process model is active per process.

		When this model is being activated, deactivate all other models
		that belong to the same process_name.
		"""
		if not self.is_active or not self.process_name:
			return

		frappe.db.set_value(
			"BPMN Process Model",
			{
				"process_name": self.process_name,
				"is_active": 1,
				"name": ("!=", self.name),
			},
			"is_active",
			0,
			update_modified=False,
		)

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
