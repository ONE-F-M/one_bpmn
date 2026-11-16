"""Backend code removal status and notes move from each BPMN Process Model onto its Process.

Each Process takes the most advanced status among its models and their notes joined.
Runs post_model_sync: the Process columns exist by then, and the model's old columns stay in
the table after its fields leave the doctype.
"""

import frappe

PRECEDENCE = ["Not Started", "Removed on BA", "Removed on Production", "Migrated"]


def execute():
	rows = frappe.get_all(
		"BPMN Process Model",
		filters={"process_name": ["is", "set"]},
		fields=["process_name", "backend_code_removal_status", "backend_code_removal_notes"],
		order_by="creation asc",
	)
	by_process = {}
	for row in rows:
		by_process.setdefault(row.process_name, []).append(row)

	for process_name, models in by_process.items():
		if not frappe.db.exists("Process", process_name):
			continue
		ranks = [
			PRECEDENCE.index(m.backend_code_removal_status)
			for m in models
			if m.backend_code_removal_status in PRECEDENCE
		]
		status = PRECEDENCE[max(ranks, default=0)]
		notes = "\n".join(
			m.backend_code_removal_notes.strip()
			for m in models
			if (m.backend_code_removal_notes or "").strip()
		)
		if status == PRECEDENCE[0] and not notes:
			continue
		frappe.db.set_value(
			"Process",
			process_name,
			{"backend_code_removal_status": status, "backend_code_removal_notes": notes or None},
			update_modified=False,
		)
