# Copyright (c) 2026, one-fm and contributors
"""Resolve task assignees and manage Frappe ToDos for BPMN user tasks."""

import json
from typing import TYPE_CHECKING

import frappe
from frappe import _

from processa.processa_engine import engine as bpmn_engine
from processa.processa_engine.dispatch.common import split_config
from processa.processa_engine.engine import Task

if TYPE_CHECKING:
	from processa.processa_engine.doctype.bpmn_process_instance.bpmn_process_instance import (
		BPMNProcessInstance,
	)


def split_users(value: str) -> list:
	"""Split a comma-separated ``assigned_user`` into trimmed, unique user names in order.
	Table Field mode stores several users comma-joined, so read ``assigned_user`` as a set only through this."""
	return list(dict.fromkeys(split_config(value)))


def decode_html_attr(value: str) -> str:
	"""Decode a base64 HTML attribute written by the BPMN editor; a value that is not base64 is returned as is."""
	if not value:
		return ""
	import base64
	try:
		return base64.b64decode(value).decode("utf-8")
	except Exception:
		return value


def get_reliever_if_on_leave(user: str, pairs: list = None) -> str:
	"""Return the reliever on *user*'s approved leave covering today, else *user*.
	Each redirect is appended to *pairs* as (relieved, reliever) so the row records the original owner."""
	if not user:
		return user

	try:
		reliever_user = _current_reliever(user)
		if not reliever_user:
			return user
		if pairs is not None:
			pairs.append((user, reliever_user))
		return reliever_user
	except Exception:
		frappe.log_error(
			title="BPMN: Leave reliever lookup failed",
			message=frappe.get_traceback(),
		)
		return user


