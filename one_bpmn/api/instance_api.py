# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _

from one_bpmn.api.utils import _is_bpmn_super_user


@frappe.whitelist()
def list_process_instances(
	filters=None,
	limit_start=0,
	limit_page_length=20,
	order_by="creation desc",
	pending_action_by=None,
) -> list:
	"""
	List BPMN process instances with their active tasks joined as 'current_step'.

	``pending_action_by`` is not a field on the instance — it is resolved from
	the active task rows (see ``_instances_pending_on``) and narrows the list to
	Active instances that user still has to act on.
	"""

	if isinstance(filters, str):
		filters = json.loads(filters)

	if isinstance(limit_start, str):
		limit_start = int(limit_start)
	if isinstance(limit_page_length, str):
		limit_page_length = int(limit_page_length)

	if pending_action_by:
		pending = _instances_pending_on(pending_action_by)
		if not pending:
			return []
		# A Waiting row can outlive its instance (Cancelled/Errored runs keep
		# their rows), so pin to Active — nothing else is actionable.
		if isinstance(filters, list):
			filters = filters + [["name", "in", pending], ["status", "=", "Active"]]
		else:
			filters = dict(filters or {})
			filters["name"] = ["in", pending]
			filters["status"] = "Active"

	instances = frappe.get_list(
		"BPMN Process Instance",
		fields=[
			"name",
			"process_model",
			"status",
			"waiting_for_ai",
			"context_doctype",
			"context_docname",
			"started_at",
			"initiated_by",
		],
		filters=filters,
		limit_start=limit_start,
		limit_page_length=limit_page_length,
		order_by=order_by,
	)

	if instances:
		instance_names = [d.name for d in instances]
		tasks = frappe.get_all(
			"BPMN Active Task",
			filters={
				"parent": ["in", instance_names],
				"parenttype": "BPMN Process Instance",
				"status": ["in", ["Waiting", ""]],
			},
			fields=["parent", "task_name", "status"],
		)

		from collections import defaultdict

		task_map = defaultdict(list)
		for t in tasks:
			task_map[t.parent].append(t.task_name)

		for d in instances:
			d.current_step = ", ".join(task_map.get(d.name, []))

		# Active instances with no waiting USER task still have a current
		# position — a running automation, an inner subprocess task, or an
		# ad-hoc subprocess waiting on its next selection. Derive it from
		# the engine state so the column never goes silently blank.
		needs_derivation = [
			d.name for d in instances if d.status == "Active" and not d.current_step
		]
		if needs_derivation:
			states = frappe.get_all(
				"BPMN Process Instance",
				filters={"name": ["in", needs_derivation]},
				fields=["name", "workflow_state"],
			)
			derived = {row.name: _derive_current_step(row.workflow_state) for row in states}
			for d in instances:
				if not d.current_step:
					d.current_step = derived.get(d.name, "")

	return instances


def _instances_pending_on(user: str) -> list:
	"""Names of process instances holding a Waiting task ``user`` must act on.

	Mirrors the authorization rule in ``complete_user_task``: a task reaches
	someone either because

	1. ``assigned_user`` names them. In multi-assignee ("Table Field") mode that
	   field is a comma-joined list, so membership goes through ``split_users``
	   — ``=`` would miss those rows, and a bare LIKE would match a user whose
	   email is a substring of someone else's. The LIKE is only a coarse
	   pre-filter; the real test happens in Python below.
	2. ``assigned_role`` names a role they hold and no user has been resolved
	   onto the row — an unclaimed role task is pending on every member. Once
	   ``assigned_user`` is set, that field alone decides who owes the action.
	"""
	# Imported lazily for the same reason as in complete_user_task: assignment.py
	# pulls in engine.py, which is fragile across SpiffWorkflow versions.
	from one_bpmn.one_bpmn.doctype.bpmn_process_instance.assignment import split_users

	roles = frappe.get_roles(user)

	or_filters = {"assigned_user": ["like", f"%{user}%"]}
	if roles:
		or_filters["assigned_role"] = ["in", roles]

	rows = frappe.get_all(
		"BPMN Active Task",
		filters={"parenttype": "BPMN Process Instance", "status": "Waiting"},
		or_filters=or_filters,
		fields=["parent", "assigned_user", "assigned_role"],
	)

	role_set = set(roles)
	return list(
		{
			row.parent
			for row in rows
			if user in split_users(row.assigned_user)
			or (not (row.assigned_user or "").strip() and row.assigned_role in role_set)
		}
	)


