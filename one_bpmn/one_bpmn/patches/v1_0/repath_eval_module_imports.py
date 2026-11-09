import frappe
from frappe.utils import cint

from one_bpmn.ai_agent_security.code_checks.script_gate import script_hash

# Old dotted path to new, for the eval modules that moved into ai_agent_evals.
MOVED_MODULES = {
	"one_bpmn.agents.eval_runner": "one_bpmn.ai_agent_evals.eval_runner",
	"one_bpmn.agents.eval_case_factory": "one_bpmn.ai_agent_evals.eval_case_factory",
	"one_bpmn.agents.eval_ci": "one_bpmn.ai_agent_evals.eval_ci",
	"one_bpmn.agents.eval_alerts": "one_bpmn.ai_agent_evals.eval_alerts",
	"one_bpmn.agents.eval_permissions": "one_bpmn.ai_agent_evals.eval_permissions",
	"one_bpmn.agents.adversarial_gate": "one_bpmn.ai_agent_evals.adversarial_gate",
	"one_bpmn.agents.adversarial_pack": "one_bpmn.ai_agent_evals.adversarial_pack",
	"one_bpmn.agents.online_eval": "one_bpmn.ai_agent_evals.online_eval",
	"one_bpmn.api.golden_dataset": "one_bpmn.ai_agent_evals.golden_dataset",
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
