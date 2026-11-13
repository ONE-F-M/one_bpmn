# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Stop Docu's schema writer being shown a hardcoded module in its own template.

The ``schema_writer`` sub-prompt carries the JSON template the model must
produce, and that template contained a worked example::

    "module": "ONE BPMN",   // ... always the module you are told to use (default ONE BPMN)

A concrete value inside the output schema outweighs any instruction in the user
prompt, so the model copied it. Observed on a real conversation: "I need a
DocType ... in the ONE FM module" produced ONE BPMN on turn 1; "actually move it
to Operations" was acknowledged in prose on turn 3 and not applied; and asked on
turn 5, the agent reported ONE BPMN. The agent narrating a change the template
had already decided against is the worse half of that.

The module was pinned in three places and this is the one an export does not
carry. The other two — the writer's user prompt and the reviewer's
``setdefault`` fallback — are Server Scripts and travel with the Docu map.

Idempotent, and quiet when there is nothing to do: a site whose prompt has
already been corrected, or which has no Docu agent, is left alone.
"""

import frappe

AGENT_ID = "docu_agent"
SUB_AGENT = "schema_writer"

OLD = (
	'  "module": "ONE BPMN",         // Frappe app module — always the module you '
	"are told to use (default ONE BPMN); NEVER the business-process name"
)
NEW = (
	'  "module": "<module>",          // Frappe app module. Use the module the USER '
	"asks for; if they name one, that wins. Otherwise keep the current value you "
	"were given. NEVER the business-process name"
)


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return

	config = frappe.get_doc("AI Agent Configuration", name)
	changed = False
	for row in config.get("sub_prompts") or []:
		if row.sub_agent_id != SUB_AGENT:
			continue
		text = row.prompt_text or ""
		if OLD not in text:
			# Already corrected, or the prompt has been edited since. Either way
			# there is nothing here to replace, and guessing at a near-match
			# would risk rewriting somebody's deliberate wording.
			continue
		row.prompt_text = text.replace(OLD, NEW)
		changed = True

	if not changed:
		return

	config.save(ignore_permissions=True)
	frappe.db.commit()
	print(f"Docu schema_writer: the module is no longer hardcoded in the output template")