def _derive_current_step(workflow_state: str) -> str:
	"""Name the engine's current position from serialized state: active
	non-internal tasks, descending into subprocesses. A container with no
	active inner task (an ad-hoc subprocess whose heads are all parked —
	e.g. the AI selector declined or stalled) is reported as awaiting
	selection instead of blank."""
	try:
		state = json.loads(workflow_state or "{}")
	except Exception:
		return ""
	if not state:
		return ""

	ACTIVE_STATES = {8, 16, 32}  # WAITING, READY, STARTED
	subprocesses = state.get("subprocesses") or {}
	subprocess_specs = state.get("subprocess_specs") or {}

	def display(spec_map, spec_name):
		spec_data = (spec_map or {}).get(spec_name) or {}
		return spec_data.get("bpmn_name") or spec_data.get("description") or spec_name

	def active_tasks(tasks_dict):
		for task_id, t in (tasks_dict or {}).items():
			spec = t.get("task_spec") or ""
			if not spec or spec in ("Start", "End"):
				continue
			if spec.endswith(".EndJoin") or ".BoundaryEvent" in spec:
				continue
			if (t.get("state") or 0) in ACTIVE_STATES:
				yield task_id, spec

	def describe(tasks_dict, spec_map):
		labels = []
		for task_id, spec_name in active_tasks(tasks_dict):
			sub = subprocesses.get(task_id)
			if sub is None:
				labels.append(display(spec_map, spec_name))
				continue
			child_specs = (subprocess_specs.get(spec_name) or {}).get("task_specs") or {}
			inner = describe(sub.get("tasks"), child_specs)
			if inner:
				labels.append(inner)
			else:
				typename = ((spec_map or {}).get(spec_name) or {}).get("typename") or ""
				label = display(spec_map, spec_name)
				if "AdHoc" in typename:
					labels.append(f"{label} — awaiting task selection")
				else:
					labels.append(f"{label} — in progress")
		return ", ".join(labels)

	top_specs = (state.get("spec") or {}).get("task_specs") or {}
	return describe(state.get("tasks"), top_specs)


@frappe.whitelist()
def start_process(
	model_name: str,
	context_doctype: str = None,
	context_docname: str = None,
	initial_data: str = None,
) -> dict:
	"""
	Create and start a new BPMN Process Instance.

	The engine will immediately run all automated tasks (script tasks,
	gateways, etc.) and pause at the first User Task(s).

	Args:
		model_name:       Name of the BPMN Process Model to run
		context_doctype:  Optional linked Frappe DocType (e.g. 'Work Item')
		context_docname:  Optional linked document name
		initial_data:     Optional JSON string of initial workflow data

	Returns:
		dict with instance name, status, and first active tasks
	"""
	if not model_name:
		frappe.throw(_("model_name is required"))

	if not frappe.db.exists("BPMN Process Model", model_name):
		frappe.throw(_("Process model '{0}' not found").format(model_name))

	parsed_data = {}
	if initial_data:
		parsed_data = frappe.parse_json(initial_data) if isinstance(initial_data, str) else initial_data

	# Create the instance record
	instance = frappe.new_doc("BPMN Process Instance")
	instance.process_model = model_name
	instance.status = "Active"
	instance.initiated_by = frappe.session.user
	instance.started_at = frappe.utils.now_datetime()
	if context_doctype:
		instance.context_doctype = context_doctype
	if context_docname:
		instance.context_docname = context_docname
	instance.insert(ignore_permissions=True)

	# Start the engine (synchronous).
	try:
		instance.start(initial_data=parsed_data)
	except frappe.ValidationError:
		# start() already handles the failures it owns: runtime/script errors are
		# halted + surfaced as a sanitized Reference-ID message, and pre-engine
		# validation (e.g. no compiled spec) already carries a safe message.
		# Re-raise as-is — never wrap raw internals (the old wrapper leaked str(exc)).
		raise
	except Exception:
		# Backstop for failures OUTSIDE the engine seam (e.g. building or
		# serializing the workflow), which start() does not sanitize. Record the
		# failure and surface a generic message instead of a raw traceback.
		frappe.db.set_value(
			"BPMN Process Instance", instance.name, "status", "Errored",
			update_modified=False,
		)
		frappe.log_error(
			title=f"BPMN start_process failed — {instance.name}",
			message=frappe.get_traceback(),
		)
		frappe.throw(
			_("Failed to start process '{0}'. Please contact your administrator.").format(model_name)
		)

	return {
		"instance": instance.name,
		"status": instance.status,
		"active_tasks": instance.get_active_tasks_summary(),
	}


