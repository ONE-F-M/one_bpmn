# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class AIGoldenDatasetVersion(Document):
	def validate(self):
		if self.subject_type == "Agent" and not self.agent_configuration:
			frappe.throw(_("An agent's dataset version must name the agent."))
		if self.subject_type == "Skill" and not self.target_skill:
			frappe.throw(_("A skill's dataset version must name the skill."))

		subject = self.agent_configuration if self.subject_type == "Agent" else self.target_skill
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
		if self.subject_type == "Agent":
			return {"subject_type": "Agent", "agent_configuration": self.agent_configuration}
		return {"subject_type": "Skill", "target_skill": self.target_skill}
