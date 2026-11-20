"""Logix's script writers reuse the library scripts on the map through import_script."""

import frappe

AGENT_ID = "logix_agent"
WRITERS = ("script_writer", "tool_writer")
GUIDANCE = (
	"Library scripts: when the context lists LIBRARY SCRIPTS ON THIS MAP, call their functions instead of "
	'writing the same code again: lib = import_script("<library name>"), then lib.<function>(...). Use the '
	"library name exactly as listed, in quotes. Change only the script that is open; never edit a library "
	"in the same reply."
)


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return
	config = frappe.get_doc("AI Agent Configuration", name)
	changed = False
	for row in config.sub_prompts:
		if row.sub_agent_id in WRITERS and GUIDANCE not in (row.prompt_text or ""):
			row.prompt_text = ((row.prompt_text or "").rstrip() + "\n\n" + GUIDANCE).strip()
			changed = True
	if changed:
		config.save(ignore_permissions=True)  # a patch runs as Administrator with no request user to check