@frappe.whitelist()
def start_process_async(
	model_name: str,
	context_doctype: str = None,
	context_docname: str = None,
	initial_data: str = None,
) -> dict:
	"""
	Enqueue start_process as a background job so it doesn't block the UI.
	Captures the caller's user so the job runs with correct attribution.
	"""
	if not model_name:
		frappe.throw(_("model_name is required"))

	if not frappe.db.exists("BPMN Process Model", model_name):
		frappe.throw(_("Process model '{0}' not found").format(model_name))

	frappe.enqueue(
		"one_bpmn.api.instance_api._start_process_as_user",
		# WI-001365: dedicated queue so multi-turn AI Task Selector loops
		# cannot starve unrelated ONE-FM jobs (emails, reports, integrations)
		# on the shared default/short/long queues. Requires the queue in
		# common_site_config.json's "workers" block.
		queue="bpmn_ai_agent",
		model_name=model_name,
		context_doctype=context_doctype,
		context_docname=context_docname,
		initial_data=initial_data,
		run_as_user=frappe.session.user,
		is_async=True,
		timeout=600,
	)

	return {"status": "queued", "message": _("Process '{0}' queued for execution").format(model_name)}


def _start_process_as_user(
	model_name: str,
	context_doctype: str = None,
	context_docname: str = None,
	initial_data: str = None,
	run_as_user: str = None,
):
	"""
	Wrapper for start_process that sets the session user before execution.
	Used by start_process_async to preserve the caller's user context.
	Restores the original user afterwards to avoid leaking into subsequent jobs.
	"""
	original_user = frappe.session.user
	try:
		if run_as_user:
			frappe.set_user(run_as_user)
		start_process(
			model_name=model_name,
			context_doctype=context_doctype,
			context_docname=context_docname,
			initial_data=initial_data,
		)
	finally:
		frappe.set_user(original_user)


