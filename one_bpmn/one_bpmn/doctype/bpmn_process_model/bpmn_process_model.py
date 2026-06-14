# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
import re
import uuid


class BPMNProcessModel(Document):
	def before_insert(self):
		self.regenerate_process_id_on_duplicate()

	def validate(self):
		self.validate_is_editable()
		self.extract_process_id_from_xml()
		self.enforce_single_active()

	def validate_is_editable(self):
		"""Ensure that the process is editable on the backend level before saving it.

		The cross-site Pathfinder Log check is expensive (~0.5-2s HTTP round-trip).
		Skip it for metadata-only changes (title, description, is_active, etc.)
		where the actual BPMN XML content has not been modified.

		Trusted callers (import_bpmn, compile_process_model) set
		``doc.flags.skip_editability_check = True`` to bypass this gate
		because those operations are permitted even on Production.
		"""
		if self.flags.get("skip_editability_check"):
			return

		if not self.process_name:
			return

		# Allow Frappe Administrator to bypass if necessary
		if frappe.session.user == "Administrator":
			return

		# Skip the expensive cross-site check only when neither the XML
		# content nor the process assignment has changed. Changing
		# process_name could move the model to a locked process.
		if (
			not self.is_new()
			and not self.has_value_changed("bpmn_xml")
			and not self.has_value_changed("process_name")
		):
			return

		from one_bpmn.api.editability import check_process_editable

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

	def extract_process_id_from_xml(self):
		"""Always extract process_id from the BPMN XML (source of truth).

		The XML's <bpmn:process id="…"> is the canonical process_id.
		This keeps the field in sync whenever the diagram is saved.
		"""
		if not self.bpmn_xml:
			return

		try:
			import xml.etree.ElementTree as ET

			root = ET.fromstring(self.bpmn_xml)
			ns = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL"}
			process = root.find(".//bpmn:process", ns)
			if process is not None:
				extracted = process.get("id", "")
				if extracted:
					self.process_id = extracted
		except Exception:
			pass  # XML parsing failures are non-fatal here

	def regenerate_process_id_on_duplicate(self):
		"""Generate a new unique process_id when duplicating a process model.

		When a BPMN Process Model is duplicated (via Frappe desk Menu > Duplicate
		or ``frappe.copy_doc()``), the XML still contains the original process_id.
		This would cause identity collisions during import and deploy.

		Detection: this is a new document (``before_insert``) that already carries
		XML content with a ``<bpmn:process id="…">`` element — i.e. it was created
		from an existing model rather than from scratch.

		Trusted callers (e.g. ``import_bpmn``) set
		``doc.flags.skip_process_id_regeneration = True`` to preserve the original
		process_id from the imported file.

		The new process_id uses the format ``Process_<8-hex-chars>``.
		if self.flags.get("skip_process_id_regeneration"):
			return

		if not self.bpmn_xml:
			return

		# Only act when the XML already contains a process id
		old_match = re.search(r'<bpmn:process\s[^>]*id=["\']([^"\']+)["\']', self.bpmn_xml)
		if not old_match:
			return

		old_id = old_match.group(1)
		if not frappe.db.exists("BPMN Process Model", {"process_id": old_id}):
			return
		new_id = "Process_" + uuid.uuid4().hex[:8]
		# Replace all occurrences of the old process id in the XML
		# (covers <bpmn:process id="…"> and bpmnElement="…" references)
		self.bpmn_xml = self.bpmn_xml.replace(old_id, new_id)
		self.process_id = new_id


