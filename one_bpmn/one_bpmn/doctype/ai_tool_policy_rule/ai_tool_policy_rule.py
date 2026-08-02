# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class AIToolPolicyRule(Document):
	def validate(self):
		self.require_something_to_match()

	def require_something_to_match(self):
		"""A rule with no match criteria would either never fire or refuse
		everything, depending on how it were read. Refuse to save it rather
		than leave a security control whose behaviour is ambiguous."""
		if not (self.restricted_doctypes or "").strip():
			frappe.throw(
				_("A policy rule needs at least one Restricted DocType, "
				  "otherwise it can never match a tool call.")
			)

	def on_update(self):
		self.clear_policy_cache()

	def on_trash(self):
		self.clear_policy_cache()

	def clear_policy_cache(self):
		"""Rules are cached because they are read on every tool call; an edit
		must take effect immediately, not at the next cache expiry."""
		from one_bpmn.security.tool_policy import clear_rule_cache

		clear_rule_cache()