def _current_reliever(user: str) -> str | None:
	"""The reliever named on *user*'s approved leave covering today, or None."""
	today = frappe.utils.today()
	employee = frappe.db.get_value(
		"Employee",
		{"user_id": user, "status": ["in", ["Active", "Vacation", "Not Returned from Leave"]]},
		"name",
	)
	if not employee:
		return None
	return frappe.db.get_value(
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


def task_actors(row) -> set:
	"""Everyone who may action a Waiting task row: its assignees, the recorded relieved/reliever
	pair, and the live reliever of any assignee or relieved user."""
	actors = set()
	for field in (row.assigned_user, row.relieved_user, row.reliever_user):
		actors.update(split_users(field or ""))
	owners = set(split_users(row.assigned_user or "")) | set(split_users(row.relieved_user or ""))
	for owner in owners:
		reliever = _current_reliever(owner)
		if reliever:
			actors.add(reliever)
	return actors


def resolve_assignee(
	instance: "BPMNProcessInstance", task: Task, extensions: dict
) -> tuple[str, list[tuple[str, str]]]:
	"""resolve_assignment with the user task config in *extensions*, for an instance not yet started.
	Returns the assignee and the (relieved, reliever) pairs."""
	instance._user_task_extensions = extensions
	return resolve_assignment(instance, task), instance._relief_pairs


def resolve_assignment(instance, task) -> str:
	"""Resolve a UserTask's assignee by ``assigneeMode``: User, DocField, Round Robin, Load Balancing or Table Field.
	Table Field returns a comma-joined list; an assignee on leave today is swapped for their reliever.
	Relief pairs are left on ``instance._relief_pairs``; returns "" when unresolvable."""
	extensions = getattr(instance, "_user_task_extensions", {})
	bpmn_id = getattr(task.task_spec, "bpmn_id", None) or ""
	task_cfg = extensions.get(bpmn_id, {})

	# Reset per call: the caller reads it next to fill the row's relief fields.
	pairs = []
	instance._relief_pairs = pairs

	mode = task_cfg.get("assigneeMode", "")

	if mode == "User":
		return get_reliever_if_on_leave(task_cfg.get("assigneeUser", ""), pairs)

	if mode == "DocField":
		doctype = task_cfg.get("targetDoctype") or instance.context_doctype
		docfield = task_cfg.get("assigneeDocfield", "")
		if doctype and docfield and instance.context_docname:
			try:
				user = frappe.db.get_value(doctype, instance.context_docname, docfield)
				return get_reliever_if_on_leave(user or "", pairs)
			except Exception:
				return ""
		return ""

	# Rotation state lives on the Process Model so it continues across instances.
	if mode == "Round Robin":
		users = split_config(task_cfg.get("assigneeUsers"))
		if not users:
			return ""

		try:
			model = frappe.get_doc("BPMN Process Model", instance.process_model)
			rr_state = frappe.parse_json(model.round_robin_state or "{}")
			task_state = rr_state.get(bpmn_id, {"next_idx": 0, "last_user": ""})

			next_idx = int(task_state.get("next_idx", 0))
			assignee = users[next_idx % len(users)]
			next_idx += 1

			task_state["next_idx"] = next_idx
			task_state["last_user"] = assignee
			rr_state[bpmn_id] = task_state
			model.round_robin_state = frappe.as_json(rr_state)
			model.save(ignore_permissions=True)  # engine writes round-robin state on the model

			# Best-effort patch of roundRobinLastUser in the BPMN XML for the editor.
			try:
				_update_round_robin_in_model(instance.process_model, bpmn_id, assignee)
			except Exception:
				pass

			return get_reliever_if_on_leave(assignee, pairs)
		except Exception:
			frappe.log_error(
				title="BPMN: Round Robin assignment failed",
				message=frappe.get_traceback(),
			)
			return get_reliever_if_on_leave(users[0], pairs) if users else ""

	# Fewest Waiting rows of this same task across all instances wins; ties go to list order.
	if mode == "Load Balancing":
		users = split_config(task_cfg.get("assigneeUsers"))
		if not users:
			return ""

		try:
			# The display name identifies the same task across instances of this model.
			task_name = bpmn_engine.get_task_display_name(task)

			loads = {}
			for user in users:
				loads[user] = frappe.db.count(
					"BPMN Active Task",
					filters={
						"assigned_user": user,
						"task_name": task_name,
						"status": "Waiting",
					},
				)

			minimum = min(loads.values())
			assignee = next(u for u in users if loads[u] == minimum)
			return get_reliever_if_on_leave(assignee, pairs)

		except Exception:
			frappe.log_error(
				title="BPMN: Load Balancing assignment failed",
				message=frappe.get_traceback(),
			)
			return get_reliever_if_on_leave(users[0], pairs) if users else ""

	if mode == "Table Field":
		doctype = task_cfg.get("targetDoctype") or instance.context_doctype
		table_field = task_cfg.get("assigneeTableField", "")
		user_field = task_cfg.get("assigneeTableUserField", "") or "user"
		if not (doctype and table_field and instance.context_docname):
			return ""
		try:
			parent_doc = frappe.get_doc(doctype, instance.context_docname)
			rows = parent_doc.get(table_field) or []
			users = []
			seen = set()
			for row in rows:
				u = row.get(user_field)
				if u and u not in seen:
					seen.add(u)
					users.append(get_reliever_if_on_leave(u, pairs))
			return ",".join(users)
		except Exception:
			frappe.log_error(
				title="BPMN: Table Field assignment failed",
				message=frappe.get_traceback(),
			)
			return ""

	return ""


def _update_round_robin_in_model(model_name: str, task_bpmn_id: str, last_user: str) -> None:
	"""Record the last round-robin assignee on the model's state and on the User Task in its XML."""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	try:
		model = frappe.get_doc("BPMN Process Model", model_name)
		state = json.loads(model.round_robin_state or "{}")
		if task_bpmn_id not in state:
			state[task_bpmn_id] = {"next_idx": 0, "last_user": ""}
		state[task_bpmn_id]["last_user"] = last_user
		model.round_robin_state = json.dumps(state)

		if model.bpmn_xml:
			try:
				_ET.register_namespace("", BPMN_NS)
				_ET.register_namespace("spiffworkflow", SPIFF_NS)
				root = _ET.fromstring(model.bpmn_xml.strip().encode("utf-8"))
				attr_key = f"{{{SPIFF_NS}}}roundRobinLastUser"
				for el in root.iter(f"{{{BPMN_NS}}}userTask"):
					if el.get("id") == task_bpmn_id:
						el.set(attr_key, last_user)
						break
				model.bpmn_xml = _ET.tostring(root, encoding="unicode", xml_declaration=False)
			except Exception:
				pass  # the state field is the record; the XML copy is only for the editor

		model.save(ignore_permissions=True)  # engine writes round-robin state on the model
	except Exception:
		frappe.log_error(
			title="BPMN: round-robin state update failed",
			message=frappe.get_traceback(),
		)


def add_frappe_assignment(instance, user: str, task_name: str = "") -> None:
	"""Create an Open ToDo of type Process on the context document for *user*, unless one exists.
	Inserted directly, not through assign_to.add, so Frappe's assignment email is skipped.
	Failures are logged and never break the workflow."""
	if not (instance.context_doctype and instance.context_docname and user):
		return

	try:
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

		# notifyAssigneeBody is for the email only, never the ToDo description.
		description = _('BPMN Task: "{0}" on instance {1}').format(
			task_name or "User Task", instance.name
		)

		from frappe.utils import nowdate

		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"allocated_to": user,
				"reference_type": instance.context_doctype,
				"reference_name": str(instance.context_docname),
				"description": description,
				"priority": "Medium",
				"status": "Open",
				"date": nowdate(),
				"assigned_by": (frappe.session.user or getattr(instance, "initiated_by", None) or "Administrator"),
			}
		).insert(ignore_permissions=True)  # engine creates the ToDo for the assignee

		# ToDo validate resets type to Action, so set it after insert.
		frappe.db.set_value("ToDo", todo.name, "type", "Process")

		doc = frappe.get_doc(instance.context_doctype, instance.context_docname)
		if not frappe.has_permission(doc=doc, user=user):
			if not frappe.get_system_settings("disable_document_sharing"):
				frappe.share.add(doc.doctype, str(doc.name), user)

		try:
			if frappe.get_cached_value("User", user, "follow_assigned_documents"):
				from frappe.desk.like import follow_document
				follow_document(instance.context_doctype, instance.context_docname, user)
		except Exception:
			pass

	except Exception:
		frappe.log_error(
			title=f"BPMN: Failed to assign {instance.context_doctype} to {user}",
			message=frappe.get_traceback(),
		)



