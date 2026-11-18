"""Fixes two ways the Testing Agent's stored scripts lost the run's values.

1. Sandbox tool scripts read git_branch from the model's arguments. The map has no such variable, only base_branch (set from the
   pull request), so the tools failed unless the model copied the branch in. Fall back to base_branch.
2. Run Specs calls the run_specs_op connector step from inside its script. That step's parameters are all {{ task_data.* }}, and
   no process variables were passed, so every one rendered blank. Pass the script's own task_data."""

import frappe

REPLACEMENTS = (
	(
		'git_branch = (task_data.get("git_branch") or "").strip()',
		'git_branch = (task_data.get("git_branch") or task_data.get("base_branch") or "").strip()',
	),
	(
		'execute_shape(instance, "run_specs_op", None, {})',
		'execute_shape(instance, "run_specs_op", None, {}, task_data)',
	),
)


def execute():
	for old, new in REPLACEMENTS:
		for name in frappe.get_all("Server Script", filters={"script": ["like", "%" + old + "%"]}, pluck="name"):
			script = frappe.db.get_value("Server Script", name, "script")
			frappe.db.set_value("Server Script", name, "script", script.replace(old, new))
