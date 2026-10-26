# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Tell Docu that a reserved field already on a DocType is not a new field.

The writer is told to keep every existing field exactly as it is; the reviewer
was told no field may carry a reserved Frappe name. A submittable DocType's own
``amended_from`` satisfied one rule and broke the other, and the repair cost a
full rewrite of the definition. Both prompts now separate a NEW reserved name
from one the DocType already carries.

The text lives in the seed module so the two stay in step; this patch only
pushes it onto a configuration that already exists.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.seed_docu_agent_config import _INLINE_SUB_PROMPTS

_AGENT = "Docu Agent"
_KEYS = ("schema_writer", "schema_reviewer")


def execute():
	if not frappe.db.exists("AI Agent Configuration", _AGENT):
		return

	doc = frappe.get_doc("AI Agent Configuration", _AGENT)
	changed = []
	for row in doc.sub_prompts:
		wanted = _INLINE_SUB_PROMPTS.get(row.sub_agent_id)
		if row.sub_agent_id in _KEYS and wanted and row.prompt_text != wanted:
			row.prompt_text = wanted
			changed.append(row.sub_agent_id)

	if changed:
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		print(f"Docu prompts refreshed: {', '.join(changed)}")
