import frappe


def execute():
	"""Remove the one-ai desk Page in both of its names (WI-001678 follow-up).

	The page was born as "one-ai", where onefm_mcp's PUBLIC WORKSPACE titled
	"ONE AI" shadowed it (the desk router resolves workspaces first), briefly
	renamed to "one-ai-chat", then removed outright at the user's direction
	(2026-08-10). The one-ai BUNDLE stays: window.oneAI.openAgentChat still
	serves the AI Agent Configuration form's Chat button; only the standalone
	desk page is gone. General chat remains on the legacy /app/lumina page
	until the onefm_mcp retirement (WI-001669 / WI-001964).
	"""
	for name in ("one-ai", "one-ai-chat"):
		if frappe.db.exists("Page", name):
			frappe.delete_doc("Page", name, force=True, ignore_permissions=True)
