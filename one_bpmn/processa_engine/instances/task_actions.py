# Copyright (c) 2026, one-fm and contributors
"""Act on the tasks of a running instance: complete a user task, list and retry AI tasks, and who may act."""

import json

import frappe
from frappe import _

from one_bpmn.processa_engine.agent_runtime.job_limits import AI_AGENT_JOB_TIMEOUT
from one_bpmn.processa_engine.audit import is_bpmn_super_user
from one_bpmn.processa_engine.instances import starting
from one_bpmn.processa_engine.runtime import active_tasks as runtime_tasks
from one_bpmn.processa_engine.runtime import common as runtime_common


def complete_task(
	instance_name: str,
	task_id: str,
	data: str = None,
) -> dict:
	"""Complete a User Task and advance the workflow, after the checks Frappe's workflow makes:
	the user is assigned, the action is allowed, and the user can write the context document."""
	if not instance_name or not task_id:
		frappe.throw(_("instance_name and task_id are required"))

	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	instance.check_permission("write")

	# The gate is held only while an engine pass runs, so a waiting instance keeps its human tasks completable.
	if frappe.db.get_value(
		"BPMN Process Instance", instance_name, "engine_in_progress"
	):
		frappe.throw(
			_(
				"Instance is processing - an engine pass (AI task or another "
				"action) is currently running. Please retry in a moment."
			)
		)

	parsed_data = {}
	if data:
		parsed_data = frappe.parse_json(data) if isinstance(data, str) else data

	active_row = next(
		(r for r in instance.active_tasks if r.task_id == task_id),
		None,
	)
	if not active_row:
		frappe.throw(_("Task '{0}' not found in the active tasks of this instance.").format(task_id))

	if active_row.status != "Waiting":
		frappe.throw(_("Task '{0}' is not in Waiting status.").format(active_row.task_name or task_id))

	current_user = frappe.session.user

	refusal, approved_ctc_name = _task_authorization(instance, active_row, current_user)
	if refusal:
		frappe.throw(refusal, frappe.PermissionError)

	submitted_action = parsed_data.get("action", "")
	allowed_actions_str = active_row.task_actions or ""

	# task_actions is a JSON list of {"action": ...} or a legacy comma-separated string.
	_trimmed = allowed_actions_str.strip()
	if _trimmed.startswith("["):
		try:
			_parsed_actions = json.loads(_trimmed)
			allowed_actions = [
				a.get("action", "").strip()
				for a in (_parsed_actions if isinstance(_parsed_actions, list) else [])
				if isinstance(a, dict) and a.get("action", "").strip()
			]
		except (TypeError, ValueError):
			frappe.log_error(
				title="BPMN complete_task: malformed task_actions JSON",
				message=f"task_actions={_trimmed!r} on instance {instance_name}",
			)
			allowed_actions = [a.strip() for a in _trimmed.split(",") if a.strip()]
	else:
		allowed_actions = [a.strip() for a in _trimmed.split(",") if a.strip()]

	if allowed_actions:
		if not submitted_action:
			frappe.throw(
				_("An action is required. Valid actions: {0}").format(", ".join(allowed_actions)),
				frappe.ValidationError,
			)
		if submitted_action not in allowed_actions:
			frappe.throw(
				_("Action '{0}' is not allowed. Valid actions: {1}").format(
					submitted_action, ", ".join(allowed_actions)
				),
				frappe.ValidationError,
			)

	if instance.context_doctype and instance.context_docname:
		if not frappe.has_permission(
			instance.context_doctype, "write", instance.context_docname, user=current_user
		):
			frappe.throw(
				_("You do not have write permission on {0} {1}.").format(
					instance.context_doctype, instance.context_docname
				),
				frappe.PermissionError,
			)

	# Rows for a question a remote A2A agent asked: the answer goes back over A2A, no engine pass here.
	if task_id.startswith(runtime_common.A2A_HUMAN_PREFIX):
		instance.complete_a2a_human_task(task_id, parsed_data)
		instance.reload()
		return {
			"instance": instance_name,
			"status": instance.status,
			"queued": True,
			"waiting_for_ai": instance.waiting_for_ai,
			"waiting_for_human": instance.waiting_for_human,
			"active_tasks": instance.get_active_tasks_summary(),
		}

	# Rows a suspended agent spawned: the output goes on its checkpoint and its resume job is queued.
	if task_id.startswith(runtime_common.AI_HUMAN_PREFIX):
		instance.complete_ai_human_task(task_id, parsed_data)
		instance.reload()
		return {
			"instance": instance_name,
			"status": instance.status,
			"queued": True,
			"waiting_for_ai": instance.waiting_for_ai,
			"waiting_for_human": instance.waiting_for_human,
			"active_tasks": instance.get_active_tasks_summary(),
		}

	# The engine pass runs inline; AI tasks it reaches are parked and only their model work is queued.
	frappe.db.set_value(
		"BPMN Process Instance",
		instance_name,
		"engine_in_progress",
		1,
		update_modified=False,
	)

	_complete_task_job(
		instance_name=instance_name,
		task_id=task_id,
		data=parsed_data,
		run_as_user=current_user,
		approved_ctc_name=approved_ctc_name,
	)
	instance.reload()
	return {
		"instance": instance_name,
		"status": instance.status,
		"queued": False,
		"waiting_for_ai": instance.waiting_for_ai,
		"active_tasks": instance.get_active_tasks_summary(),
	}


