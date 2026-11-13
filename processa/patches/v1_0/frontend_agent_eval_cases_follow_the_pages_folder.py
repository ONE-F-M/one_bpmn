"""Frontend Agent eval cases and their A2A Task fixtures name the Processa pages by their new paths.

Output from past runs (A2A Task result, AI Eval Result) is history and is left as it was. Idempotent.
"""

import frappe

PAGE_RENAMES = (
	("spiff/src/views/Insights.vue", "spiff/src/pages/Insights.vue"),
	("spiff/src/views/Editor.vue", "spiff/src/pages/Process.vue"),
	("spiff/src/views/Home.vue", "spiff/src/pages/Processes.vue"),
)


def execute():
	cases = frappe.get_all(
		"AI Eval Case",
		filters={"input_user_prompt": ["like", "%spiff/src/views/%"]},
		fields=["name", "input_user_prompt", "input_context"],
	)
	for case in cases:
		frappe.db.set_value(
			"AI Eval Case", case.name, "input_user_prompt", renamed(case.input_user_prompt), update_modified=False
		)
		_rename_in_fixture(case.input_context)


def renamed(text: str) -> str:
	for old, new in PAGE_RENAMES:
		text = text.replace(old, new)
	return text


def _rename_in_fixture(input_context: str | None):
	task = (frappe.parse_json(input_context or "{}") or {}).get("context_docname")
	if not task or not frappe.db.exists("A2A Task", task):
		return
	payload = frappe.db.get_value("A2A Task", task, "request_payload")
	if payload:
		frappe.db.set_value("A2A Task", task, "request_payload", renamed(payload), update_modified=False)
