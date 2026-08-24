import frappe

# aiMaxTokens in these ad-hoc task_cfg dicts never actually took effect: once
# aiAgentConfig resolves to a real config (always true now), dispatch_ai_agent
# overlays the config's own max_tokens onto the call, overwriting whatever the
# script set. The real value now lives on each dedicated config instead (see
# set_logix_stage_config_max_tokens.py) — this just removes the dead line.
EDITS = {
	"Logix – Tool Classify Intent": '    "aiMaxTokens": 512,\n',
	"Logix – Tool Clarify": '    "aiMaxTokens": 512,\n',
	"Logix – Tool Write Script": '    "aiMaxTokens": 4096,\n',
	"Logix – Tool Review Script": '    "aiMaxTokens": 4096,\n',
	"Logix – Tool Write Agent Tool": '    "aiMaxTokens": 4096,\n',
	"Logix – Tool Finalize": '                        "aiMaxTokens": 1024,\n',
}


def execute():
	for script_name, old_line in EDITS.items():
		if not frappe.db.exists("Server Script", script_name):
			continue
		doc = frappe.get_doc("Server Script", script_name)
		script = doc.script or ""
		if old_line not in script:
			continue  # already migrated, or diverged (nothing to log — dead-code cleanup only)
		doc.script = script.replace(old_line, "", 1)
		doc.save(ignore_permissions=True)
