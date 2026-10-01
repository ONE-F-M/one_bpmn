"""
WI-003131: backend code removal tracking moves from BPMN Process Model to Process.

Whether a process's old backend code has been removed is a fact about the
process, not about one version of its diagram. The two fields used to live in
a "Deployment Checklist" section on every BPMN Process Model, so each new
version started back at "Not Started" and the deploy warned again. They now
live once on the Process, in its More Information tab.

This patch runs pre_model_sync, while the old backend_code_removal_status and
backend_code_removal_notes columns are still present on BPMN Process Model,
and backfills the Process from its models:

- For each Process, set backend_code_removal_status to the most advanced
  value among its models, in precedence order:
  Not Started < Removed on BA < Removed on Production < Migrated.
- Concatenate any non-empty backend_code_removal_notes from those models.
- A Process whose models are all "Not Started" (or blank) is left at the
  Select field's own default ("Not Started") and gets no notes.

Idempotent: the result is always derived fresh from the model rows, so
running the patch again recomputes and sets the same values.
"""

import frappe

_PRECEDENCE = ["Not Started", "Removed on BA", "Removed on Production", "Migrated"]
_RANK = {status: idx for idx, status in enumerate(_PRECEDENCE)}


def execute():
	if not frappe.db.table_has_column("BPMN Process Model", "backend_code_removal_status"):
		# Already migrated away on this site (or a fresh install past this
		# point) — nothing to read.
		return

	rows = frappe.get_all(
		"BPMN Process Model",
		filters={"process_name": ["is", "set"]},
		fields=["process_name", "backend_code_removal_status", "backend_code_removal_notes"],
		limit_page_length=0,
	)

	by_process: dict[str, list] = {}
	for row in rows:
		by_process.setdefault(row.process_name, []).append(row)

	for process_name, models in by_process.items():
		if not frappe.db.exists("Process", process_name):
			continue

		best_status = "Not Started"
		best_rank = 0
		notes = []
		for model in models:
			status = (model.backend_code_removal_status or "").strip() or "Not Started"
			rank = _RANK.get(status, 0)
			if rank > best_rank:
				best_rank = rank
				best_status = status

			note = (model.backend_code_removal_notes or "").strip()
			if note:
				notes.append(note)

		updates = {"backend_code_removal_status": best_status}
		if notes:
			updates["backend_code_removal_notes"] = "\n".join(notes)

		frappe.db.set_value("Process", process_name, updates, update_modified=False)

	frappe.db.commit()
