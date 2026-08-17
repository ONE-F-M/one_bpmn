# Throwaway (LOCAL BENCH ONLY): gives the three chat agents' maps a Process,
# an Active Pathfinder Log and a Process Implementation, so they show up in
# Processa like any other process. Site data only — nothing here ships.

import frappe

OWNER = "c.akeru@one-fm.com"

# process name → (description, goal, [BPMN Process Models to attach])
SEEDS = {
	"Lumina General Chat": (
		"Lumina's general assistant: answers questions about ONE-FM data and runs "
		"read-only tools on the user's behalf.",
		"Give every user a single conversational entry point to ONE-FM.",
		["Lumina Chat – General Agent"],
	),
	"LuCrusher Migration": (
		"Migrates Lucidchart process maps into ONE-FM: matches processes, parses "
		"documents, scans the codebase and drafts the migration plan.",
		"Turn a Lucidchart diagram into a reviewed migration plan without manual transcription.",
		["LuCrusher – Migration Agent"],
	),
	"BA Agent Planning": (
		"Business analysis: clarifies a requirement, plans it, and breaks the "
		"approved plan into user stories.",
		"Turn a plain-English need into an approved plan and reviewable user stories.",
		# Both shapes of the BA map hang off one process — the LangGraph one and
		# the tools-shaped one, whichever is currently active.
		["BA – Planning Agent", "Lumina Chat – BA Agent"],
	),
}

STATUS = "Active"  # → Process Implementation Active + editable (STATUS_MAP)

# Pathfinder Log refuses to go Active without an Epic and a folder link
# (_validate_active_status_conditions), so each process gets its own Epic.
FOLDER_LINK = "http://127.0.0.1:8001/processa"


def _epic(process: str, goal: str) -> str:
	title = f"{process} — agent process"
	existing = frappe.db.exists("Work Item", {"title": title, "work_item_type": "Epic"})
	if existing:
		print(f"  epic exists: {existing}")
		return existing
	doc = frappe.get_doc({
		"doctype": "Work Item",
		"work_item_type": "Epic",
		"title": title,
		"description": goal,
	})
	doc.flags.ignore_permissions = True
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True)
	print(f"  epic created: {doc.name}")
	return doc.name


def _process(name: str, description: str) -> str:
	if frappe.db.exists("Process", name):
		print(f"  process exists: {name}")
		return name
	doc = frappe.get_doc({
		"doctype": "Process",
		"process_name": name,
		"description": description,
		"process_owner": OWNER,
	})
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	print(f"  process created: {doc.name}")
	return doc.name


def _pathfinder_log(process: str, goal: str, epic: str) -> str:
	existing = frappe.db.exists("Pathfinder Log", {"process_name": process})
	if existing:
		doc = frappe.get_doc("Pathfinder Log", existing)
		doc.epic = doc.epic or epic
		doc.process_folder_link = doc.process_folder_link or FOLDER_LINK
		doc.status = STATUS
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)
		print(f"  pathfinder log exists: {existing} → {STATUS}")
		return existing
	doc = frappe.get_doc({
		"doctype": "Pathfinder Log",
		"process_name": process,
		"goal_description": goal,
		"process_owner_user": OWNER,
		"business_analyst_user": OWNER,
		"epic": epic,
		"process_folder_link": FOLDER_LINK,
		"status": STATUS,
	})
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	print(f"  pathfinder log created: {doc.name} ({STATUS})")
	return doc.name


def _implementation(process: str, goal: str, models: list) -> str | None:
	"""One implementation per process, attached to every one of its models —
	the same rule create_process_implementations_from_pathfinder_logs applies.
	Active ⇒ editable, so the map opens unlocked in the designer."""
	existing = frappe.db.get_value(
		"Process Implementation", {"process_name": process, "docstatus": ["<", 2]}, "name"
	)
	if not existing:
		linked = next((m for m in models if frappe.db.get_value("BPMN Process Model", m, "is_active")), models[0])
		doc = frappe.get_doc({
			"doctype": "Process Implementation",
			"process_name": process,
			"bpmn_process_model": linked,
			"process_owner": OWNER,
			"business_analyst": OWNER,
			"goal_description": goal,
			"workflow_state": STATUS,
			"editable": 1,
		})
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		existing = doc.name
		print(f"  implementation created: {existing} (editable)")
	else:
		print(f"  implementation exists: {existing}")
	return existing


def run():
	for process_name, (description, goal, models) in SEEDS.items():
		print(process_name + ":")
		present = [m for m in models if frappe.db.exists("BPMN Process Model", m)]
		if not present:
			print("  no maps on this site — skipped")
			continue
		_process(process_name, description)
		_pathfinder_log(process_name, goal, _epic(process_name, goal))
		implementation = _implementation(process_name, goal, present)
		for model in present:
			frappe.db.set_value(
				"BPMN Process Model",
				model,
				{"process_name": process_name, "process_implementation": implementation},
				update_modified=False,
			)
			print(f"  map linked: {model}")
	frappe.db.commit()
