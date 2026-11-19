# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import DocType

from processa.ai_agent_security.code_checks.script_categories import SYNTAX_CHECKS, clear_category_cache


class ScriptImportCategory(Document):
	def validate(self):
		for d in self.names:
			d.dotted_name = (d.dotted_name or "").strip()
			if d.kind == "Syntax" and d.dotted_name not in SYNTAX_CHECKS:
				frappe.throw(
					_("Row {0}: {1} is not a shape check. Use one of: {2}").format(
						d.idx, d.dotted_name, ", ".join(sorted(SYNTAX_CHECKS))
					)
				)
			if not all(part.isidentifier() for part in d.dotted_name.split(".")):
				frappe.throw(
					_("Row {0}: {1} is not a dotted name such as urllib.request").format(d.idx, d.dotted_name)
				)
		self.refuse_names_in_other_categories()

	def refuse_names_in_other_categories(self):
		row = DocType("Script Import Category Name")
		taken = (
			frappe.qb.from_(row)
			.select(row.parent, row.dotted_name, row.kind)
			.where(row.parenttype == "Script Import Category")
			.where(row.parent != self.name)
			.where(row.dotted_name.isin([d.dotted_name for d in self.names] or [""]))
		).run(as_dict=True)
		owner = {(t.dotted_name, t.kind): t.parent for t in taken}
		for d in self.names:
			other = owner.get((d.dotted_name, d.kind))
			if other:
				frappe.throw(
					_("Row {0}: {1} ({2}) is already in category {3}, so it cannot also be in {4}").format(
						d.idx, d.dotted_name, d.kind, other, self.name
					)
				)

	def on_update(self):
		clear_category_cache()

	def on_trash(self):
		clear_category_cache()
