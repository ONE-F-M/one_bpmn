"""Submit Assertions joined every string the Assertion Checker produced. The AI dispatcher stores the checker's answer under both
its output variable (assertion_review) and <bpmn_id>_output (assertion_checker_output), so each APPROVED line arrived twice. The
approved lines then never equalled the submitted ones, every criterion came back "The checker did not approve every line exactly
as written." with no reason, and run_specs refused because nothing was ever frozen. Read the one variable the map names."""

import frappe

OLD = '_review = "\\n".join(str(v) for v in _out.values() if isinstance(v, str))'
NEW = '_review = str(_out.get("assertion_review") or _out.get("assertion_checker_output") or "")'


def execute():
	for name in frappe.get_all("Server Script", filters={"script": ["like", "%" + OLD + "%"]}, pluck="name"):
		script = frappe.db.get_value("Server Script", name, "script")
		frappe.db.set_value("Server Script", name, "script", script.replace(OLD, NEW))