def get_parked_ai_tasks(instance_name: str) -> list:
	"""The parked AI units of an instance, as {kind, task_id, bpmn_id, label, since}.
	The diagram marks them as waiting for AI and the manual retry button re-queues them."""
	if not instance_name:
		frappe.throw(_("instance_name is required"))
	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	instance.check_permission("read")
	try:
		return instance.get_parked_ai_units()
	except Exception:
		frappe.log_error(
			title=f"BPMN get_parked_ai_tasks failed: {instance_name}",
			message=frappe.get_traceback(),
		)
		return []


def get_suspended_ai_tasks(instance_name: str) -> list:
	"""The agents of this instance suspended waiting for a person, as {bpmn_id, human_task_id, human_task_label}."""
	if not instance_name:
		frappe.throw(_("instance_name is required"))

	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	instance.check_permission("read")

	runs = frappe.get_list(
		"AI Agent Run",
		filters={"instance": instance_name, "status": "Suspended"},
		fields=["bpmn_id", "pending_human_task"],
	)
	labels = {
		row.task_id: row.task_name
		for row in instance.active_tasks
		if str(row.task_id).startswith(runtime_common.AI_HUMAN_PREFIX)
	}
	return [
		{
			"bpmn_id": r.bpmn_id,
			"human_task_id": r.pending_human_task or "",
			"human_task_label": labels.get(r.pending_human_task, ""),
		}
		for r in runs
	]


def retry_ai_task(instance_name: str, task_id: str, kind: str = "service_task") -> dict:
	"""Queue a parked AI unit again after its automatic retries ran out, or re-run a stalled selector decision.
	task_id is the parked task UUID (service_task) or the ad-hoc subprocess bpmn id (adhoc_decision)."""
	if not instance_name or not task_id:
		frappe.throw(_("instance_name and task_id are required"))
	if kind not in ("service_task", "adhoc_decision"):
		frappe.throw(_("kind must be 'service_task' or 'adhoc_decision'"))

	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	instance.check_permission("write")

	if instance.status not in ("Errored", "Active"):
		frappe.throw(
			_('Instance "{0}" is {1} - only Errored or Active instances can retry an AI task.').format(
				instance_name, instance.status
			)
		)

	frappe.db.set_value(
		"BPMN Process Instance",
		instance_name,
		{"status": "Active", "waiting_for_ai": 1},
		update_modified=False,
	)

	frappe.enqueue(
		"one_bpmn.processa_engine.runtime.ai_jobs.run_parked_ai_task",
		queue="bpmn_ai_agent",
		timeout=AI_AGENT_JOB_TIMEOUT,
		enqueue_after_commit=True,
		# Manual retries are deliberate, so never dedup against a stale job id.
		job_id=f"bpmn-ai-{instance_name}-{task_id}-manual-{frappe.generate_hash(length=6)}",
		instance_name=instance_name,
		kind=kind,
		task_id=task_id,
		run_as_user=frappe.session.user,
		attempt=0,
	)

	return {"instance": instance_name, "status": "queued", "kind": kind, "task_id": task_id}