@frappe.whitelist()
def complete_task(
	instance_name: str,
	task_id: str,
	data: str = None,
) -> dict:
	"""
	Complete a User Task in a running process instance and advance the workflow.

	Performs the same permission and validation checks as Frappe's native
	workflow before allowing the action:
	  1. User assignment check — is the current user assigned to this task?
	  2. Action validation     — is the submitted action in the allowed list?
	  3. Document permission   — does the user have write access to the doc?
	  4. Role check            — does the user have the required role (if any)?

	Args:
		instance_name: Name of the BPMN Process Instance
		task_id:       The SpiffWorkflow task UUID (from active_tasks.task_id)
		data:          Optional JSON string of form data submitted by the user

	Returns:
		dict with updated status and next active tasks
	"""
	if not instance_name or not task_id:
		frappe.throw(_("instance_name and task_id are required"))

	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	instance.check_permission("write")

	# ── WI-001498: gate scoped to ACTIVE AI execution ────────────────────────
	# engine_in_progress is held only while an engine pass (an AI job, or a
	# concurrent complete_task) is actually running. A waiting instance —
	# parked AI job queued, human task, catch event — has the gate clear, so
	# human tasks stay completable even when they were spawned by AI.
	if frappe.db.get_value(
		"BPMN Process Instance", instance_name, "engine_in_progress"
	):
		frappe.throw(
			_(
				"Instance is processing — an engine pass (AI task or another "
				"action) is currently running. Please retry in a moment."
			)
		)

	parsed_data = {}
	if data:
		parsed_data = frappe.parse_json(data) if isinstance(data, str) else data

	# ── Find the active task row ─────────────────────────────────────────────
	active_row = next(
		(r for r in instance.active_tasks if r.task_id == task_id),
		None,
	)
	if not active_row:
		frappe.throw(_("Task '{0}' not found in the active tasks of this instance.").format(task_id))

	if active_row.status != "Waiting":
		frappe.throw(_("Task '{0}' is not in Waiting status.").format(active_row.task_name or task_id))

	current_user = frappe.session.user
	approved_ctc_name = None

	# ── 1. USER ASSIGNMENT CHECK ─────────────────────────────────────────────
	# Same as Frappe's "allow_edit" on workflow states — only the assigned
	# user (or Administrator) can complete the task.
	assigned_user = active_row.assigned_user or ""
	assigned_role = active_row.assigned_role or ""

	# assigned_user may list multiple people (Table Field / multi-assignee
	# mode, e.g. Task.custom_assigned_to) — completion by any one of them
	# is authorized, not just an exact string match.
	# Imported lazily: assignment.py pulls in engine.py, which is fragile
	# (SpiffWorkflow version drift) — importing it at module load time would
	# take down every whitelisted method in this file, not just this one.
	from one_bpmn.one_bpmn.doctype.bpmn_process_instance.assignment import split_users

	assigned_users_list = split_users(assigned_user)

	if assigned_users_list and current_user not in assigned_users_list and not _is_bpmn_super_user(current_user):
		# Also allow the document owner (they initiated the process)
		is_doc_owner = False
		if instance.context_doctype and instance.context_docname:
			doc_owner = frappe.db.get_value(instance.context_doctype, instance.context_docname, "owner")
			is_doc_owner = doc_owner == current_user

		if not is_doc_owner:
			# Allow if this specific user has an approved Contingency Task Completion
			# for this context document.  Any other user's CTC does not grant access.
			# Check workflow_state OR status since the BPMN process sets
			# workflow_state via apply_workflow and status via update_field.
			if instance.context_doctype and instance.context_docname:
				from frappe.query_builder import DocType

				CTC = DocType("Contingency Task Completion")
				ctc_result = (
					frappe.qb.from_(CTC)
					.select(CTC.name)
					.where(CTC.context_doctype == instance.context_doctype)
					.where(CTC.context_docname == instance.context_docname)
					.where(CTC.process_owner_user == current_user)
					.where(
						(CTC.workflow_state == "Approved") | (CTC.status == "Approved")
					)
					.where(CTC.status != "Expired")
					.where(CTC.docstatus == 1)
					.limit(1)
				).run()
				approved_ctc_name = ctc_result[0][0] if ctc_result else None

			if not approved_ctc_name:
				assignee_names = ", ".join(
					frappe.utils.get_fullname(u) or u for u in assigned_users_list
				)
				frappe.throw(
					_("You are not authorized to complete this task. It is assigned to {0}.").format(
						assignee_names
					),
					frappe.PermissionError,
				)

	if assigned_role and not _is_bpmn_super_user(current_user):
		user_roles = frappe.get_roles(current_user)
		if assigned_role not in user_roles:
			frappe.throw(
				_("Only users with the role '{0}' can complete this task.").format(assigned_role),
				frappe.PermissionError,
			)

	# ── 2. ACTION VALIDATION ─────────────────────────────────────────────────
	# Same as Frappe's workflow transition validation — the submitted action
	# must be one of the allowed actions configured on the User Task.
	submitted_action = parsed_data.get("action", "")
	allowed_actions_str = active_row.task_actions or ""

	# Parse actions from either JSON array or legacy comma-separated format.
	# New format: [{"action":"Approve","confirmTransition":"true"},{"action":"Reject"}]
	# Legacy format: "Approve,Reject,Send Back"
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
			# Invalid JSON — fall back to legacy CSV parsing rather than
			# silently bypassing validation with an empty list.
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

	# ── 3. DOCUMENT PERMISSION CHECK ─────────────────────────────────────────
	# Same as Frappe's doc.check_permission("write") before workflow action.
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

	# ── Durable AI Agent HITL: human-tool tasks resume the agent ─────────────
	# These rows are synthetic (spawned by a suspended agent, no engine task
	# behind them). They pass the exact same checks above as real User Tasks;
	# completion stores the person's output on the agent's checkpoint and
	# enqueues the resume job instead of running an engine pass here.
	# WI-001933: the same shape for a question asked by a REMOTE agent — the
	# answer goes back over A2A instead of onto a local checkpoint.
	if task_id.startswith(instance.A2A_HUMAN_PREFIX):
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

	if task_id.startswith(instance.AI_HUMAN_PREFIX):
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

	# ── 4. HAND OFF TO THE ENGINE (inline) ───────────────────────────────────
	# All validation passed. The engine pass runs inline in the request
	# (WI-001494/WI-001496) and reports the real resulting state. AI tasks
	# reached by the pass are parked by the WI-001495 seam — ONLY their LLM
	# work runs as a bpmn_ai_agent job, so the request never blocks on AI
	# latency. The UI follows waiting_for_ai and the realtime events the AI
	# job publishes.
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


@frappe.whitelist()
def get_parked_ai_tasks(instance_name: str) -> list:
	"""
	WI-001499: the parked AI units of an instance — the shapes the diagram
	viewer highlights as "Waiting for AI execution" and the targets the
	manual retry button re-kicks.

	Returns: list of {kind, task_id, bpmn_id, label}.
	"""
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


