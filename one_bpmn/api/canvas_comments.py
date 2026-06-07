# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _


# ============================================================================
# Processa Canvas Comment API
# ============================================================================


@frappe.whitelist()
def get_canvas_comments(model_name: str) -> list:
	"""
	Fetch all comments for a specific BPMN Process Model.
	"""
	if not model_name:
		return []

	comments = frappe.get_list(
		"Comment",
		filters={
			"reference_doctype": "BPMN Process Model",
			"reference_name": model_name,
			"comment_type": "Comment",
			"is_processa_comment": 1
		},
		fields=[
			"name",
			"reference_name as model",
			"custom_element_id as element_id",
			"content as comment",
			"custom_assigned_to as assigned_to",
			"custom_status as status",
			"owner",
			"custom_is_task as is_task",
			"creation",
		],
		order_by="creation desc",
	)

	if comments:
		user_ids = list(set([c.owner for c in comments] + [c.assigned_to for c in comments if c.assigned_to]))
		user_info = frappe.get_all("User", filters={"name": ["in", user_ids]}, fields=["name", "full_name", "user_image"])
		user_map = {u.name: u for u in user_info}

		# Fetch ToDo statuses and assignees for tasks
		comment_names = [c.name for c in comments if c.is_task]
		todos = {}
		todo_assignees = []
		if comment_names:
			todo_list = frappe.get_all(
				"ToDo",
				filters={"reference_type": "Comment", "reference_name": ["in", comment_names]},
				fields=["reference_name", "status", "allocated_to"]
			)
			for t in todo_list:
				todos[t.reference_name] = {"status": t.status, "allocated_to": t.allocated_to}
				if t.allocated_to:
					todo_assignees.append(t.allocated_to)

		user_ids = list(set([c.owner for c in comments] + [c.assigned_to for c in comments if c.assigned_to] + todo_assignees))
		user_info = frappe.get_all("User", filters={"name": ["in", user_ids]}, fields=["name", "full_name", "user_image"])
		user_map = {u.name: u for u in user_info}

		for c in comments:
			c.author = c.owner  # Legacy alias
			u_info = user_map.get(c.owner, {})
			c.owner_full_name = u_info.get("full_name", c.owner)
			c.owner_image = u_info.get("user_image")

			if c.is_task:
				todo_info = todos.get(c.name)
				if todo_info:
					c.status = "Resolved" if todo_info["status"] == "Closed" else todo_info["status"]
					# Use ToDo's allocated_to as the source of truth for assignment
					c.assigned_to = todo_info["allocated_to"]
				else:
					c.status = None

			if c.assigned_to:
				a_info = user_map.get(c.assigned_to, {})
				c.assigned_to_full_name = a_info.get("full_name", c.assigned_to)

	return comments


@frappe.whitelist()
def post_canvas_comment(
	model_name: str, element_id: str, comment: str, assigned_to: str = None, is_task: int = 0
) -> dict:
	"""
	Create a new comment on the BPMN canvas using standard Comment DocType.
	"""
	if not model_name or not comment:
		frappe.throw(_("Model name and comment are required"))

	doc = frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": "BPMN Process Model",
			"reference_name": model_name,
			"content": comment,
			"is_processa_comment": 1,
			"custom_element_id": element_id,
			"custom_assigned_to": assigned_to,
			"custom_is_task": is_task,
			"custom_status": "Open",
		}
	)
	doc.insert(ignore_permissions=True)

	# If assigned to someone, create a ToDo
	if is_task and assigned_to:
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"allocated_to": assigned_to,
				"description": _("BPMN Task for {0}: {1}").format(model_name, comment),
				"reference_type": "Comment",
				"reference_name": doc.name,
			}
		).insert(ignore_permissions=True)

	# --- Notification Logic ---
	recipients = set()
	if assigned_to:
		recipients.add(assigned_to)

	# Extract plain text mentions (@Full Name or @Email)
	# BPMN Editor currently sends mentions as plain text formatted by BpmnEditor.vue
	if "@" in comment:
		active_users = frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"}, fields=["name", "full_name"])
		for u in active_users:
			if (u.full_name and f"@{u.full_name}" in comment) or f"@{u.name}" in comment:
				recipients.add(u.name)

	# Exclude author from notifications
	recipients.discard(frappe.session.user)

	if recipients:
		from frappe.desk.doctype.notification_log.notification_log import enqueue_create_notification

		# Set type: if it's assigned to someone in the recipients list, use Assignment, else Mention
		notification_type = "Assignment" if assigned_to and assigned_to in recipients else "Mention"

		sender_name = frappe.utils.get_fullname(frappe.session.user)
		subject = _("{0} mentioned you on {1}").format(sender_name, model_name)
		if notification_type == "Assignment":
			subject = _("{0} assigned a task to you on {1}").format(sender_name, model_name)
		process_name = frappe.get_value("BPMN Process Model", model_name, "process_name")
		notification_doc = {
			"type": notification_type,
			"document_type": "BPMN Process Model",
			"document_name": model_name,
			"subject": subject,
			"from_user": frappe.session.user,
			"email_content": comment,
			"link": f"/processa/process/{process_name}"
		}
		enqueue_create_notification(list(recipients), notification_doc)

	# Map fields back for frontend compatibility
	res = doc.as_dict()
	res.model = doc.reference_name
	res.element_id = doc.custom_element_id
	res.comment = doc.content
	res.assigned_to = doc.custom_assigned_to
	res.is_task = doc.custom_is_task
	res.status = doc.custom_status
	res.author = doc.owner

	return res