def _complete_task_job(
	instance_name: str,
	task_id: str,
	data: dict = None,
	run_as_user: str = None,
	approved_ctc_name: str = None,
):
	"""The engine pass after complete_task has validated the action, run inline as the acting user.
	AI tasks the pass reaches are parked and continue on the bpmn_ai_agent worker."""
	# set_user wipes session data, which a web request would write back under the browser's sid.
	if run_as_user and run_as_user != frappe.session.user:
		frappe.set_user(run_as_user)

	# The row lock serializes engine passes on one instance.
	instance = frappe.get_doc("BPMN Process Instance", instance_name, for_update=True)
	try:
		instance.advance(task_id=task_id, data=data or {})

		if approved_ctc_name:
			try:
				starting.send_message(
					message_name="Active Task is Completed",
					context_doctype="Contingency Task Completion",
					context_docname=approved_ctc_name,
					payload=json.dumps({
						"ctc_name": approved_ctc_name,
						"actioned_doctype": instance.context_doctype,
						"actioned_docname": instance.context_docname,
						"actioned_by": run_as_user or frappe.session.user,
					}),
				)
			except Exception as exc:
				frappe.log_error(
					title="BPMN CTC expiry message failed",
					message=str(exc),
				)
	except frappe.ValidationError:
		# An engine-level validation (the task was completed elsewhere) is not an instance failure.
		frappe.log_error(
			title="BPMN complete_task job: validation error",
			message=frappe.get_traceback(),
		)
	except frappe.PermissionError:
		# The user sees what they lack; the request rollback leaves the task waiting for a retry.
		raise
	except Exception:
		frappe.db.set_value("BPMN Process Instance", instance_name, "status", "Errored")
		frappe.log_error(
			title="BPMN complete_task failed",
			message=frappe.get_traceback(),
		)
	finally:
		frappe.db.set_value(
			"BPMN Process Instance",
			instance_name,
			"engine_in_progress",
			0,
			update_modified=False,
		)

		# Every user viewing the instance page refreshes.
		frappe.publish_realtime(
			"bpmn_instance_updated",
			{
				"instance_name": instance_name,
				"status": frappe.db.get_value("BPMN Process Instance", instance_name, "status"),
				"context_doctype": instance.context_doctype or "",
				"context_docname": instance.context_docname or "",
			},
			after_commit=True,
			user="all",
		)

		if instance.context_doctype and instance.context_docname:
			frappe.publish_realtime(
				"doc_update",
				{
					"modified": str(frappe.utils.now_datetime()),
					"doctype": instance.context_doctype,
					"name": instance.context_docname,
				},
				doctype=instance.context_doctype,
				docname=instance.context_docname,
				after_commit=True,
			)


def get_active_bpmn_tasks(doctype: str, docname: str) -> list:
	"""The Waiting User Task actions on a document, for the buttons bpmn_form_actions.js adds on each form refresh.
	Each row names the instance, task, actions, assignee and whether the current user may act."""
	if not doctype or not docname:
		return []

	instance_names = frappe.get_all(
		"BPMN Process Instance",
		filters={
			"context_doctype": doctype,
			"context_docname": docname,
			"status": "Active",
		},
		pluck="name",
	)

	if not instance_names:
		return []

	result = []

	for instance_name in instance_names:
		try:
			instance = frappe.get_doc("BPMN Process Instance", instance_name)

			for row in instance.active_tasks:
				if row.status != "Waiting":
					continue

				# A question an agent asked is answered in its own panel, not from the Actions menu.
				if (row.task_type or "") == "AI Human Task":
					continue

				actions_str = runtime_tasks.resolve_task_actions(row)
				actions_detail = runtime_tasks.resolve_task_actions_detail(row)

				result.append(
					{
						"instance_name": instance_name,
						"task_id": row.task_id,
						"task_name": row.task_name or "",
						"task_actions": actions_str,
						"task_actions_detail": actions_detail,
						"assigned_user": row.assigned_user or "",
						"assigned_role": row.assigned_role or "",
						"can_action": not _task_authorization(instance, row, frappe.session.user)[0],
					}
				)

		except Exception:
			frappe.log_error(
				title=f"get_active_bpmn_tasks failed for instance {instance_name}",
				message=frappe.get_traceback(),
			)

	return result


def _task_authorization(instance, row, user: str) -> tuple[str | None, str | None]:
	"""Why ``user`` may not complete this Waiting task, or None; and the approved CTC that lets them.
	Assignees and their relievers may act, and so may a super user or the holder of an approved Contingency Task Completion."""
	# Imported lazily: assignment.py pulls in engine.py, which is fragile across SpiffWorkflow versions.
	from one_bpmn.processa_engine.assignment import split_users, task_actors

	super_user = is_bpmn_super_user(user)
	assigned_users = split_users(row.assigned_user or "")
	approved_ctc_name = None

	if assigned_users and user not in task_actors(row) and not super_user:
		if instance.context_doctype and instance.context_docname:
			from frappe.query_builder import DocType

			CTC = DocType("Contingency Task Completion")
			ctc_result = (
				frappe.qb.from_(CTC)
				.select(CTC.name)
				.where(CTC.context_doctype == instance.context_doctype)
				.where(CTC.context_docname == instance.context_docname)
				.where(CTC.process_owner_user == user)
				# The process sets workflow_state via apply_workflow and status via update_field.
				.where((CTC.workflow_state == "Approved") | (CTC.status == "Approved"))
				.where(CTC.status != "Expired")
				.where(CTC.docstatus == 1)
				.limit(1)
			).run()
			approved_ctc_name = ctc_result[0][0] if ctc_result else None

		if not approved_ctc_name:
			assignee_names = ", ".join(frappe.utils.get_fullname(u) or u for u in assigned_users)
			return (
				_("You are not authorized to complete this task. It is assigned to {0}.").format(assignee_names),
				None,
			)

	assigned_role = row.assigned_role or ""
	if assigned_role and not super_user and assigned_role not in frappe.get_roles(user):
		return _("Only users with the role '{0}' can complete this task.").format(assigned_role), None

	return None, approved_ctc_name
