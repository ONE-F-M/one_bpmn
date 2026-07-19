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
		self.attach_process_implementation()

	def attach_process_implementation(self):
		"""Link the editable Process Implementation that enabled this creation.

		When a new model is created for a process (e.g. from the Processa
		editor), the Process Implementation that made the process editable
		is attached so that per-model editability can later be derived from
		that implementation's 'Editable' flag.

		Callers that already set process_implementation explicitly (e.g. the
		'Create BPMN Process Model' engine script) are left untouched.
		"""
		if self.process_implementation or not self.process_name:
			return

		from one_bpmn.api.editability import check_process_editable

		try:
			info = check_process_editable(self.process_name)
		except Exception:
			# Attaching is best-effort — the editability gate in validate()
			# is what actually blocks creation on locked processes.
			return

		pi_name = info.get("process_implementation")
		# The implementation may live on the Production site only (connected
		# mode) — never create a dangling local Link.
		if pi_name and frappe.db.exists("Process Implementation", pi_name):
			self.process_implementation = pi_name

	def on_trash(self):
		# Remove version-history snapshots that Link to this model, otherwise
		# deletion fails with a LinkExistsError. Runs before Frappe's link check
		# (on_trash precedes check_if_doc_is_linked), so it covers desk, API and
		# programmatic deletions alike.
		for snap in frappe.get_all("BPMN Diagram Version", filters={"model": self.name}, pluck="name"):
			frappe.delete_doc("BPMN Diagram Version", snap, ignore_permissions=True, force=True)

	def validate(self):
		self.validate_is_editable()
		self.extract_process_id_from_xml()
		self.enforce_single_active()
		self.validate_script_task_security()

	def validate_script_task_security(self):
		"""Pre-deployment gate: block unsafe script tasks at authoring time.

		Only runs when the BPMN XML actually changed (metadata-only saves are
		exempt), and can be bypassed by trusted internal callers that have
		already validated the content (e.g. compile_process_model) via
		``doc.flags.skip_script_security_check = True``.
		"""
		if self.flags.get("skip_script_security_check"):
			return
		if not self.bpmn_xml:
			return
		if not self.is_new() and not self.has_value_changed("bpmn_xml"):
			return

		from one_bpmn.security.script_gate import validate_process_model_scripts

		validate_process_model_scripts(self.bpmn_xml)

	def validate_is_editable(self):
		"""Ensure the model is editable on the backend level before saving it.

		Editability is derived from the Process Implementation doctype:
		  - New models require an editable (Active) Process Implementation
		    for the process — which gets attached in ``before_insert`` — or
		    an explicitly pre-set ``process_implementation``.
		  - Existing models are editable only while the Process
		    Implementation *linked to them* has its 'Editable' flag checked.

		Skipped for metadata-only changes (title, description, is_active,
		etc.) where the actual BPMN XML content has not been modified.

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

		# Skip the check only when neither the XML content nor the process
		# assignment has changed. Changing process_name could move the
		# model to a locked process.
		if (
			not self.is_new()
			and not self.has_value_changed("bpmn_xml")
			and not self.has_value_changed("process_name")
		):
			return

		from one_bpmn.api.editability import (
			_site_lock_override,
			check_process_editable,
			is_implementation_editable,
		)

		override = _site_lock_override()
		if override is not None:
			if not override["editable"]:
				frappe.throw(
					_("Cannot edit BPMN Process Model: {0}").format(override["reason"]),
					exc=frappe.ValidationError,
					title=_("Process Locked"),
				)
			return

		if self.is_new():
			# A pre-set implementation (engine script / before_insert attach)
			# authorises the creation; otherwise an editable implementation
			# must exist for the process (checked via the Production API in
			# connected mode, locally otherwise).
			if self.process_implementation:
				return
			editability_info = check_process_editable(self.process_name)
			if editability_info.get("editable"):
				return
			frappe.throw(
				_("Cannot create BPMN Process Model: {0}").format(
					editability_info.get(
						"reason",
						_('Process is locked. Create a Process Implementation and get it actioned to "Active" state to enable editing.'),
					)
				),
				exc=frappe.ValidationError,
				title=_("Process Locked"),
			)

		# Existing model — its own linked implementation must be editable
		# (routed to Production when connect_to_production is enabled).
		if self.process_implementation and is_implementation_editable(self.process_implementation):
			return

		reason = (
			_("The Process Implementation linked to this model ({0}) is not editable.").format(
				self.process_implementation
			)
			if self.process_implementation
			else _("No Process Implementation is linked to this model.")
		)
		frappe.throw(
			_("Cannot edit BPMN Process Model: {0}").format(reason),
			exc=frappe.ValidationError,
			title=_("Process Locked"),
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
		"""
		if self.flags.get("skip_process_id_regeneration"):
			return

		if not self.bpmn_xml:
			return

		# Only act when the XML already contains a process id
		old_match = re.search(r'<(?:[\w-]+:)?process\s[^>]*\bid=["\']([^"\']+)["\']', self.bpmn_xml)
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


