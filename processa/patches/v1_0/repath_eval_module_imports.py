import frappe
from frappe.utils import cint

from processa.ai_agent_security.code_checks.script_gate import script_hash

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
	"""Point Server Script imports at the moved eval modules and keep each approval valid."""
	for old in MOVED_MODULES:
		for name in frappe.get_all("Server Script", filters={"script": ["like", f"%{old}%"]}, pluck="name"):
			_repath_script(name)
	frappe.clear_cache(doctype="Server Script")


def _repath_script(name: str) -> None:
	row = frappe.db.get_value(
		"Server Script", name, ["script", "processa_approved", "processa_approved_hash"], as_dict=True
	)
	script = row.script
	for old, new in MOVED_MODULES.items():
		script = script.replace(old, new)
	if script == row.script:
		return
	values = {"script": script}
	if cint(row.processa_approved) and row.processa_approved_hash == script_hash(row.script):
		values["processa_approved_hash"] = script_hash(script)
	frappe.db.set_value("Server Script", name, values, update_modified=False)
