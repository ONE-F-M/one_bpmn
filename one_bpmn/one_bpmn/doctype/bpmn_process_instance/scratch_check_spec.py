"""Quick script to check the compiled spec for notifyAssignee."""
import frappe
import json

def check():
	models = frappe.get_all(
		"BPMN Process Model",
		filters={"process_name": ["like", "%Software Development%"], "is_active": 1},
		fields=["name", "serialized_spec"],
		limit=1,
	)
	if not models:
		print("No active Software Development model found")
		return

	model = models[0]
	print(f"Model: {model.name}")

	if not model.serialized_spec:
		print("No serialized_spec!")
		return

	spec = json.loads(model.serialized_spec)
	exts = spec.get("user_task_extensions", {})
	print(f"\nAll user_task_extensions keys: {list(exts.keys())}")

	for bpmn_id, cfg in exts.items():
		print(f"\n--- {bpmn_id} ---")
		print(json.dumps(cfg, indent=2)[:500])

	# Specifically check Activity_1nsov2a
	task = exts.get("Activity_1nsov2a", {})
	print("\n=== Activity_1nsov2a (Assign Work Item to Developer) ===")
	print(f"  notifyAssignee: {task.get('notifyAssignee')!r}")
	print(f"  notifyAssigneeBody present: {bool(task.get('notifyAssigneeBody'))}")
