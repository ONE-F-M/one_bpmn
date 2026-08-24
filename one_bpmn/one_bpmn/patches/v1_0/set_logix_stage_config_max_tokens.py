import frappe

# max_tokens belongs on the config — dispatch_ai_agent overlays it onto every call.
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
