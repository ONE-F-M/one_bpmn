# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class AIGoldenDatasetVersion(Document):
	SUBJECT_FIELD = {"Suite": "eval_suite", "Agent": "agent_configuration", "Skill": "target_skill"}

	def validate(self):
		field = self.SUBJECT_FIELD.get(self.subject_type)
		if not field or not self.get(field):
			frappe.throw(_("A dataset version must name the {0} it belongs to.").format(
				(self.subject_type or "subject").lower()))

		subject = self.get(field)
		if self.subject_type == "Suite":
			# A suite is named by a hash, so the label reads by its title.
			subject = frappe.db.get_value("AI Eval Suite", subject, "title") or subject
		self.label = f"{subject} v{self.version}"

	def on_trash(self):
		# A version is the record of what was tested and passed. Deleting the
		# newest would let the next snapshot reuse its number, so two different
		# datasets would answer to the same version.
		latest = frappe.db.get_value(
			"AI Golden Dataset Version",
			self._subject_filters(),
			"version",
			order_by="version desc",
		)
		if latest and int(latest) == int(self.version or 0):
			frappe.throw(_("The newest version cannot be deleted — the number would be reused."))

	def _subject_filters(self) -> dict:
		field = self.SUBJECT_FIELD[self.subject_type]
		return {"subject_type": self.subject_type, field: self.get(field)}
