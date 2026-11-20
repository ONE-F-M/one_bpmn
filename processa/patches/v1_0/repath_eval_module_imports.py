import frappe

# Old dotted path to new, for the eval modules that moved into ai_agent_evals.
MOVED_MODULES = {
	"processa.agents.eval_runner": "processa.ai_agent_evals.eval_runner",
	"processa.agents.eval_case_factory": "processa.ai_agent_evals.eval_case_factory",
	"processa.agents.eval_ci": "processa.ai_agent_evals.eval_ci",
	"processa.agents.eval_alerts": "processa.ai_agent_evals.eval_alerts",
	"processa.agents.eval_permissions": "processa.ai_agent_evals.eval_permissions",
	"processa.agents.adversarial_gate": "processa.ai_agent_evals.adversarial_gate",
	"processa.agents.adversarial_pack": "processa.ai_agent_evals.adversarial_pack",
	"processa.agents.online_eval": "processa.ai_agent_evals.online_eval",
	"processa.api.golden_dataset": "processa.ai_agent_evals.golden_dataset",
}


def execute():
	"""Point Server Script imports at the moved eval modules."""
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
