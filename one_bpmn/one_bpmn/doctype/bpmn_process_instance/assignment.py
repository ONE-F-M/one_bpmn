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


def _decode_html_attr(value: str) -> str:
	"""Decode a base64-encoded HTML attribute back to its original HTML.

	The BPMN editor stores HTML content (notifyAssigneeBody, emailBody) as
	base64 in XML attributes to prevent XML parse failures from raw HTML
	tags like ``<p>``.  This helper decodes them at runtime.

	Gracefully handles legacy values that were stored as raw HTML.
	"""
	if not value:
		return ""
	import base64
	try:
		return base64.b64decode(value).decode("utf-8")
	except Exception:
		# Not valid base64 — assume legacy raw HTML
		return value


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


def _send_assignee_notification(instance, user: str, task_name: str, task_cfg: dict) -> None:
	"""
	Send a custom HTML email notification to the assignee when
	``notifyAssignee`` is checked and ``notifyAssigneeBody`` is configured
	on the BPMN User Task.

	The HTML body supports Jinja2 rendering with ``{{ doc }}``,
	``{{ instance }}``, and ``{{ frappe }}`` as template context variables.

	Sent via ``one_fm.processor.sendemail`` with ``is_external_mail=True`` —
	"Notify Assignee" is an explicit per-task opt-in in the BPMN diagram, so
	it must NOT be filtered by the recipient's general notification
	preferences.  Passing ``is_external_mail=True`` bypasses the
	``is_email_notifications_allowed`` recipient filter that otherwise drops
	any user who isn't an Active Employee with their user_id set as the
	Company Email preferred contact — the filter that silently suppressed
	this notification.

	Non-fatal: failures are logged but never break the workflow.
	"""
	body_html = _decode_html_attr(task_cfg.get("notifyAssigneeBody") or "").strip()
	if not body_html:
		return

	# ── Resolve the context document for Jinja rendering ──────────
	doc = frappe._dict()
	if instance.context_doctype and instance.context_docname:
		try:
			doc = frappe.get_doc(instance.context_doctype, instance.context_docname)
		except Exception:
			pass

	jinja_ctx = {
		"doc": doc,
		"instance": instance,
		"frappe": frappe,
	}

	# Render the HTML body through Jinja2
	try:
		rendered_body = frappe.render_template(body_html, jinja_ctx)
	except Exception:
		rendered_body = body_html  # fall back to raw HTML on template error

	subject = _("BPMN Task: \"{0}\"").format(task_name or "User Task")

	try:
		from one_fm.processor import sendemail as onefm_sendemail

		onefm_sendemail(
			recipients=[user],
			subject=subject,
			sender=None,
			header=[subject],
			message=rendered_body,
			reference_doctype=instance.context_doctype or instance.doctype,
			reference_name=instance.context_docname or instance.name,
			is_external_mail=True,
		)
	except ImportError:
		frappe.sendmail(
			recipients=[user],
			subject=subject,
			message=rendered_body,
			reference_doctype=instance.context_doctype or instance.doctype,
			reference_name=instance.context_docname or instance.name,
			now=False,
		)


def add_frappe_assignment(instance, user: str, task_name: str = "", task_cfg: dict = None) -> None:
	"""
	Create a Frappe Assignment (ToDo) on the context document for the
	resolved user.  This makes the assignment visible in Frappe's sidebar
	and the user's ToDo list.

	Creates the ToDo directly with ``type="Process"`` so that the OneFM
	notification system skips the standard assignment email/bell — Processa
	handles notifications for process tasks independently.

	Respects the ``notifyAssignee`` setting from the BPMN diagram:
	  - If ``notifyAssignee`` is ``"true"``, a custom email notification
	    is sent using the ``notifyAssigneeBody`` HTML template (Jinja2).
	    The HTML body is rendered with ``{{ doc }}``, ``{{ instance }}``,
	    and ``{{ frappe }}`` context variables.
	  - Otherwise, no notification is sent (``notify=0``).

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

		# Determine notification settings from BPMN diagram config
		cfg = task_cfg or {}
		notify_assignee = cfg.get("notifyAssignee") == "true"

		# The ToDo description is always the standard BPMN task message.
		# notifyAssigneeBody is for email notification only — NOT the ToDo.
		description = _('BPMN Task: "{0}" on instance {1}').format(
			task_name or "User Task", instance.name
		)

		# Create the ToDo directly with type="Process" instead of using
		# assign_to.add(), which always fires notify_assignment.  The
		# ToDo's on_update hook still updates the _assign sidebar field.
		from frappe.utils import nowdate

		todo = frappe.get_doc({
			"doctype": "ToDo",
			"allocated_to": user,
			"reference_type": instance.context_doctype,
			"reference_name": str(instance.context_docname),
			"description": description,
			"priority": "Medium",
			"status": "Open",
			"date": nowdate(),
			"assigned_by": (frappe.session.user or getattr(instance, "initiated_by", None) or "Administrator"),
		}).insert(ignore_permissions=True)

		# Force type="Process" AFTER insert — Frappe's ToDo validate hook
		# resets the type field to its default ("Action"), so setting it in
		# the dict above doesn't stick.  db_set bypasses controller hooks.
		frappe.db.set_value("ToDo", todo.name, "type", "Process")

		# Share the document if the assignee lacks permission
		doc = frappe.get_doc(instance.context_doctype, instance.context_docname)
		if not frappe.has_permission(doc=doc, user=user):
			if not frappe.get_system_settings("disable_document_sharing"):
				frappe.share.add(doc.doctype, doc.name, user)

		# ── Send custom HTML notification email ──────────────────────
		# Sent AFTER the ToDo is created so the assignment is visible
		# even if the email fails.  Non-fatal: logged but never breaks.
		if notify_assignee:
			try:
				_send_assignee_notification(instance, user, task_name, cfg)
			except Exception:
				frappe.log_error(
					title=f"BPMN: Assignee notification email failed for {user}",
					message=frappe.get_traceback(),
				)
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
