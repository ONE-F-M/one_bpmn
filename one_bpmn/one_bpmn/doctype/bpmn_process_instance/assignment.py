# Copyright (c) 2026, one-fm and contributors
# BPMN Process Instance — assignment resolution + Frappe ToDo management
#
# Standalone functions extracted from the BPMNProcessInstance controller.
# Each receives the controller document as ``instance`` and reads only simple
# attributes from it (context_doctype, context_docname, name, process_model,
# _user_task_extensions).  Invoked from the controller's ``_sync_active_tasks``.

import frappe
from frappe import _

from one_bpmn.one_bpmn import engine as bpmn_engine


def get_reliever_if_on_leave(user: str) -> str:
	"""
	If *user* is on approved leave today, return the reliever's User ID
	from the Leave Application (``reliever_user_id``).  Falls back to the
	original *user* when no active approved leave exists or no reliever is set.
	"""
	if not user:
		return user

	try:
		today = frappe.utils.today()
		employee = frappe.db.get_value(
			"Employee",
			{"user_id": user, "status": ["in", ["Active", "Vacation", "Not Returned from Leave"]]},
			"name",
		)
		if not employee:
			return user
		reliever_user = frappe.db.get_value(
			"Leave Application",
			{
				"employee": employee,
				"status": "Approved",
				"from_date": ["<=", today],
				"to_date": [">=", today],
				"reliever_user_id": ["is", "set"],
			},
			"reliever_user_id",
		)
		return reliever_user if reliever_user else user
	except Exception:
		frappe.log_error(
			title="BPMN: Leave reliever lookup failed",
			message=frappe.get_traceback(),
		)
		return user


def resolve_assignment(instance, task) -> str:
	"""
	Determine which user should be assigned to a UserTask based on the
	``user_task_extensions`` embedded in the serialized spec at compile time.

	Supported ``assigneeMode`` values:

	    User
	        A specific user is hard-coded in the diagram (``assigneeUser``).

	    DocField
	        The assignee is read from a Link/Data field on the context document
	        (``targetDoctype`` + ``assigneeDocfield``).

	    Round Robin
	        Cycles through ``assigneeUsers`` (comma-separated) in order.
	        State (next_idx + last_user) is persisted on the Process Model
	        so the rotation continues across all instances of the same model.
	        After each assignment the BPMN XML is patched to show
	        ``spiffworkflow:roundRobinLastUser`` in the editor.

	    Load Balancing
	        Assigns to the user in ``assigneeUsers`` with the fewest open
	        BPMN Process Instance active tasks.  Ties are broken by list order.

	For all modes, if the resolved assignee is on approved leave today the
	task is redirected to the reliever named in their Leave Application.

	Returns the resolved user email/name, or empty string if unresolvable.
	"""
	extensions = getattr(instance, "_user_task_extensions", {})
	bpmn_id = getattr(task.task_spec, "bpmn_id", None) or ""
	task_cfg = extensions.get(bpmn_id, {})

	mode = task_cfg.get("assigneeMode", "")

	# ── User ──────────────────────────────────────────────────────────────
	if mode == "User":
		return get_reliever_if_on_leave(task_cfg.get("assigneeUser", ""))

	# ── DocField ──────────────────────────────────────────────────────────
	if mode == "DocField":
		doctype = task_cfg.get("targetDoctype") or instance.context_doctype
		docfield = task_cfg.get("assigneeDocfield", "")
		if doctype and docfield and instance.context_docname:
			try:
				user = frappe.db.get_value(doctype, instance.context_docname, docfield)
				return get_reliever_if_on_leave(user or "")
			except Exception:
				return ""
		return ""

	# ── Round Robin ────────────────────────────────────────────────────────
	if mode == "Round Robin":
		users_raw = task_cfg.get("assigneeUsers", "")
		users = [u.strip() for u in users_raw.split(",") if u.strip()]
		if not users:
			return ""

		try:
			model = frappe.get_doc("BPMN Process Model", instance.process_model)
			rr_state = frappe.parse_json(model.round_robin_state or "{}")
			task_state = rr_state.get(bpmn_id, {"next_idx": 0, "last_user": ""})

			next_idx = int(task_state.get("next_idx", 0))
			assignee = users[next_idx % len(users)]
			next_idx += 1

			# Persist updated state + patch BPMN XML (non-blocking: log on fail)
			task_state["next_idx"] = next_idx
			task_state["last_user"] = assignee
			rr_state[bpmn_id] = task_state
			model.round_robin_state = frappe.as_json(rr_state)
			model.save(ignore_permissions=True)

			# Best-effort: patch the BPMN XML attribute for editor visibility
			try:
				from one_bpmn.api.compilation import _update_round_robin_in_model

				_update_round_robin_in_model(instance.process_model, bpmn_id, assignee)
			except Exception:
				pass

			return get_reliever_if_on_leave(assignee)
		except Exception:
			frappe.log_error(
				title="BPMN: Round Robin assignment failed",
				message=frappe.get_traceback(),
			)
			return get_reliever_if_on_leave(users[0]) if users else ""

	# ── Load Balancing ─────────────────────────────────────────────────────
	# Correct logic (per spec):
	#   1. Among ALL running Process Instances, find those where THIS SAME
	#      User Task is currently an active (Waiting) task.
	#   2. For each candidate user, count how many of those task slots
	#      they are already assigned to.
	#   3. Assign to the user with the fewest such assignments.
	#   4. Ties → first user in the configured list wins.
	if mode == "Load Balancing":
		users_raw = task_cfg.get("assigneeUsers", "")
		users = [u.strip() for u in users_raw.split(",") if u.strip()]
		if not users:
			return ""

		try:
			# Use the BPMN task display name to identify the same task
			# across different process instances of this model.
			task_name = bpmn_engine.get_task_display_name(task)

			loads = {}
			for user in users:
				loads[user] = frappe.db.count(
					"BPMN Active Task",
					filters={
						"assigned_user": user,
						"task_name": task_name,  # ← this task only
						"status": "Waiting",
					},
				)

			# User with fewest active assignments wins; ties → first in list
			minimum = min(loads.values())
			assignee = next(u for u in users if loads[u] == minimum)
			return get_reliever_if_on_leave(assignee)

		except Exception:
			frappe.log_error(
				title="BPMN: Load Balancing assignment failed",
				message=frappe.get_traceback(),
			)
			return get_reliever_if_on_leave(users[0]) if users else ""

	return ""


