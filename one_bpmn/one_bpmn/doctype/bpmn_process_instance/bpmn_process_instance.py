# Copyright (c) 2026, one-fm and contributors
# BPMN Process Instance — runtime execution logic

import json
import uuid

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from SpiffWorkflow.util.task import TaskState

from one_bpmn.one_bpmn import engine as bpmn_engine

from .dispatchers import (
	dispatch_email,
	dispatch_google_chat,
	dispatch_push_notification,
	dispatch_update_field,
)
from .assignment import (
	add_frappe_assignment,
	remove_frappe_assignment,
	resolve_assignment,
)


class BPMNProcessInstance(Document):
	"""
	A running execution of a BPMN Process Model.

	Lifecycle:
	    1. Record is created (via API or trigger)
	    2. instance.start()  — parses spec, creates workflow, runs engine steps
	    3. User Tasks appear in active_tasks child table
	    4. instance.advance(task_id, data) — user submits a task
	    5. Engine steps run automatically after each advance
	    6. Repeat 3-5 until instance.status == 'Completed'

	Key fields (from bpmn_process_instance.json):
	    process_model     → Link to BPMN Process Model
	    status            → Active / Completed / Errored / Cancelled
	    workflow_state    → JSON blob of the full SpiffWorkflow state
	    serialized_spec   → JSON blob of the spec (copied from model at start)
	    active_tasks      → Child table of BPMN Active Task rows
	    context_doctype   → The Frappe DocType this instance is attached to
	    context_docname   → The specific record this instance is attached to
	"""

	# Public API

	def start(self, initial_data: dict = None):
		"""
		Initialise and start this process instance.

		Loads the compiled spec from the linked BPMN Process Model,
		creates a BpmnWorkflow, runs all automated tasks (script tasks,
		gateways, send tasks), then pauses at the first User Task(s).

		Args:
		    initial_data: optional dict injected into the root workflow data.
		                  Always merged with context_doctype/docname.

		Raises:
		    frappe.ValidationError: if the model has no compiled spec
		"""
		model = frappe.get_doc("BPMN Process Model", self.process_model)

		if not model.serialized_spec:
			frappe.throw(
				_('Process model "{0}" has no compiled spec. Call compile_process_model() first.').format(
					self.process_model
				)
			)

		spec = self._load_json(model.serialized_spec)
		sp_specs = self._load_json(model.subprocess_specs) or {}

		# Root data: always include context info so Script Tasks can find the doc
		data = {
			"context_doctype": self.context_doctype or "",
			"context_docname": self.context_docname or "",
		}

		# ── Inject context doc fields into task data ───────────────────────────
		# ConditionalStartEvent expressions like `docstatus == 0` or
		# `workflow_state == "Pending"` are evaluated against task.data by
		# SpiffWorkflow's PythonScriptEngine.  Without the doc's fields in
		# task.data the evaluation raises NameError and the condition is treated
		# as False — leaving the StartEvent stuck in WAITING forever.
		if self.context_doctype and self.context_docname:
			try:
				_ctx = frappe.get_doc(self.context_doctype, self.context_docname)
				for _field in _ctx.meta.fields:
					_val = _ctx.get(_field.fieldname)
					# Only inject JSON-safe scalar values — skip child tables,
					# attachments, and any non-primitive types.
					if isinstance(_val, (str, int, float, bool)) or _val is None:
						data[_field.fieldname] = _val
				# Always include docstatus explicitly (it's not in meta.fields)
				data["docstatus"] = _ctx.docstatus
			except Exception:
				# If the doc can't be loaded for any reason, carry on.
				# The condition will simply fail and users will see the instance
				# stuck; they can check BPMN Activity Log for the real error.
				frappe.log_error(
					title="BPMN: failed to inject doc fields into task data",
					message=frappe.get_traceback(),
				)

		if initial_data:
			data.update(initial_data)

		# ── Load service task extensions (embedded at compile time) ────────────
		# These tell the engine what each ServiceTask should actually DO at runtime
		# (e.g. apply a Frappe workflow state).  Stored under service_task_extensions
		# in the serialized_spec JSON by compile_process_model.
		self._service_task_extensions = spec.get("service_task_extensions", {})
		self._user_task_extensions = spec.get("user_task_extensions", {})
		self._script_task_extensions = spec.get("script_task_extensions", {})

		# so Script Tasks can call the configured Frappe Server Script at runtime.
		wf = bpmn_engine.create_workflow(
			serialized_spec=spec,
			subprocess_specs=sp_specs,
			initial_data=data,
			context_doctype=self.context_doctype,
			context_docname=self.context_docname,
			script_task_extensions=self._script_task_extensions,
			initiated_by=self.initiated_by or frappe.session.user,
		)

		frappe.flags.bpmn_engine_action = True
		try:
			self._run_engine(wf)
		finally:
			frappe.flags.bpmn_engine_action = False

		# Persist state
		# Strip non-serializable Frappe doc objects before persisting state
		bpmn_engine.clean_doc_from_wf_data(wf)
		self.workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))
		self.serialized_spec = model.serialized_spec  # snapshot of spec at start time
		self.status = "Active"
		self.started_at = now_datetime()
		self.initiated_by = frappe.session.user

		# Sync user-facing tasks
		self._sync_active_tasks(wf)

		# Maybe it completed immediately (e.g. no user tasks at all)
		self._check_completion(wf)

		self.save(ignore_permissions=True)

	def advance(self, task_id: str, data: dict = None) -> list:
		"""
		Complete a User Task and advance the workflow.

		Args:
		    task_id: the SpiffWorkflow task UUID string (stored in active_tasks.task_id)
		    data:    key/value data submitted by the user for this task

		Returns:
		    list of dicts describing the next active tasks

		Raises:
		    frappe.ValidationError: if task not found or not in READY state
		"""
		if self.status in ("Completed", "Cancelled"):
			frappe.throw(
				_('Instance "{0}" is already {1} and cannot be advanced.').format(self.name, self.status)
			)

		if not self.workflow_state:
			frappe.throw(_("Workflow state is missing. The instance may be corrupted."))

		# Restore the workflow from DB state
		# These are needed by _dispatch_service_task (service) and the ScriptEngine (script).
		# Without this restore, self._service_task_extensions is an empty dict and
		# ALL ServiceTask dispatches silently do nothing (service_type == '').
		_spec_snap = self._load_json(self.serialized_spec or "{}") or {}
		_script_exts = _spec_snap.get("script_task_extensions", {})
		self._service_task_extensions = _spec_snap.get("service_task_extensions", {})
		self._user_task_extensions = _spec_snap.get("user_task_extensions", {})

		wf = bpmn_engine.restore_workflow(
			workflow_state=self._load_json(self.workflow_state),
			context_doctype=self.context_doctype,
			context_docname=self.context_docname,
			script_task_extensions=_script_exts,
			initiated_by=self.initiated_by or "Administrator",
		)

		# Always refresh the context doc so conditional events see latest data
		if self.context_doctype and self.context_docname:
			bpmn_engine.refresh_context_doc(wf, self.context_doctype, self.context_docname)

		# SpiffWorkflow uses uuid.UUID objects as task keys
		try:
			task = wf.get_task_from_id(uuid.UUID(task_id))
		except Exception:
			frappe.throw(_('Task "{0}" not found in this workflow instance.').format(task_id))

		if task.state != TaskState.READY:
			frappe.throw(
				_('Task "{0}" is not in READY state (current state: {1}).').format(
					bpmn_engine.get_task_display_name(task),
					TaskState.get_name(task.state),
				)
			)

		# Push refreshed doc fields into the completing task's data.
		# SpiffWorkflow copies task.data into child tasks on completion,
		# so downstream gateways will see the latest doc values.
		# We do this BEFORE user data injection so user-submitted values
		# take precedence over doc field values.
		if self.context_doctype and self.context_docname:
			task.data.update({
				k: v for k, v in wf.task_tree.data.items()
				if k not in ("doc",)  # skip non-serializable keys
			})

		# Inject user data into task (highest priority — overrides doc fields)
		if data:
			task.data.update(data)

		# Capture current assignments BEFORE marking task completed,
		# so the diff in _sync_active_tasks knows who was previously assigned.
		prev_assigned = {
			row.assigned_user
			for row in self.active_tasks
			if row.status == "Waiting" and row.assigned_user
		}

		# Mark the active_tasks row as Completed and record timing
		# (Frappe assignment cleanup is handled by _sync_active_tasks
		# via a before/after diff to avoid close+recreate for the same user)
		_completed_at = now_datetime()
		for row in self.active_tasks:
			if row.task_id == task_id:
				row.status = "Completed"
				row.end_time = _completed_at
				if row.started_at:
					row.timer_duration = int(
						frappe.utils.time_diff_in_seconds(_completed_at, row.started_at)
					)

		self._log_task(
			task_id=task_id,
			task_name=bpmn_engine.get_task_display_name(task),
			action="Completed",
			data=data,
		)

		frappe.flags.bpmn_engine_action = True
		try:
			task.run()
			self._run_engine(wf)
		finally:
			frappe.flags.bpmn_engine_action = False

		# Persist updated state
		# Strip non-serializable Frappe doc objects before persisting state
		bpmn_engine.clean_doc_from_wf_data(wf)
		self.workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))

		# Rebuild active tasks
		self._sync_active_tasks(wf, prev_assigned=prev_assigned)

		self._check_completion(wf)

		# Persist state directly via db_update to bypass Frappe's check_if_latest
		# (optimistic-lock check). This Frappe version has no ignore_version flag
		# on Document.save(). Using save() races with the realtime doc_update
		# broadcast we publish (and with Frappe's own notify_update() which also
		# fires on save), causing TimestampMismatchError.
		#
		# db_update() writes only the parent-level scalar fields. Child tables
		# (active_tasks) are updated separately via update_children().
		# run_method("on_update") fires any custom on_update hooks without
		# going through the full save/validate pipeline.
		self.modified = frappe.utils.now()
		self.modified_by = frappe.session.user
		self.db_update()
		self.update_children()
		self.run_method("on_update")

		return self.get_active_tasks_summary()

	def receive_message(self, message_name: str, payload: dict = None) -> list:
		"""
		Deliver an external BPMN message to this process instance.

		This is the BPMN-standard mechanism for external systems (webhooks,
		scheduled jobs, other processes) to interact with a running process.
		The message is delivered to a waiting IntermediateCatchEvent,
		ReceiveTask, or EventBasedGateway child that matches the message name.

		When an EventBasedGateway is waiting, delivering a message will:
		  1. Fire the matching Message Catch Event
		  2. Cancel all other waiting paths (User Task, other catch events)
		  3. Continue the flow down the matched path

		The message payload is merged into task.data, making its keys
		available as variables in downstream gateway conditions and
		script task expressions.

		Convention: message names follow ``{System}: {Event}`` format,
		e.g. ``GitHub: PR Merged``, ``GitHub: PR Changes Requested``.

		Args:
		    message_name: BPMN message name — must match <bpmn:message name="...">
		    payload:      Optional dict merged into task.data. Each key becomes
		                  a task variable usable in gateway conditions.

		Returns:
		    list of dicts describing the next active tasks

		Raises:
		    frappe.ValidationError: if instance is not Active or message not caught
		"""
		if self.status in ("Completed", "Cancelled"):
			frappe.throw(
				_('Instance "{0}" is already {1} and cannot receive messages.').format(
					self.name, self.status
				)
			)

		if not self.workflow_state:
			frappe.throw(_("Workflow state is missing. The instance may be corrupted."))

		if not message_name:
			frappe.throw(_("message_name is required."))

		# ── Restore workflow (same as advance) ───────────────────────────────
		_spec_snap = self._load_json(self.serialized_spec or "{}") or {}
		_script_exts = _spec_snap.get("script_task_extensions", {})
		self._service_task_extensions = _spec_snap.get("service_task_extensions", {})
		self._user_task_extensions = _spec_snap.get("user_task_extensions", {})

		wf = bpmn_engine.restore_workflow(
			workflow_state=self._load_json(self.workflow_state),
			context_doctype=self.context_doctype,
			context_docname=self.context_docname,
			script_task_extensions=_script_exts,
			initiated_by=self.initiated_by or "Administrator",
		)

		# Refresh context doc so downstream conditions see latest data
		if self.context_doctype and self.context_docname:
			bpmn_engine.refresh_context_doc(wf, self.context_doctype, self.context_docname)

		# Capture current assignments BEFORE message delivery
		prev_assigned = {
			row.assigned_user
			for row in self.active_tasks
			if row.status == "Waiting" and row.assigned_user
		}

		# ── Deliver the message ──────────────────────────────────────────────
		caught = bpmn_engine.send_message(wf, message_name, payload=payload)

		if not caught:
			frappe.throw(
				_('No task in instance "{0}" is waiting for message "{1}".').format(
					self.name, message_name
				)
			)

		self._log_task(
			task_id="",
			task_name=f"Message: {message_name}",
			action="Message Received",
			data=payload,
		)

		# ── Run engine to process tasks that became READY ────────────────────
		frappe.flags.bpmn_engine_action = True
		try:
			self._run_engine(wf)
		finally:
			frappe.flags.bpmn_engine_action = False

		# ── Persist (same as advance) ────────────────────────────────────────
		bpmn_engine.clean_doc_from_wf_data(wf)
		self.workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))

		self._sync_active_tasks(wf, prev_assigned=prev_assigned)
		self._check_completion(wf)

		self.modified = frappe.utils.now()
		self.modified_by = frappe.session.user
		self.db_update()
		self.update_children()
		self.run_method("on_update")

		return self.get_active_tasks_summary()

	def get_active_tasks_summary(self) -> list:
		"""
		Return the current waiting User Tasks as a list of dicts.
		Used by API responses and the Processa frontend.
		"""
		return [
			{
				"task_id": row.task_id,
				"task_name": row.task_name,
				"task_type": row.task_type,
				"status": row.status,
				"assigned_user": row.assigned_user,
				"assigned_role": row.assigned_role,
				"started_at": str(row.started_at) if row.started_at else None,
				# Comma-separated action labels (e.g. "Approve,Reject").
				# Maintained for backward compat with older frontends.
				"task_actions": self._resolve_task_actions(row),
				# Structured array of action objects with per-action flags:
				# [{"action":"Approve","confirmTransition":"true","requireDigitalSignature":"true"}, ...]
				"task_actions_detail": self._resolve_task_actions_detail(row),
			}
			for row in self.active_tasks
			if row.status == "Waiting"
		]

	# Internal execution helpers

	@staticmethod
	def _parse_task_actions_json(raw: str) -> list:
		"""
		Parse task_actions from either JSON array format or legacy CSV.

		New format (JSON array):
		    [{"action":"Approve","confirmTransition":"true"},{"action":"Reject"}]

		Legacy format (comma-separated):
		    "Approve,Reject,Send Back"

		Returns a list of dicts with at least an "action" key.
		"""
		if not raw:
			return []
		trimmed = raw.strip()
		if trimmed.startswith("["):
			try:
				parsed = json.loads(trimmed)
				return parsed if isinstance(parsed, list) else []
			except (TypeError, ValueError):
				return []
		# Legacy CSV
		return [
			{"action": a.strip()} for a in trimmed.split(",") if a.strip()
		]

	def _resolve_task_actions(self, row) -> str:
		"""
		Return comma-separated action labels for a pending active task row.

		Parses the stored task_actions (JSON or CSV)
		and returns comma-separated action names.
		"""
		raw = getattr(row, "task_actions", "") or ""
		actions = self._parse_task_actions_json(raw)
		return ",".join(a.get("action", "") for a in actions if a.get("action"))

	def _resolve_task_actions_detail(self, row) -> list:
		"""
		Return the full structured action list with per-action flags.

		Parses the stored JSON/CSV list of action dicts
		with all per-action metadata (confirmTransition, requireDigitalSignature).
		"""
		raw = getattr(row, "task_actions", "") or ""
		return self._parse_task_actions_json(raw)

	def _run_engine(self, wf):
		"""
		Run all automated engine tasks until only User Tasks or
		WAITING (conditional/timer) tasks remain.

		SpiffWorkflow 3.x ServiceTask lifecycle:
		  do_engine_steps() → READY → STARTED  (task waits for external call)
		  We then dispatch the real-world side effect and call task.complete()
		  to advance STARTED → COMPLETED, then loop again.
		"""
		wf.refresh_waiting_tasks()

		for _ in range(20):  # safety cap — no real workflow needs > 20 passes
			wf.do_engine_steps(
				did_complete_task=self._on_engine_task_complete,
			)

			# Find non-manual tasks left in STARTED state.  These are
			# ServiceTasks waiting for us to dispatch their action and
			# explicitly call task.complete().
			started_tasks = [
				t for t in wf.get_tasks(state=TaskState.STARTED) if not getattr(t.task_spec, "manual", False)
			]
			if not started_tasks:
				break  # nothing left to advance — we're done

			for task in started_tasks:
				self._dispatch_service_task(task)
				self._on_engine_task_complete(task)
				task.complete()

		# Final refresh catches conditional events that became true after
		# the engine steps ran (e.g. script task updated a doc field that
		# a downstream catch event now matches).
		wf.refresh_waiting_tasks()

	def _on_engine_task_complete(self, task):
		"""
		Callback fired by do_engine_steps() after each automated task.
		Logs the completion to BPMN Activity Log.

		Skips internal SpiffWorkflow tasks (Start, End, EndJoin) that have
		no bpmn_id — they're engine internals not visible on the BPMN diagram.
		"""
		task_spec = task.task_spec
		bpmn_id = getattr(task_spec, "bpmn_id", None)
		spec_name = getattr(task_spec, "name", "") or ""

		# Skip engine-internal tasks that don't correspond to BPMN elements
		if not bpmn_id and (spec_name in ("Start", "End") or spec_name.endswith(".EndJoin")):
			return

		self._log_task(
			task_id=str(task.id),
			task_name=bpmn_engine.get_task_display_name(task),
			action="Completed",
			data=dict(task.data),
		)

	def _dispatch_service_task(self, task):
		"""
		Execute the real-world action for a STARTED ServiceTask before
		marking it complete.

		Reads the ``service_task_extensions`` dict that was embedded into the
		serialized spec at compile time and dispatches to the appropriate
		handler based on ``serviceType``.

		Returns:
		    True  — task was handled; caller should mark it complete.
		    False — task requires user confirmation (confirmTransition=true);
		            caller should leave it STARTED so it appears in active_tasks.

		Currently supported service types:
		    apply_workflow — Apply a Frappe Workflow state transition to the
		                     context document, with full permission checking.
		"""
		extensions = getattr(self, "_service_task_extensions", {})
		bpmn_id = getattr(task.task_spec, "bpmn_id", None) or ""
		task_cfg = extensions.get(bpmn_id, {})

		service_type = task_cfg.get("serviceType", "")

		if service_type == "apply_workflow":
			# ── Resolve doctype + docname ───────────────────────────────────
			# serviceTargetDoctype lets the diagram override the context doctype.
			doctype = task_cfg.get("serviceTargetDoctype") or self.context_doctype
			docname = self.context_docname
			target_state = task_cfg.get("workflowState", "")
			doc_status = task_cfg.get("docStatus", "")  # override hint
			only_role = task_cfg.get("onlyAllowEdit", "")
			triggered_by = frappe.session.user or self.initiated_by or "Administrator"

			if not (doctype and docname):
				frappe.log_error(
					title="BPMN ServiceTask: apply_workflow misconfigured",
					message=(
						f"Task {bpmn_id} ({bpmn_engine.get_task_display_name(task)}) "
						f"is missing doctype={doctype!r} or docname={docname!r}."
					),
				)
				return True  # skip but still complete to avoid stuck workflow

			if not target_state and not doc_status:
				frappe.log_error(
					title="BPMN ServiceTask: apply_workflow misconfigured",
					message=(
						f"Task {bpmn_id} ({bpmn_engine.get_task_display_name(task)}) "
						f"has neither workflowState nor docStatus configured."
					),
				)
				return True  # skip but still complete to avoid stuck workflow

			try:
				from one_bpmn.api.workflow_state import _apply_bpmn_workflow_state

				_apply_bpmn_workflow_state(
					doctype=doctype,
					docname=docname,
					target_state=target_state,
					doc_status_hint=doc_status,
					only_allow_role=only_role,
					triggered_by=triggered_by,
				)
			except Exception:
				raise  # bubble up so the instance can be marked Errored

		elif service_type == "send_email":
			try:
				dispatch_email(self, task, task_cfg)
			except Exception:
				# Email failures are non-fatal: log and continue so the
				# workflow can complete even if the email account is not
				# configured or the mail server is unreachable.
				frappe.log_error(
					title=f"BPMN ServiceTask: send_email failed for task {bpmn_id}",
					message=frappe.get_traceback(),
				)

		elif service_type == "update_field":
			dispatch_update_field(self, task, task_cfg, bpmn_id)

		elif service_type == "google_chat":
			# Error handling is fully inside _dispatch_google_chat;
			# failures are non-fatal and logged there.
			dispatch_google_chat(self, task, task_cfg, bpmn_id)

		elif service_type == "push_notification":
			try:
				dispatch_push_notification(self, task, task_cfg, bpmn_id)
			except Exception:
				frappe.log_error(
					title=f"BPMN ServiceTask: push_notification failed for task {bpmn_id}",
					message=frappe.get_traceback(),
				)

		return True  # default: complete the task

	def _sync_active_tasks(self, wf, prev_assigned=None):
		"""
		Rebuild the active_tasks child table to reflect the current
		set of READY User Tasks in the workflow.

		- Keeps rows that are already Completed (for audit visibility)
		- Adds new rows for newly READY user tasks
		- Removes rows for tasks that are no longer READY
		- Manages Frappe assignments (ToDo) via before/after diff:
		  same user keeps existing ToDo; changed user gets old closed, new created

		Args:
		    prev_assigned: set of user emails that had Open assignments before
		                   this sync. Passed from advance() which captures the
		                   snapshot before marking the task row Completed.
		                   When None (e.g. called from start()), computed from
		                   current Waiting rows.
		"""
		ready_user_tasks = bpmn_engine.get_ready_user_tasks(wf)
		new_ready_ids = {str(t.id) for t in ready_user_tasks}

		# Snapshot: which users have Open assignments before this rebuild
		if prev_assigned is None:
			prev_assigned = {
				row.assigned_user
				for row in self.active_tasks
				if row.status == "Waiting" and row.assigned_user
			}

		# Keep completed rows + rows still waiting that are still ready
		self.active_tasks = [
			row for row in self.active_tasks if row.status == "Completed" or row.task_id in new_ready_ids
		]

		existing_waiting_ids = {row.task_id for row in self.active_tasks if row.status == "Waiting"}

		for task in ready_user_tasks:
			tid = str(task.id)
			if tid in existing_waiting_ids:
				continue  # already in the table

			task_name = bpmn_engine.get_task_display_name(task)
			task_type = bpmn_engine.get_task_type_label(task)

			# Assignment hints can be stored in task data by upstream tasks
			assigned_user = task.data.get("assigned_user") or ""
			assigned_role = task.data.get("assigned_role") or ""

			# Resolve assignment from the task's configuration -------------------
			async_user = resolve_assignment(self, task)
			if async_user:
				assigned_user = async_user

			# Resolve task actions (action buttons) from user_task_extensions --
			bpmn_id_key = getattr(task.task_spec, "bpmn_id", None) or ""
			task_cfg = getattr(self, "_user_task_extensions", {}).get(bpmn_id_key, {})
			task_actions = task_cfg.get("taskActions", "")
			target_doctype = self.context_doctype
			target_docname = self.context_docname

			self.append(
				"active_tasks",
				{
					"task_id": tid,
					"task_name": task_name,
					"task_type": task_type,
					"status": "Waiting",
					"started_at": now_datetime(),
					"assigned_user": assigned_user,
					"assigned_role": assigned_role,
					"task_actions": task_actions,
					"target_doctype": target_doctype,
					"target_docname": target_docname,
				},
			)

			self._log_task(
				task_id=tid,
				task_name=task_name,
				action="Started",
			)

		# Diff: which users are now assigned across all Waiting tasks
		curr_assigned = {
			row.assigned_user: row.task_name
			for row in self.active_tasks
			if row.status == "Waiting" and row.assigned_user
		}

		# Close ToDos for users who were assigned but no longer are
		for user in prev_assigned - set(curr_assigned.keys()):
			remove_frappe_assignment(self, user)

		# Create ToDos for users who are newly assigned
		for user, task_name in curr_assigned.items():
			if user not in prev_assigned:
				add_frappe_assignment(self, user, task_name)

	def _check_completion(self, wf):
		"""
		Mark the instance Completed when the workflow has no more
		READY or WAITING tasks — i.e. it has fully run to the End Event.

		Also ensures STARTED tasks (ServiceTasks awaiting external calls)
		are not confused with a completed workflow — they keep the instance
		in Active state until explicitly resolved.
		"""
		if wf.is_completed():
			self.status = "Completed"
			self.completed_at = now_datetime()
		elif (
			not wf.get_tasks(state=TaskState.READY)
			and not wf.get_tasks(state=TaskState.WAITING)
			and not wf.get_tasks(state=TaskState.STARTED)
		):
			# Fallback: no pending tasks at all but is_completed() returned
			# False.  Treat as complete to avoid a forever-stuck instance.
			self.status = "Completed"
			self.completed_at = now_datetime()

	def _log_task(self, task_id: str, task_name: str, action: str, data: dict = None):
		"""
		Write a row to BPMN Activity Log.
		Deduplicates by checking if the same task_id + action already exists.
		Failures are silently logged — they should never break the main flow.
		"""
		try:
			# Guard against duplicate log entries (can happen when
			# do_engine_steps callback and the STARTED loop both fire
			# for the same service task completion).
			if frappe.db.exists("BPMN Activity Log", {
				"instance": self.name,
				"task_id": task_id,
				"action": action,
			}):
				return

			log = frappe.new_doc("BPMN Activity Log")
			log.instance = self.name
			log.task_id = task_id
			log.task_name = task_name
			log.action = action
			log.timestamp = now_datetime()
			log.user = frappe.session.user
			if data:
				log.data = json.dumps(data, default=str, indent=2)
			log.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(
				title="BPMN Activity Log write failed",
				message=frappe.get_traceback(),
			)

	# Utilities

	@staticmethod
	def _load_json(value):
		"""Safely load a JSON field that may already be a dict."""
		if value is None:
			return None
		if isinstance(value, (dict, list)):
			return value
		try:
			return json.loads(value)
		except (TypeError, ValueError):
			return None