def notify_task_assignee(
	instance, user: str, task_name: str, task_cfg: dict | None,
	task_id: str = "", bpmn_id: str = "",
) -> None:
	"""Email the assignee of a User Task with Notify Assignee ticked; failures are logged, never raised.
	Kept apart from add_frappe_assignment: one ToDo per person per instance, but one email per notifying task."""
	cfg = task_cfg or {}
	if cfg.get("notifyAssignee") != "true":
		return
	if not (instance.context_doctype and instance.context_docname and user):
		return
	try:
		from processa.processa_engine.notifications.composer import compose_and_send_task_email

		compose_and_send_task_email(
			instance=instance,
			user=user,
			task_name=task_name,
			task_id=task_id,
			bpmn_id=bpmn_id,
			task_cfg=cfg,
		)
	except Exception:
		frappe.log_error(
			title=f"BPMN: Assignee notification email failed for {user}",
			message=frappe.get_traceback(),
		)


def remove_frappe_assignment(instance, user: str, status: str = "Closed") -> None:
	"""Set *user*'s ToDo on the context document to *status*, Closed by default; failures are logged.
	Uses set_status, not close(), because close() requires session.user to be the assignee.
	A process can pass another status through the ``todo_close_status`` task data hint."""
	if not (instance.context_doctype and instance.context_docname and user):
		return

	try:
		from frappe.desk.form.assign_to import set_status

		set_status(
			instance.context_doctype,
			instance.context_docname,
			assign_to=user,
			status=status,
			ignore_permissions=True,  # engine closes the assignee's ToDo
		)
	except Exception:
		frappe.log_error(
			title=f"BPMN: Failed to close assignment on {instance.context_doctype} for {user}",
			message=frappe.get_traceback(),
		)


def _swap_user(value: str, old_user: str, new_user: str) -> str:
	"""Replace *old_user* with *new_user* in a comma-separated assignee list, leaving the others."""
	users = split_users(value)
	if old_user not in users or new_user in users:
		return value
	return ",".join(new_user if u == old_user else u for u in users)


def restore_tasks_on_return(user: str) -> int:
	"""Hand every Waiting task a reliever holds back to *user*, who is back from leave, and re-point its ToDo.
	The relieved/reliever pair stays on the row, and a row already handed back is skipped.
	Returns the number of rows handed back."""
	if not user:
		return 0

	rows = frappe.db.sql(  # FIND_IN_SET over a comma list, parameterised
		"""
		SELECT t.name, t.parent, t.assigned_user, t.relieved_user, t.reliever_user
		FROM `tabBPMN Active Task` t
		INNER JOIN `tabBPMN Process Instance` i ON i.name = t.parent
		WHERE t.status = 'Waiting'
		  AND i.status = 'Active'
		  AND FIND_IN_SET(%s, REPLACE(t.relieved_user, ' ', '')) > 0
		""",
		user,
		as_dict=True,
	)

	restored = 0
	for row in rows:
		relieved = split_users(row.relieved_user)
		relievers = split_users(row.reliever_user)
		if user not in relieved:
			continue
		idx = relieved.index(user)
		if idx >= len(relievers):
			continue
		reliever = relievers[idx]

		new_assigned = _swap_user(row.assigned_user, reliever, user)
		if new_assigned == row.assigned_user:
			continue  # already back with them, or the reliever has since moved on

		frappe.db.set_value("BPMN Active Task", row.name, "assigned_user", new_assigned)

		try:
			instance = frappe.get_doc("BPMN Process Instance", row.parent)
			remove_frappe_assignment(instance, reliever, status="Cancelled")
			add_frappe_assignment(
				instance,
				user,
				task_name=frappe.db.get_value("BPMN Active Task", row.name, "task_name") or "",
			)
		except Exception:
			frappe.log_error(
				title=f"BPMN: Could not re-point assignment on {row.parent} to {user}",
				message=frappe.get_traceback(),
			)

		restored += 1

	return restored