def add_frappe_assignment(instance, user: str, task_name: str = "") -> None:
	"""
	Create a Frappe Assignment (ToDo) on the context document for the
	resolved user.  This makes the assignment visible in Frappe's sidebar
	and the user's ToDo list.

	Creates the ToDo directly with ``type="Process"`` so that the OneFM
	notification system skips the standard assignment email/bell — Processa
	handles notifications for process tasks independently.

	Silently skips if no context document is linked or if the user is
	already assigned.  Failures are logged but never break the workflow.
	"""
	if not (instance.context_doctype and instance.context_docname and user):
		return

	try:
		# Check if already assigned to avoid duplicates
		existing = frappe.db.exists(
			"ToDo",
			{
				"reference_type": instance.context_doctype,
				"reference_name": instance.context_docname,
				"allocated_to": user,
				"status": "Open",
			},
		)
		if existing:
			return

		description = _('BPMN Task: "{0}" on instance {1}').format(
			task_name or "User Task", instance.name
		)

		# Create the ToDo directly with type="Process" instead of using
		# assign_to.add(), which always fires notify_assignment.  The
		# ToDo's on_update hook still updates the _assign sidebar field.
		from frappe.utils import nowdate

		frappe.get_doc({
			"doctype": "ToDo",
			"allocated_to": user,
			"reference_type": instance.context_doctype,
			"reference_name": str(instance.context_docname),
			"description": description,
			"priority": "Medium",
			"status": "Open",
			"date": nowdate(),
			"assigned_by": frappe.session.user,
			"type": "Process",
		}).insert(ignore_permissions=True)

		# Share the document if the assignee lacks permission
		doc = frappe.get_doc(instance.context_doctype, instance.context_docname)
		if not frappe.has_permission(doc=doc, user=user):
			if not frappe.get_system_settings("disable_document_sharing"):
				frappe.share.add(doc.doctype, doc.name, user)

	except Exception:
		frappe.log_error(
			title=f"BPMN: Failed to assign {instance.context_doctype} to {user}",
			message=frappe.get_traceback(),
		)


def remove_frappe_assignment(instance, user: str) -> None:
	"""
	Close the Frappe Assignment (ToDo) on the context document when
	the User Task is completed.

	Sets the ToDo status to "Closed" (task finished) — not "Cancelled"
	(task removed).  Uses ``set_status`` directly instead of ``close()``
	because ``close()`` asserts ``session.user == assignee``, which fails
	when the engine runs under a different user context.

	Failures are logged but never break the workflow.
	"""
	if not (instance.context_doctype and instance.context_docname and user):
		return

	try:
		from frappe.desk.form.assign_to import set_status

		set_status(
			instance.context_doctype,
			instance.context_docname,
			assign_to=user,
			status="Closed",
			ignore_permissions=True,
		)
	except Exception:
		frappe.log_error(
			title=f"BPMN: Failed to close assignment on {instance.context_doctype} for {user}",
			message=frappe.get_traceback(),
		)
