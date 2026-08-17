# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class AIToolPolicyRule(Document):
	def validate(self):
		self.require_something_to_match()
		self.check_parameter_limits_parse()

	def require_something_to_match(self):
		"""A rule with no match criteria would either never fire or refuse
		everything, depending on how it were read. Refuse to save it rather
		than leave a security control whose behaviour is ambiguous.

		Either criterion is enough: a rule may bound WHAT a tool may act on
		(Restricted DocTypes), or HOW MUCH it may act with (Parameter Limits),
		or both. Requiring a DocType would make a pure transaction ceiling
		unsavable.
		"""
		if not (self.restricted_doctypes or "").strip() and not (self.parameter_limits or "").strip():
			frappe.throw(
				_("A policy rule needs at least one Restricted DocType or Parameter Limit, "
				  "otherwise it can never match a tool call.")
			)

	def check_parameter_limits_parse(self):
		"""Reject a limit line the interceptor could not read.

		At runtime an unreadable line is skipped and logged — it has to be, or
		one bad character in one rule would take the whole policy down. But a
		skipped line is a ceiling that looks enforced and is not, so the moment
		a person is present to fix it, say so instead of accepting it.
		"""
		from one_bpmn.security.tool_policy import _LIMIT_RE, _split_lines

		bad = [line for line in _split_lines(self.parameter_limits) if not _LIMIT_RE.match(line)]
		if bad:
			frappe.throw(
				_("Could not read these parameter limits: {0}. Write one bound per line as "
				  "<code>parameter &lt;= number</code>, using &lt;=, &lt;, &gt;= or &gt; — "
				  "for example <code>amount &lt;= 5000</code>.").format(
					", ".join(f"<b>{frappe.utils.escape_html(line)}</b>" for line in bad)
				)
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
