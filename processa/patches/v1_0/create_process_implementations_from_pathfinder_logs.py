import frappe

# Pathfinder Log status → (Process Implementation workflow_state, editable, submit)
# States mirror the 'Process Implementation V1' BPMN lifecycle: the engine's
# apply_workflow service tasks use Backlog/Upcoming/Active/On Hold/Deployed,
# set editable=1 only while Active, and submit (docstatus 1) on Deployed.
STATUS_MAP = {
	"Backlog": ("Backlog", 0, False),
	"Pending Process Classification": ("Backlog", 0, False),
	"Upcoming": ("Upcoming", 0, False),
	"Active": ("Active", 1, False),
	"On Hold": ("On Hold", 0, False),
	"Deployed": ("Deployed", 0, True),
}


def execute():
	"""Backfill Process Implementations from Pathfinder Logs.

	Editability used to be derived from Pathfinder Log (one_fm); it now
	comes from the Process Implementation doctype. For every Process that
	already has BPMN Process Models and a Pathfinder Log, create ONE
	Process Implementation with the workflow state/status mapped from the
	most relevant log (an Active log wins, otherwise the most recently
	modified one) and attach it to ALL of that process's models.
	"""
	if not frappe.db.exists("DocType", "Pathfinder Log"):
		# one_fm (Pathfinder Log) is not installed on this site — nothing to backfill.
		return

	models = frappe.get_all(
		"BPMN Process Model",
		filters={"process_name": ["is", "set"]},
		fields=["name", "process_name", "is_active", "modified", "process_implementation"],
		order_by="modified desc",
	)

	models_by_process = {}
	for m in models:
		models_by_process.setdefault(m.process_name, []).append(m)

	for process_name, process_models in models_by_process.items():
		# Idempotency: skip processes that already have an implementation.
		existing_pi = frappe.db.get_value(
			"Process Implementation", {"process_name": process_name, "docstatus": ["<", 2]}, "name"
		)
		if not existing_pi:
			log = _pick_log(process_name)
			if not log:
				continue  # never had a Pathfinder Log — stays locked, as before
			existing_pi = _create_implementation(process_name, log, process_models)
			if not existing_pi:
				continue

		# The implementation used for one model applies to all of them.
		for m in process_models:
			if not m.process_implementation:
				frappe.db.set_value(
					"BPMN Process Model",
					m.name,
					"process_implementation",
					existing_pi,
					update_modified=False,
				)


def _pick_log(process_name: str) -> dict | None:
	"""Most relevant Pathfinder Log: an Active one wins, else latest modified."""
	logs = frappe.get_all(
		"Pathfinder Log",
		filters={"process_name": process_name},
		fields=[
			"name",
			"status",
			"goal_description",
			"process_owner_user",
			"business_analyst_user",
			"modified",
		],
		order_by="modified desc",
	)
	if not logs:
		return None
	active = [log for log in logs if log.status == "Active"]
	return active[0] if active else logs[0]


def _create_implementation(process_name: str, log: dict, process_models: list) -> str | None:
	workflow_state, editable, submit = STATUS_MAP.get(log.status or "", ("Backlog", 0, False))

	# The implementation's model link points at the deployed (active) model,
	# falling back to the most recently modified one.
	active_models = [m for m in process_models if m.is_active]
	linked_model = (active_models or process_models)[0]

	process_owner = log.process_owner_user or frappe.db.get_value(
		"Process", process_name, "process_owner"
	)

	try:
		doc = frappe.get_doc(
			{
				"doctype": "Process Implementation",
				"process_name": process_name,
				"bpmn_process_model": linked_model.name,
				"process_owner": process_owner,
				"business_analyst": log.business_analyst_user or "Administrator",
				"goal_description": log.goal_description
				or f"Backfilled from Pathfinder Log {log.name}",
				"workflow_state": workflow_state,
				"editable": editable,
			}
		)
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.insert()
		if submit:
			doc.submit()
		return doc.name
	except Exception:
		frappe.log_error(
			title=f"PI backfill failed for {process_name}",
			message=frappe.get_traceback(),
		)
		return None
