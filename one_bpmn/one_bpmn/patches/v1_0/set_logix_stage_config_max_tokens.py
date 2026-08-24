import frappe

# The real max_tokens value belongs on the config, not hardcoded in the
# script — dispatch_ai_agent overlays the linked config's own max_tokens onto
# every call once aiAgentConfig resolves, so a value typed in the script's
# task_cfg never actually took effect.
MAX_TOKENS = {
	"Logix – Intent Classifier": 512,
	"Logix – Clarifier": 512,
	"Logix – Script Writer": 4096,
	"Logix – Script Reviewer": 4096,
	"Logix – Tool Writer (Agent Tools)": 4096,
	"Logix – Test Writer": 1024,
}


def execute():
	for name, tokens in MAX_TOKENS.items():
		if not frappe.db.exists("AI Agent Configuration", name):
			continue
		frappe.db.set_value("AI Agent Configuration", name, "max_tokens", tokens)
