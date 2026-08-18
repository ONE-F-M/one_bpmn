import frappe
from frappe.model.document import Document
from frappe import _


class AISkill(Document):
	def validate(self):
		self._compute_token_estimate()
		self._validate_description()
		self._validate_allowed_tools_exist()
		self._validate_tier_graduation()

	def _compute_token_estimate(self):
		# US 1: rough rule of thumb, 1 token ~= 4 chars
		chars_per_token = 4
		self.token_estimate = len(self.body) // chars_per_token if self.body else 0

		if self.token_estimate > 5000:
			frappe.throw(_(
				"Skill body exceeds the token ceiling of 5,000 tokens (estimated {0} tokens). "
				"Please move details to resources."
			).format(self.token_estimate))

	def _validate_description(self):
		if not self.description:
			return

		if len(self.description) > 1024:
			frappe.throw(_("Description is too long (must be <= 1024 characters)."))

		desc_lower = self.description.lower()
		if "use this skill when" not in desc_lower and "when to use" not in desc_lower:
			frappe.throw(_("Description must contain trigger phrasing like 'Use this skill when' or 'when to use'."))
		if "do not use" not in desc_lower and "when not to use" not in desc_lower:
			frappe.throw(_("Description must contain anti-trigger phrasing like 'Do NOT use' or 'when NOT to use'."))

	def _validate_allowed_tools_exist(self):
		for tool_row in self.allowed_tools or []:
			if not frappe.db.exists("AI Agent Tool", tool_row.tool):
				frappe.throw(_("Allowed tool '{0}' does not exist.").format(tool_row.tool))

	def _validate_tier_graduation(self):
		"""US 5: tier is earned through eval evidence, not assigned by hand.

		Draft-Only has no requirements (it's the sandboxed starting point).
		Read-Only and Action-Allowed require eval cases + run results linked
		to this skill before they can be selected.
		"""
		if self.tier == "Draft-Only":
			return

		cases = frappe.get_all(
			"AI Eval Case",
			filters={"target_skill": self.name},
			fields=["name", "suite", "case_type"],
		)
		if not cases:
			frappe.throw(_("Cannot graduate skill to {0}: no AI Eval Cases target this skill.").format(self.tier))

		suites = sorted({c.suite for c in cases if c.suite})
		if not suites:
			frappe.throw(_("Cannot graduate skill to {0}: eval cases must belong to an AI Eval Suite.").format(self.tier))

		has_trigger_positive = any(c.case_type == "Trigger Positive" for c in cases)
		has_trigger_negative = any(c.case_type == "Trigger Negative" for c in cases)
		if not (has_trigger_positive and has_trigger_negative):
			frappe.throw(_(
				"Cannot graduate skill to {0}: needs both a Trigger Positive and a "
				"Trigger Negative eval case."
			).format(self.tier))

		runs = frappe.get_all(
			"AI Eval Run",
			filters={"suite": ["in", suites], "status": "Completed"},
			fields=["name", "passed_cases", "total_cases"],
			order_by="creation desc",
			limit=5,
		)
		if not runs:
			frappe.throw(_("Cannot graduate skill to {0}: no completed AI Eval Run for its suite yet.").format(self.tier))

		latest = runs[0]
		accuracy = (latest.passed_cases / latest.total_cases) if latest.total_cases else 0

		if self.tier == "Read-Only":
			if accuracy < 0.90:
				frappe.throw(_(
					"Cannot graduate to Read-Only: latest eval run trigger accuracy is {0}%, "
					"needs at least 90%."
				).format(round(accuracy * 100, 1)))

		elif self.tier == "Action-Allowed":
			case_count = len({c.name for c in cases})
			if case_count < 20:
				frappe.throw(_(
					"Cannot graduate to Action-Allowed: needs a golden dataset of 20+ eval "
					"cases targeting this skill (found {0})."
				).format(case_count))

			sustained = runs[:2]
			if len(sustained) < 2 or any(
				not r.total_cases or r.passed_cases != r.total_cases for r in sustained
			):
				frappe.throw(_(
					"Cannot graduate to Action-Allowed: needs sustained 100% pass across "
					"multiple recent runs (pass^k), not just a single lucky pass."
				))