@frappe.whitelist()
def get_suspended_ai_tasks(instance_name: str) -> list:
	"""
	Durable AI Agent HITL: the agents of this instance currently suspended
	waiting for a person. Powers the "waiting for human task X" banner and
	the distinct suspended-agent diagram marker.

	Returns: list of {bpmn_id, human_task_id, human_task_label}.
	"""
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
		if str(row.task_id).startswith(instance.AI_HUMAN_PREFIX)
	}
	return [
		{
			"bpmn_id": r.bpmn_id,
			"human_task_id": r.pending_human_task or "",
			"human_task_label": labels.get(r.pending_human_task, ""),
		}
		for r in runs
	]


@frappe.whitelist()
def retry_ai_task(instance_name: str, task_id: str, kind: str = "service_task") -> dict:
	"""
	WI-001497: manually re-kick a parked AI unit after the automatic retries
	were exhausted (instance Errored) — or re-run a stalled selector decision.

	The parked task was deliberately left in STARTED state on exhaustion, so
	the fresh job resumes exactly where the failed one stopped.

	Args:
		instance_name: BPMN Process Instance name
		task_id:       parked task UUID (service_task) or the ad-hoc
		               subprocess bpmn id (adhoc_decision)
		kind:          "service_task" | "adhoc_decision"
	"""
	if not instance_name or not task_id:
		frappe.throw(_("instance_name and task_id are required"))
	if kind not in ("service_task", "adhoc_decision"):
		frappe.throw(_("kind must be 'service_task' or 'adhoc_decision'"))

	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	instance.check_permission("write")

	if instance.status not in ("Errored", "Active"):
		frappe.throw(
			_('Instance "{0}" is {1} — only Errored or Active instances can retry an AI task.').format(
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
		"one_bpmn.one_bpmn.doctype.bpmn_process_instance"
		".bpmn_process_instance.run_parked_ai_task",
		queue="bpmn_ai_agent",
		timeout=600,
		enqueue_after_commit=True,
		# Manual retries are deliberate — never dedup against a stale job id.
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
	"""
	Second half of complete_task: the engine pass that follows an
	already-validated user action, run inline in the request
	(WI-001494/WI-001496). Runs with the acting user's identity so
	completed-by attribution and permission-sensitive script tasks behave
	consistently. AI tasks reached by the pass are parked by the WI-001495
	seam and continue on the bpmn_ai_agent worker.
	"""
	# NEVER call frappe.set_user for the current user: set_user() rewrites
	# local.session.sid and WIPES session.data — inside a web request (the
	# inline path) the end-of-request session persistence then writes the
	# gutted data back under the browser's cookie sid, and every following
	# request fails with "User None is disabled". Only switch identity when
	# it actually differs (the background-job case).
	if run_as_user and run_as_user != frappe.session.user:
		frappe.set_user(run_as_user)

	# Row lock serializes concurrent engine passes on the same instance
	# (a second action, the timer sweep, a message delivery).
	instance = frappe.get_doc("BPMN Process Instance", instance_name, for_update=True)
	try:
		instance.advance(task_id=task_id, data=data or {})

		# ── CTC expiry message after a successful advance ────────────────
		if approved_ctc_name:
			try:
				send_message(
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
		# Engine-level validation (e.g. the task was completed elsewhere in
		# the meantime) — not an instance failure. Log for traceability.
		frappe.log_error(
			title="BPMN complete_task job: validation error",
			message=frappe.get_traceback(),
		)
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

		# ── Publish realtime events for auto-refresh ─────────────────────
		# 1. The Processa frontend — broadcast to ALL users so anyone
		#    viewing the instance detail page auto-refreshes.
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

		# 2. The Frappe form of the context document (e.g. Employee Daily
		#    Action) so it auto-refreshes when open in the desk.
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


@frappe.whitelist()
def get_instance_tasks(instance_name: str) -> dict:
	"""
	Get the current active tasks and status for a process instance.

	Args:
		instance_name: Name of the BPMN Process Instance

	Returns:
		dict with instance details and waiting tasks
	"""
	if not instance_name:
		frappe.throw(_("instance_name is required"))

	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	instance.check_permission("read")

	return {
		"instance": instance_name,
		"status": instance.status,
		"process_model": instance.process_model,
		"context_doctype": instance.context_doctype,
		"context_docname": instance.context_docname,
		"initiated_by": instance.initiated_by,
		"started_at": str(instance.started_at) if instance.started_at else None,
		"completed_at": str(instance.completed_at) if instance.completed_at else None,
		"active_tasks": instance.get_active_tasks_summary(),
	}


@frappe.whitelist()
def get_instances_for_document(doctype: str, docname: str) -> list:
	"""
	Get all process instances linked to a specific Frappe document.
	Useful for showing workflow history on a Work Item or any other DocType.

	Args:
		doctype: e.g. 'Work Item'
		docname: the document name

	Returns:
		list of instance summaries, most recent first
	"""
	if not doctype or not docname:
		frappe.throw(_("doctype and docname are required"))

	instances = frappe.get_all(
		"BPMN Process Instance",
		filters={"context_doctype": doctype, "context_docname": docname},
		fields=[
			"name",
			"process_model",
			"status",
			"initiated_by",
			"started_at",
			"completed_at",
		],
		order_by="creation desc",
	)

	for inst in instances:
		# Attach current active task names for quick display
		active = frappe.get_all(
			"BPMN Active Task",
			filters={
				"parent": inst.name,
				"parenttype": "BPMN Process Instance",
				"status": "Waiting",
			},
			fields=["task_name", "task_type", "assigned_user"],
		)
		inst["current_tasks"] = active

	return instances


# ============================================================================
# BPMN Form Actions API — used by the global bpmn_form_actions.js injector
# ============================================================================

# Cache key for the doctype-level "is this run via Processa?" lookup.
PROCESSA_DOCTYPES_CACHE_KEY = "one_bpmn_processa_controlled_doctypes"


@frappe.whitelist()
def get_processa_controlled_doctypes() -> list:
	"""
	Return every DocType whose lifecycle is driven by Processa.

	A DocType qualifies when an **active** BPMN Process Model references it
	either as a DocType-Event start trigger (BPMN Start Event Config) or as a
	target document (BPMN Process DocType).  These are exactly the two sources
	trigger._find_matching_models() uses to decide whether a document event
	starts a process, so this list mirrors reality rather than guessing.

	bpmn_form_actions.js uses it to suppress native Frappe controls that
	Processa owns — the Submit button, the "Submit this document to confirm"
	banner, and the no-op Save button on an unchanged document — for every
	document of the DocType, not just those with a live process instance.

	Cached in Redis; invalidated by clear_processa_doctype_cache() whenever a
	BPMN Process Model is saved or deleted.
	"""
	cached = frappe.cache().get_value(PROCESSA_DOCTYPES_CACHE_KEY)
	if cached is not None:
		return cached

	rows = frappe.get_all(
		"BPMN Start Event Config",
		filters={"trigger_type": "DocType Event", "parenttype": "BPMN Process Model"},
		fields=["parent", "trigger_doctype as doctype_name"],
	)
	rows += frappe.get_all(
		"BPMN Process DocType",
		filters={"parenttype": "BPMN Process Model"},
		fields=["parent", "doctype_name"],
	)
	rows = [r for r in rows if r.doctype_name and r.parent]

	doctypes = []
	if rows:
		active_models = set(
			frappe.get_all(
				"BPMN Process Model",
				filters={"name": ["in", list({r.parent for r in rows})], "is_active": 1},
				pluck="name",
			)
		)
		doctypes = sorted({r.doctype_name for r in rows if r.parent in active_models})

	frappe.cache().set_value(PROCESSA_DOCTYPES_CACHE_KEY, doctypes)
	return doctypes


def clear_processa_doctype_cache(doc=None, method=None):
	"""Drop the cached Processa-controlled DocType list (doc_events hook)."""
	frappe.cache().delete_value(PROCESSA_DOCTYPES_CACHE_KEY)


@frappe.whitelist()
def get_active_bpmn_tasks(doctype: str, docname: str) -> list:
	"""
	Return the currently-waiting User Task actions for a given document.

	Called by bpmn_form_actions.js on every Frappe form refresh to check
	whether this document has a pending BPMN task that the current user
	should act on.  If so, the frontend injects action buttons that look
	identical to Frappe's native workflow action buttons.

	Returns list of dicts:
		instance_name  – BPMN Process Instance name
		task_id        – SpiffWorkflow UUID of the waiting User Task
		task_name      – Human-readable task name
		task_actions   – Comma-separated action labels (e.g. "Submit,Return to Draft")
		assigned_user  – User the task is assigned to (or '' for role-based)
		assigned_role  – Role the task is assigned to (or '')
	"""
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

				# A question an agent asked is not a workflow action. It appeared in
				# the Actions menu on the document as a bare shape id, and choosing
				# it completed the task with no answer in it — so the agent resumed
				# having been told nothing, and asked again. It has its own place on
				# the document, with the question, the readings it is choosing
				# between, and a box to reply in; two doors to the same task where
				# one of them loses the answer is worse than one.
				if (row.task_type or "") == "AI Human Task":
					continue

				# Resolve actions — handles both manual and frappe_workflow modes
				actions_str = instance._resolve_task_actions(row)
				actions_detail = instance._resolve_task_actions_detail(row)

				result.append(
					{
						"instance_name": instance_name,
						"task_id": row.task_id,
						"task_name": row.task_name or "",
						"task_actions": actions_str,
						"task_actions_detail": actions_detail,
						"assigned_user": row.assigned_user or "",
						"assigned_role": row.assigned_role or "",
					}
				)

		except Exception:
			frappe.log_error(
				title=f"get_active_bpmn_tasks failed for instance {instance_name}",
				message=frappe.get_traceback(),
			)

	return result


# ============================================================================
# BPMN Message Event API
# ============================================================================


@frappe.whitelist()
def trigger_process_by_message(
	message_name: str,
	payload: str = None,
	context_doctype: str = None,
	context_docname: str = None,
) -> dict:
	"""
	Start the process whose Message Start Event declares ``message_name``.

	``send_message`` delivers to a process that is ALREADY running — it needs an
	instance to hand the message to, and throws when there is none. That leaves
	no way to express the other half of the BPMN message pattern: a map whose
	start event IS a message, waiting to be instantiated by one. This is that
	half.

	The caller names an event, not a diagram. Which map answers to that name is
	configuration, so a map can be renamed, replaced or re-pointed without the
	caller changing — the same separation ``send_message`` already gives running
	instances.

	Resolution reads the diagram rather than ``start_events``: the compiler
	models Conditional, Timer and Signal start events but has no Message type,
	so the recorded config carries ``event_type = "None"`` and no message name.
	Only active models are considered.

	Args:
		message_name:    BPMN message name, e.g. ``ToDo_SyncGoogleTasks_Action``
		payload:         Optional JSON string merged into the new instance's data
		context_doctype: Optional linked DocType
		context_docname: Optional linked document

	Returns:
		dict from ``start_process_async`` plus the model that answered.

	Raises:
		frappe.ValidationError — nothing listens for the name, or more than one
		thing does. Both are refused rather than guessed at: silently picking
		one of two listeners would make the wrong process run intermittently.
	"""
	if not message_name:
		frappe.throw(_("message_name is required"))

	listeners = _models_listening_for(message_name)

	if not listeners:
		frappe.throw(
			_("No active process is listening for the message '{0}'.").format(message_name)
		)
	if len(listeners) > 1:
		frappe.throw(
			_("{0} active processes listen for the message '{1}': {2}. Exactly one must.").format(
				len(listeners), message_name, ", ".join(sorted(listeners))
			)
		)

	model_name = listeners[0]

	# Starting is not enough. A Message Start Event parks the new instance
	# waiting for its message, so a bare start leaves it Active and idle
	# forever. Start and deliver have to happen together, in that order, and
	# both belong on the worker so the button returns immediately.
	frappe.enqueue(
		"one_bpmn.api.instance_api._start_and_deliver_message",
		queue="bpmn_ai_agent",
		model_name=model_name,
		message_name=message_name,
		payload=payload,
		context_doctype=context_doctype,
		context_docname=context_docname,
		run_as_user=frappe.session.user,
		is_async=True,
		timeout=600,
	)

	return {
		"status": "queued",
		"model": model_name,
		"message_name": message_name,
		"message": _("Process '{0}' queued for execution").format(model_name),
	}


def _start_and_deliver_message(
	model_name: str,
	message_name: str,
	payload: str = None,
	context_doctype: str = None,
	context_docname: str = None,
	run_as_user: str = None,
):
	"""Create the instance, then hand it the message that starts it.

	Runs as the caller so the map's scripts see the right ``frappe.session.user``
	— the sync they trigger is per-user, and attribution on anything they write
	should name the person who pressed the button, not the worker.
	"""
	original_user = frappe.session.user
	try:
		if run_as_user:
			frappe.set_user(run_as_user)

		started = start_process(
			model_name=model_name,
			context_doctype=context_doctype,
			context_docname=context_docname,
			initial_data=payload,
		)
		instance = frappe.get_doc("BPMN Process Instance", started["instance"])
		instance.receive_message(
			message_name=message_name,
			payload=frappe.parse_json(payload) if payload else {},
		)

		# receive_message does NOT raise when nothing catches the message — it
		# logs at debug and returns unchanged. Without this the instance sits
		# Active and idle and the run looks successful. Read the flag.
		if not instance.flags.get("bpmn_message_caught"):
			frappe.log_error(
				title=f"BPMN: '{message_name}' started {model_name} but nothing caught it",
				message=(
					f"Instance {instance.name} was created for model {model_name} "
					f"but its start event did not consume message '{message_name}'. "
					"The instance is left Active and will not progress."
				),
			)
	finally:
		frappe.set_user(original_user)


def _models_listening_for(message_name: str) -> list:
	"""Active models with a Message Start Event bound to ``message_name``.

	Two hops on purpose. ``<bpmn:message>`` declares the name; a start event
	opts in by pointing its ``messageRef`` at that declaration's id. Matching on
	the declaration alone would also match a map that merely CATCHES the message
	part-way through, which must not be started by it.
	"""
	from lxml import etree as ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	wanted = (message_name or "").strip()
	found = []

	for name, xml in frappe.get_all(
		"BPMN Process Model",
		filters={"is_active": 1},
		fields=["name", "bpmn_xml"],
		as_list=True,
	):
		if not xml or wanted not in xml:
			# Cheap reject before paying for a parse.
			continue
		try:
			parser = ET.XMLParser(resolve_entities=False, no_network=True)
			root = ET.fromstring(xml.encode("utf-8"), parser=parser)
		except Exception:
			# A diagram that will not parse cannot be started by anything; the
			# compiler already reports that, so stay quiet and skip it.
			continue

		ids = {
			el.get("id")
			for el in root.iter(f"{{{BPMN_NS}}}message")
			if (el.get("name") or "").strip() == wanted and el.get("id")
		}
		if not ids:
			continue

		for start in root.iter(f"{{{BPMN_NS}}}startEvent"):
			for med in start.iter(f"{{{BPMN_NS}}}messageEventDefinition"):
				if med.get("messageRef") in ids:
					found.append(name)
					break
			else:
				continue
			break

	return found


@frappe.whitelist()
def send_message(
	message_name: str,
	context_doctype: str = None,
	context_docname: str = None,
	instance_name: str = None,
	payload: str = None,
) -> dict:
	"""
	Deliver a BPMN message to a running process instance.

	This is the public API for external systems (webhooks, scheduled jobs,
	Server Scripts) to communicate with BPMN processes using the standard
	Message Event pattern.

	Instance lookup:
	    - If ``instance_name`` is provided, deliver directly to that instance.
	    - Otherwise, look up the single active instance for the given
	      ``context_doctype`` + ``context_docname`` pair.

	The message_name must match a ``<bpmn:message name="...">`` defined in
	the process diagram. If no task is waiting for this message, an error
	is raised.

	Convention: message names follow ``{System}: {Event}`` format,
	e.g. ``GitHub: PR Merged``, ``GitHub: PR Changes Requested``.

	Args:
	    message_name:     BPMN message name (required)
	    context_doctype:  DocType of the linked document (e.g. "Work Item")
	    context_docname:  Name of the linked document
	    instance_name:    Direct instance name (overrides context lookup)
	    payload:          JSON string of data to merge into task.data

	Returns:
	    dict with instance status and active tasks
	"""
	if not message_name:
		frappe.throw(_("message_name is required"))

	# ── Resolve the target instance ──────────────────────────────────────
	if not instance_name:
		if not context_doctype or not context_docname:
			frappe.throw(
				_("Either instance_name or both context_doctype and context_docname are required")
			)

		instances = frappe.get_all(
			"BPMN Process Instance",
			filters={
				"context_doctype": context_doctype,
				"context_docname": context_docname,
				"status": "Active",
			},
			pluck="name",
			limit=1,
		)
		if not instances:
			frappe.throw(
				_('No active BPMN instance found for {0} "{1}"').format(
					context_doctype, context_docname
				)
			)
		instance_name = instances[0]

	instance = frappe.get_doc("BPMN Process Instance", instance_name)
	instance.check_permission("write")

	# ── Parse payload ────────────────────────────────────────────────────
	parsed_payload = {}
	if payload:
		parsed_payload = frappe.parse_json(payload) if isinstance(payload, str) else payload

	# ── Deliver message ──────────────────────────────────────────────────
	try:
		active_tasks = instance.receive_message(
			message_name=message_name,
			payload=parsed_payload,
		)
	except frappe.ValidationError:
		raise
	except Exception as exc:
		frappe.db.set_value("BPMN Process Instance", instance_name, "status", "Errored")
		frappe.log_error(
			title="BPMN send_message failed",
			message=frappe.get_traceback(),
		)
		frappe.throw(_("Failed to deliver message: {0}").format(str(exc)))

	# ── Publish realtime events ──────────────────────────────────────────
	frappe.publish_realtime(
		"bpmn_instance_updated",
		{
			"instance_name": instance_name,
			"status": instance.status,
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

	return {
		"instance": instance_name,
		"status": instance.status,
		"active_tasks": active_tasks,
	}

