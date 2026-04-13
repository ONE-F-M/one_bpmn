# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
import re


class BPMNProcessModel(Document):
	def validate(self):
		self.validate_is_editable()
		self.extract_process_id_from_xml()
		self.enforce_single_active()

	def validate_is_editable(self):
		"""Ensure that the process is editable on the backend level before saving it"""
		if not self.process_name:
			return
		
		# Allow Frappe Administrator to bypass if necessary
		if frappe.session.user == "Administrator":
			return
		
		from one_bpmn.api import check_process_editable
		
		editability_info = check_process_editable(self.process_name)
		if not editability_info.get("editable"):
			reason = editability_info.get("reason", "No active Pathfinder Log.")
			frappe.throw(
				_("Cannot edit BPMN Process Model: {0}").format(reason),
				exc=frappe.ValidationError,
				title=_("Process Locked")
			)

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
