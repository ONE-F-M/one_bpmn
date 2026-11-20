import frappe

# Old dotted path to new, for the observability modules and the Insights API that moved.
MOVED_MODULES = {
	"processa.agents.observability": "processa.ai_agent_observability.observability",
	"processa.agents.pricing": "processa.ai_agent_observability.pricing",
	"processa.agents.goal_completion": "processa.ai_agent_observability.goal_completion",
	"processa.api.insights_api": "processa.api.insights",
}


def execute():
	"""Point Server Script imports at the moved observability and Insights modules."""
	for old in MOVED_MODULES:
		for name in frappe.get_all("Server Script", filters={"script": ["like", f"%{old}%"]}, pluck="name"):
			_repath_script(name)
	frappe.clear_cache(doctype="Server Script")


def _repath_script(name: str) -> None:
	original = frappe.db.get_value("Server Script", name, "script")
	script = original
	for old, new in MOVED_MODULES.items():
		script = script.replace(old, new)
	if script != original:
		frappe.db.set_value("Server Script", name, "script", script, update_modified=False)