@frappe.whitelist()
def update_comment_status(name: str, status: str) -> dict:
	"""
	Update the status of a canvas comment by closing/opening its linked ToDo.
	"""
	if not name or not status:
		frappe.throw(_("Comment name and status are required"))

	allowed_statuses = {"Open", "Resolved", "Closed"}
	normalized_status = status.strip()
	if normalized_status not in allowed_statuses:
		frappe.throw(_("Status must be one of: Open, Resolved, Closed"))

	# Check for linked ToDo
	todo_name = frappe.db.get_value("ToDo", {"reference_type": "Comment", "reference_name": name}, "name")
	if not todo_name:
		frappe.throw(_("No ToDo found linked to this comment. Cannot update status."))

	todo_doc = frappe.get_doc("ToDo", todo_name)

	current_user = frappe.session.user
	is_system_manager = "System Manager" in frappe.get_roles(current_user)

	allowed_users = {todo_doc.allocated_to, getattr(todo_doc, "assigned_by", None), todo_doc.owner, "Administrator"}
	if current_user not in allowed_users and not is_system_manager:
		frappe.throw(_("Only the assigned user or assigner can update this task's status"))

	todo_status = "Closed" if normalized_status in ("Resolved", "Closed") else "Open"

	# Update ToDo
	todo_doc.status = todo_status
	todo_doc.save(ignore_permissions=True)

	# Update Comment custom_status for consistency
	doc = frappe.get_doc("Comment", name)
	doc.custom_status = "Resolved" if todo_status == "Closed" else "Open"
	doc.save(ignore_permissions=True)

	# Map back for frontend compatibility
	res = doc.as_dict()
	res.status = doc.custom_status
	return res


@frappe.whitelist()
def delete_canvas_element_assets(model_name: str, element_id: str):
	"""
	Delete all comments and associated ToDos linked to a specific BPMN element.
	Called when a shape is deleted from the canvas.
	"""
	if not model_name or not element_id:
		return

	# Find all standard Comment records linked to this specific element
	comments = frappe.get_all("Comment",
		filters={
			"reference_doctype": "BPMN Process Model",
			"reference_name": model_name,
			"custom_element_id": element_id,
			"is_processa_comment": 1
		},
		fields=["name"]
	)

	for comment in comments:
		# Delete linked ToDos explicitly
		frappe.db.delete("ToDo", {"reference_type": "Comment", "reference_name": comment.name})

		# Delete the comment
		frappe.delete_doc("Comment", comment.name, ignore_permissions=True)

	return {"success": True}


def cleanup_process_model_assets(model_name: str):
	"""
	Background job to cleanup custom assets when a BPMN Process Model is deleted.
	Updated to support the standard Comment DocType.
	"""
	if not model_name:
		return

	# Find all standard Comment records linked to the model
	comments = frappe.get_all("Comment",
		filters={
			"reference_doctype": "BPMN Process Model",
			"reference_name": model_name,
			"is_processa_comment": 1
		},
		fields=["name"]
	)

	for comment in comments:
		# Delete linked ToDos
		frappe.db.delete("ToDo", {"reference_type": "Comment", "reference_name": comment.name})

		# Delete the comment
		frappe.delete_doc("Comment", comment.name, ignore_permissions=True)
