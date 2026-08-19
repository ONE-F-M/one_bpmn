# Copyright (c) 2026, one-fm and contributors
# BPMN Process Instance — runtime execution logic

import json
import uuid

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from SpiffWorkflow.bpmn.specs.mixins.subworkflow_task import SubWorkflowTask
from SpiffWorkflow.util.task import TaskState

from one_bpmn.one_bpmn import engine as bpmn_engine
from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import dispatch_ai_agent

from .dispatchers import (
	dispatch_connector,
	dispatch_email,
	dispatch_google_chat,
	dispatch_push_notification,
	dispatch_send_notification,
	dispatch_update_field,
)
from .assignment import (
	add_frappe_assignment,
	remove_frappe_assignment,
	resolve_assignment,
	split_users,
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
			"process_model": self.process_model or "",
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
		except Exception:
			# Script/service/gateway failure — halt + sanitized Reference-ID error.
			self._fail_runtime(phase="start")
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

		# Persist state directly via db_update to bypass Frappe's check_if_latest
		# (optimistic-lock check), same as advance()/receive_message()/
		# resume_parked_ai(). _sync_active_tasks() above can create a ToDo whose
		# assignment email sends synchronously (frappe.sendmail(..., now=True)),
		# committing mid-flow; an enqueue_after_commit AI job can then touch this
		# same row before we get here. self.save() would raise
		# TimestampMismatchError at that point — a ValidationError (HTTP 417),
		# which Frappe never logs to Error Log (only >=500 gets logged), so the
		# instance silently ends up with status="Active" but no workflow_state
		# and no active_tasks ever persisted. db_update() doesn't hit that check.
		self.modified = frappe.utils.now()
		self.modified_by = frappe.session.user
		self.db_update()
		self.update_children()
		self.run_method("on_update")

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
		self._refresh_user_task_extensions_from_model()

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
		prev_assigned = set()
		for row in self.active_tasks:
			if row.status == "Waiting" and row.assigned_user:
				prev_assigned.update(split_users(row.assigned_user))

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
		except Exception:
			# Script/service/gateway failure — halt + sanitized Reference-ID error.
			self._fail_runtime(phase="advance")
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

	# ── Runtime failure handling (spec 2.2 + 2.4) ─────────────────────────────
	#
	# A script/service/gateway task can fail while the engine runs (start / advance
	# / receive_message / resume_parked_ai). When that happens we must:
	#   * HALT — mark the instance "Errored" durably so it never silently proceeds
	#     past a control gate (2.4); and
	#   * SANITISE — write the full traceback + context to admin-only stores under a
	#     random Reference ID, and surface the caller only a generic message + that
	#     ID, so a failing script can't leak schema names, permission walls, or
	#     blocked-keyword hints back to an attacker (2.2).

	def _record_runtime_failure(self, phase: str) -> str:
		"""
		Halt this instance on a runtime engine failure and record an admin-only
		diagnostic keyed by a random Reference ID. Returns that Reference ID.

		Must be called from inside an ``except`` block (it reads the live
		traceback). Sets ``status = "Errored"`` and COMMITS it — the caller then
		re-raises a sanitized error which rolls the request back, so without the
		commit the failure state would be lost (the pre-existing gap).

		Both sinks are admin-only: the Frappe Error Log (System Manager) and the
		BPMN Activity Log (a System-Manager-only doctype), so the traceback and
		variables never reach a regular user.
		"""
		ref_id = frappe.generate_hash(length=12).upper()

		detail = (
			f"Reference ID: {ref_id}\n"
			f"Phase: {phase}\n"
			f"Instance: {self.name}\n"
			f"Process Model: {self.process_model}\n"
			f"Context: {self.context_doctype or '-'} / {self.context_docname or '-'}\n"
			f"Initiated by: {self.initiated_by or '-'}\n"
			f"\n{frappe.get_traceback()}"
		)
		# log_error truncates the title to ~140 chars; keep the Reference ID in it
		# so an admin can jump straight from the user's quoted ID to the record.
		frappe.log_error(
			title=f"BPMN runtime failure [{ref_id}] — {self.name}",
			message=detail,
		)

		try:
			frappe.db.set_value(
				"BPMN Process Instance", self.name, "status", "Errored",
				update_modified=False,
			)
			self.status = "Errored"
			self._settle_goal_completion("Errored")
			self._log_task(
				task_id=f"runtime-failure::{ref_id}",
				task_name=f"Runtime failure ({phase})",
				action="Errored",
				data={"reference_id": ref_id, "phase": phase},
			)
			# Persist the Errored state before the sanitized re-raise rolls back.
			frappe.db.commit()
		except Exception:
			frappe.log_error(
				title=f"BPMN: failed to persist Errored state [{ref_id}]",
				message=frappe.get_traceback(),
			)

		return ref_id

	def _fail_runtime(self, phase: str):
		"""
		Record the failure (halt + deep log) then raise a sanitized, Reference-ID
		error for the caller. Never returns. Call from inside an ``except`` block.
		"""
		# A refusal by a security control — a rate limit, a conversation freeze, a
		# blocked injection attempt — is a DECISION the platform made, not a fault
		# in the process. Two things go wrong if it is treated as one: the instance
		# is marked Errored, so the conversation stays broken even after a reviewer
		# releases the lock; and an explainable refusal is replaced by "quote this
		# reference id", which the user can do nothing with. Let it through
		# untouched — the chat surface knows how to say it.
		#
		# Matched on the AgentRefusal CATEGORY, not on each control's
		# own class. Naming them one by one put the security module's class list
		# inside the engine, and guaranteed the next control would forget to
		# register itself and silently start halting instances again.
		import sys

		in_flight = sys.exc_info()[1]
		if in_flight is not None:
			from one_bpmn.security.refusal import AgentRefusal

			if isinstance(in_flight, AgentRefusal):
				raise in_flight

		ref_id = self._record_runtime_failure(phase)
		frappe.throw(
			_(
				"This process could not continue and has been halted due to an "
				"internal error. Quote Reference ID {0} to your administrator for "
				"assistance."
			).format(ref_id),
			title=_("Process Halted"),
		)

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
		self._refresh_user_task_extensions_from_model()

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
		prev_assigned = set()
		for row in self.active_tasks:
			if row.status == "Waiting" and row.assigned_user:
				prev_assigned.update(split_users(row.assigned_user))

		# ── Deliver the message ──────────────────────────────────────────────
		caught = bpmn_engine.send_message(wf, message_name, payload=payload)

		if not caught:
			# No task is waiting for this message (e.g. a document event fired
			# while the instance isn't parked at a matching catch node). This is
			# benign, so skip quietly and return the unchanged task summary rather
			# than surfacing an alarming error to the user.
			frappe.logger("one_bpmn").debug(
				f'No task in instance "{self.name}" is waiting for message "{message_name}".'
			)
			return self.get_active_tasks_summary()

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
		except Exception:
			# Script/service/gateway failure — halt + sanitized Reference-ID error.
			self._fail_runtime(phase="receive_message")
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

	def resume_parked_ai(self, kind: str, task_id: str):
		"""
		WI-001495: execute one parked AI unit in the bpmn_ai_agent worker and
		resume the flow.

		kind == "service_task"  — task_id is the SpiffWorkflow UUID of a parked
		    (STARTED) ai_agent Service Task: dispatch it, complete it, then run
		    the engine forward. Idempotent: if the task is no longer STARTED
		    (redelivery, completed elsewhere) this is a no-op.
		kind == "adhoc_decision" — task_id is the ad-hoc subprocess spec name
		    whose AI Task Selector decision was parked: re-run the engine with
		    the resume target set so the decider executes exactly ONE LLM
		    decision inline; the next decision parks again (one job per turn).

		Downstream non-AI tasks reached after the AI completes run in this
		worker pass — there is no open request to return them to. Further AI
		tasks reached here park again as fresh jobs.
		"""
		if self.status in ("Completed", "Cancelled"):
			return
		if not self.workflow_state:
			return

		# Restore extensions + workflow exactly like advance()
		_spec_snap = self._load_json(self.serialized_spec or "{}") or {}
		_script_exts = _spec_snap.get("script_task_extensions", {})
		self._service_task_extensions = _spec_snap.get("service_task_extensions", {})
		self._user_task_extensions = _spec_snap.get("user_task_extensions", {})
		self._refresh_user_task_extensions_from_model()

		wf = bpmn_engine.restore_workflow(
			workflow_state=self._load_json(self.workflow_state),
			context_doctype=self.context_doctype,
			context_docname=self.context_docname,
			script_task_extensions=_script_exts,
			initiated_by=self.initiated_by or "Administrator",
		)

		if self.context_doctype and self.context_docname:
			bpmn_engine.refresh_context_doc(wf, self.context_doctype, self.context_docname)

		prev_assigned = {
			row.assigned_user
			for row in self.active_tasks
			if row.status == "Waiting" and row.assigned_user
		}

		frappe.flags.bpmn_engine_action = True
		try:
			if kind == "a2a_result":
				# WI-001933: a delegated task reached a terminal state. Apply
				# the remote's answer to the parked Service Task and carry on;
				# a still-running delegation leaves the task parked.
				try:
					task = wf.get_task_from_id(uuid.UUID(task_id))
				except Exception:
					task = None
				if task is None or task.state != TaskState.STARTED:
					return  # already resolved elsewhere — idempotent no-op
				marker = self._task_waiting_a2a(task)
				if not marker:
					return
				if not self._apply_a2a_result(task, marker):
					return  # not terminal yet — stay parked
				self.waiting_for_ai = 0
				self._on_engine_task_complete(task)
				task.complete()
			elif kind in ("service_task", "human_resume"):
				try:
					task = wf.get_task_from_id(uuid.UUID(task_id))
				except Exception:
					task = None
				if task is None or task.state != TaskState.STARTED:
					return  # already resolved elsewhere — idempotent no-op

				marker = self._task_waiting_human(task)
				if kind == "service_task":
					if marker:
						# Suspended for a human — a re-kicked job or manual
						# retry must NOT restart the agent from scratch.
						return
					self._dispatch_service_task(task)
				else:  # human_resume
					if not marker:
						return  # nothing suspended here — idempotent no-op
					bpmn_id = getattr(task.task_spec, "bpmn_id", None) or task.task_spec.name
					task_cfg = getattr(self, "_service_task_extensions", {}).get(bpmn_id) or {}
					# Claims the checkpoint atomically; a lost race (status
					# already flipped) leaves the marker untouched and the
					# state below simply re-persists unchanged.
					dispatch_ai_agent(
						self, task, task_cfg, bpmn_id,
						resume_run=marker.get("run") or None,
					)

				# The dispatch either finished (marker cleared → complete the
				# task and continue the flow) or suspended (again) for a human
				# (marker present → spawn the human task, leave it STARTED).
				if self._task_waiting_human(task):
					self._on_ai_agent_suspended(task)
				else:
					self.waiting_for_human = ""
					self._on_engine_task_complete(task)
					task.complete()
					if isinstance(
						getattr(task.workflow, "spec", None), bpmn_engine.AdHocSubprocessSpec
					) and getattr(task.task_spec, "bpmn_id", None):
						self._on_adhoc_task_complete(task)
			else:  # adhoc_decision
				frappe.flags.bpmn_ai_resume_target = task_id

			self._run_engine(wf)
		finally:
			frappe.flags.bpmn_engine_action = False
			frappe.flags.bpmn_ai_resume_target = None

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

	def get_parked_ai_units(self) -> list:
		"""
		WI-001499: the AI units currently parked on this instance.

		- ai_agent Service Tasks sitting in STARTED (their job is queued,
		  running, retrying, or exhausted-awaiting-manual-retry)
		- ai_task_selector ad-hoc subprocesses waiting for a DECISION
		  (container STARTED with no active inner head)

		Returns: list of {kind, task_id, bpmn_id, label} — task_id is what
		retry_ai_task / run_parked_ai_task expect for that kind.
		"""
		if not self.workflow_state:
			return []

		_spec_snap = self._load_json(self.serialized_spec or "{}") or {}
		self._service_task_extensions = _spec_snap.get("service_task_extensions", {})

		wf = bpmn_engine.restore_workflow(
			workflow_state=self._load_json(self.workflow_state),
			context_doctype=self.context_doctype,
			context_docname=self.context_docname,
		)

		units = []
		for t in wf.get_tasks(state=TaskState.STARTED):
			if getattr(t.task_spec, "manual", False):
				continue
			bpmn_id = getattr(t.task_spec, "bpmn_id", None) or t.task_spec.name
			if isinstance(t.task_spec, SubWorkflowTask):
				cfg = self._service_task_extensions.get(bpmn_id) or {}
				if cfg.get("serviceType") != "ai_task_selector":
					continue
				# Waiting for a decision only when no inner head is active —
				# otherwise the selector is mid-turn running a shape.
				sp = getattr(wf, "subprocesses", {}).get(t.id)
				if sp is not None and sp.get_tasks(
					state=TaskState.READY | TaskState.STARTED
				):
					continue
				units.append(
					{
						"kind": "adhoc_decision",
						"task_id": bpmn_id,
						"bpmn_id": bpmn_id,
						"label": bpmn_engine.get_task_display_name(t),
					}
				)
			elif self._ai_service_type(t) in self._AI_SERVICE_TYPES:
				# Suspended-for-human agents are waiting for a person, not for
				# an AI job — they are not retry targets and not "Waiting for
				# AI execution" shapes.
				if self._task_waiting_human(t):
					continue
				units.append(
					{
						"kind": "service_task",
						"task_id": str(t.id),
						"bpmn_id": bpmn_id,
						"label": bpmn_engine.get_task_display_name(t),
					}
				)
		return units

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
		# WI-001352: while this engine call runs, ad-hoc subprocesses tagged
		# with an AI Task Selector decide their next inner task via the LLM
		# instead of diagram order. WI-001359: every ad-hoc activation is
		# audited. Both hooks are process-global engine state —
		# install/uninstall them around the run.
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance.ai_task_selector import (
			make_adhoc_decider,
		)

		bpmn_engine.adhoc_next_task_decider = make_adhoc_decider(self, wf)
		bpmn_engine.adhoc_task_activated_logger = self._log_adhoc_activation
		self._pending_ai_jobs = []
		try:
			self._run_engine_inner(wf)
		finally:
			bpmn_engine.adhoc_next_task_decider = None
			bpmn_engine.adhoc_task_activated_logger = None

		# WI-001495: reflect parked AI work on the instance and hand ONLY the
		# AI work to the bpmn_ai_agent worker. The callers (start / advance /
		# receive_message / resume_parked_ai) persist the doc right after this
		# method returns, and the jobs fire enqueue_after_commit — so the job
		# always sees the committed parked state.
		self.waiting_for_ai = (
			1 if (self._pending_ai_jobs or self._has_parked_ai_tasks(wf)) else 0
		)
		self._enqueue_parked_ai_jobs()

	# ── WI-001495: park-and-enqueue seam for AI tasks ─────────────────────────

	_AI_SERVICE_TYPES = ("ai_agent", "ai_task_selector")

	# Durable AI Agent HITL: active-task rows for the human tools of a
	# suspended agent are synthetic (no SpiffWorkflow task behind them) —
	# their ids carry this prefix so completion routes to the resume path.
	AI_HUMAN_PREFIX = "aihuman::"

	# WI-001933: a Service Task that delegated to a remote A2A agent and is
	# waiting for the answer. Deliberately NOT the AI human marker: that one
	# means "a person must act" and is bound to AI Agent Run checkpoints,
	# while this task is waiting on a machine somewhere else. Rows spawned
	# when the REMOTE asks a question carry the a2ahuman:: prefix.
	A2A_WAITING_KEY = "_bpmn_a2a_waiting"
	A2A_HUMAN_PREFIX = "a2ahuman::"

	@staticmethod
	def _task_waiting_a2a(task) -> dict | None:
		"""The waiting-for-delegate marker delegate_task left on task.data,
		or None. A marked task must not be re-dispatched or completed — it
		leaves this state only through the a2a_result resume path."""
		data = getattr(task, "data", None)
		if not isinstance(data, dict):
			return None
		marker = data.get(BPMNProcessInstance.A2A_WAITING_KEY)
		return marker if isinstance(marker, dict) else None

	@staticmethod
	def _task_waiting_human(task) -> dict | None:
		"""The waiting-for-human marker a suspended ai_agent dispatch left on
		task.data, or None. A marked task is WAITING for a person: it must not
		be re-parked, re-dispatched, retried, or counted as waiting-for-AI."""
		data = getattr(task, "data", None)
		if isinstance(data, dict):
			marker = data.get("_bpmn_ai_waiting_human")
			if isinstance(marker, dict):
				return marker
		return None

	def _ai_parking_active(self) -> bool:
		"""
		Parking moves ONLY the AI work of an engine pass to the bpmn_ai_agent
		worker. Inactive in tests (no worker, auto-rollback) unless a test
		opts in via frappe.flags.bpmn_force_ai_parking.

		The chat delegation path (Logix / ProsAlly / Docu) opts OUT via
		frappe.flags.bpmn_disable_ai_parking so the agent runs INLINE and the
		HTTP turn returns the reply synchronously. Unlike a document save, the
		chat endpoint is an explicit waiter — the frontend expects the reply in
		the response, so blocking on the LLM is correct there. (Without this the
		agent parks async, the caller's read-back finds no fresh bot message,
		and it wrongly surfaces "reopen the chat" while the instance is fine.)
		"""
		if getattr(frappe.flags, "bpmn_disable_ai_parking", False):
			return False
		if frappe.flags.bpmn_force_ai_parking:
			return True
		return not frappe.flags.in_test

	def _ai_service_type(self, task) -> str:
		"""The serviceType of a task's compile-time extension config ('' if none)."""
		bpmn_id = getattr(task.task_spec, "bpmn_id", None) or task.task_spec.name
		task_cfg = getattr(self, "_service_task_extensions", {}).get(bpmn_id) or {}
		return task_cfg.get("serviceType", "")

	def _queue_parked_ai_job(self, kind: str, ident: str):
		"""
		Record one parked AI unit (an ai_agent service task or an
		ai_task_selector decision) for enqueueing after this engine pass.
		Deduplicated here AND by job_id at the queue (AC: one job per
		instance + task).
		"""
		jobs = getattr(self, "_pending_ai_jobs", None)
		if jobs is None:
			jobs = self._pending_ai_jobs = []
		if any(i == ident for _, i in jobs):
			return
		jobs.append((kind, ident))

	def _has_parked_ai_tasks(self, wf) -> bool:
		"""Any ai_agent service task still parked in STARTED state?

		A task suspended for a HUMAN does not count — the instance is waiting
		for a person (waiting_for_human), not for an AI job."""
		for t in wf.get_tasks(state=TaskState.STARTED):
			if getattr(t.task_spec, "manual", False) or isinstance(
				t.task_spec, SubWorkflowTask
			):
				continue
			if self._task_waiting_human(t):
				continue
			if self._ai_service_type(t) in self._AI_SERVICE_TYPES:
				return True
		return False

	def _enqueue_parked_ai_jobs(self):
		"""One bpmn_ai_agent job per parked AI unit, deduplicated by job_id."""
		jobs, self._pending_ai_jobs = getattr(self, "_pending_ai_jobs", []), []
		for kind, ident in jobs:
			frappe.enqueue(
				"one_bpmn.one_bpmn.doctype.bpmn_process_instance"
				".bpmn_process_instance.run_parked_ai_task",
				# AI-only jobs — the rest of the pass already ran inline
				# (WI-001494/WI-001495).
				queue="bpmn_ai_agent",
				timeout=600,
				enqueue_after_commit=True,
				job_id=f"bpmn-ai-{self.name}-{ident}",
				deduplicate=True,
				instance_name=self.name,
				kind=kind,
				task_id=ident,
				run_as_user=frappe.session.user,
			)

	# ── Durable AI Agent HITL: suspend / spawn human task / resume ────────────

	def _on_ai_agent_suspended(self, task):
		"""An ai_agent dispatch suspended for a human tool: spawn the chosen
		User/Manual shape as a pending human task (active-task row + Frappe
		assignment — the existing user-task machinery) and bind it to the
		checkpoint. The service task itself stays STARTED with the marker."""
		marker = self._task_waiting_human(task) or {}
		shape_id = marker.get("tool") or ""
		run_name = marker.get("run") or ""
		arguments = marker.get("arguments") or {}

		# WI-001933: the pause may be on another AGENT rather than a person.
		# Nothing to assign and nobody to notify — the delegated task is the
		# thing being waited on, so bind it to the run and let the reconciler
		# wake this one when it answers.
		if marker.get("waits_on") == "a2a":
			self._bind_a2a_wait(task, marker)
			return

		# The human shape's designer config (assignment mode, actions, label)
		# comes from the same user_task_extensions every real User Task uses.
		if not hasattr(self, "_user_task_extensions"):
			_spec_snap = self._load_json(self.serialized_spec or "{}") or {}
			self._user_task_extensions = _spec_snap.get("user_task_extensions", {})
		self._refresh_user_task_extensions_from_model()
		shape_cfg = getattr(self, "_user_task_extensions", {}).get(shape_id, {}) or {}
		label = marker.get("label") or shape_cfg.get("label") or shape_id

		row_id = f"{self.AI_HUMAN_PREFIX}{frappe.generate_hash(length=10)}"

		# Assignment: same resolver as real user tasks — the synthetic task
		# carries the shape's bpmn_id and the LLM's arguments as data.
		synthetic = frappe._dict(
			data=dict(arguments),
			task_spec=frappe._dict(bpmn_id=shape_id, name=shape_id, description=label),
			workflow=frappe._dict(data={}),
		)
		assigned_user = ""
		try:
			assigned_user = resolve_assignment(self, synthetic) or ""
		except Exception:
			frappe.log_error(
				title=f"AI HITL: assignment resolution failed ({shape_id})",
				message=frappe.get_traceback(),
			)

		self.append(
			"active_tasks",
			{
				"task_id": row_id,
				"task_name": label,
				"task_type": "AI Human Task",
				"status": "Waiting",
				"started_at": now_datetime(),
				"assigned_user": assigned_user,
				"assigned_role": shape_cfg.get("assigneeRole", "") or "",
				"task_actions": shape_cfg.get("taskActions", "") or "",
				"target_doctype": self.context_doctype,
				"target_docname": self.context_docname,
			},
		)

		for u in split_users(assigned_user):
			try:
				add_frappe_assignment(self, u, label, shape_id, task_id=row_id, task_cfg=shape_cfg)
			except Exception:
				frappe.log_error(
					title=f"AI HITL: assignment creation failed ({shape_id})",
					message=frappe.get_traceback(),
				)

		self._log_task(
			task_id=row_id,
			task_name=label,
			action="Started",
			data={
				"source": "ai_agent_human_tool",
				"agent_bpmn_id": getattr(task.task_spec, "bpmn_id", None) or task.task_spec.name,
				"arguments": arguments,
			},
		)

		# Bind row ↔ checkpoint and surface the wait on the instance.
		marker["row_id"] = row_id
		marker["label"] = label
		task.data["_bpmn_ai_waiting_human"] = marker
		if run_name:
			try:
				frappe.db.set_value(
					"AI Agent Run", run_name, "pending_human_task", row_id,
					update_modified=False,
				)
				from one_bpmn.agents import checkpoint as _checkpoint
				run_doc = frappe.get_doc("AI Agent Run", run_name)
				payload = json.loads(run_doc.checkpoint or "{}")
				payload["human_row_id"] = row_id
				run_doc.db_set("checkpoint", json.dumps(payload, default=str), update_modified=False)
			except Exception:
				frappe.log_error(
					title=f"AI HITL: checkpoint binding failed ({run_name})",
					message=frappe.get_traceback(),
				)
		self.waiting_for_human = label

	def complete_ai_human_task(self, task_id: str, data: dict = None) -> None:
		"""Complete a pending AI human task and hand its output to the
		suspended agent (resume runs as a bpmn_ai_agent job).

		Caller (instance_api.complete_task) has already validated assignment,
		action and document permissions — exactly like a real User Task."""
		data = data or {}
		row = next(
			(r for r in self.active_tasks if r.task_id == task_id), None
		)
		if row is None or row.status != "Waiting":
			frappe.throw(_("Task '{0}' is not waiting for completion.").format(task_id))

		from one_bpmn.agents import checkpoint as _checkpoint

		run_name = _checkpoint.get_suspended_run(self.name, human_row_id=task_id)
		if not run_name:
			frappe.throw(
				_("No suspended AI agent is waiting on task '{0}' — it may have been resumed already.").format(
					row.task_name or task_id
				)
			)

		# Record completion on the row (same bookkeeping as advance())
		_completed_at = now_datetime()
		prev_assigned = {
			u
			for r in self.active_tasks
			if r.status == "Waiting" and r.assigned_user
			for u in split_users(r.assigned_user)
		}
		row.status = "Completed"
		row.end_time = _completed_at
		if row.started_at:
			row.timer_duration = int(
				frappe.utils.time_diff_in_seconds(_completed_at, row.started_at)
			)
		self._log_task(
			task_id=task_id,
			task_name=row.task_name,
			action="Completed",
			data=data,
		)

		# Close the ToDos of users who now have no Waiting row left
		still_assigned = {
			u
			for r in self.active_tasks
			if r.status == "Waiting" and r.assigned_user
			for u in split_users(r.assigned_user)
		}
		for user in prev_assigned - still_assigned:
			remove_frappe_assignment(self, user, status="Closed")

		# The human's output becomes the pending tool call's result.
		_checkpoint.store_human_result(run_name, data)

		self.waiting_for_human = ""
		self.modified = frappe.utils.now()
		self.modified_by = frappe.session.user
		self.db_update()
		self.update_children()

		# Resume in the AI worker — one job, deduplicated, after commit.
		payload = json.loads(
			frappe.db.get_value("AI Agent Run", run_name, "checkpoint") or "{}"
		)
		frappe.enqueue(
			"one_bpmn.one_bpmn.doctype.bpmn_process_instance"
			".bpmn_process_instance.run_parked_ai_task",
			queue="bpmn_ai_agent",
			timeout=600,
			enqueue_after_commit=True,
			job_id=f"bpmn-ai-{self.name}-hr-{task_id}",
			deduplicate=True,
			instance_name=self.name,
			kind="human_resume",
			task_id=payload.get("wf_task_id") or "",
			run_as_user=frappe.session.user,
		)

	def _bind_a2a_wait(self, task, marker: dict) -> None:
		"""Bind a suspended agent to the delegation it is waiting on.

		The agent's run holds the checkpoint; the A2A Task row is what will go
		terminal. Linking them (``agent_run`` on the row, ``wf_task_id`` so the
		resume knows which step to wake) is what lets the local reconciler
		finish the job — without it the answer arrives with nobody waiting,
		which is exactly the bug this closes.
		"""
		a2a_task = marker.get("a2a_task")
		run_name = marker.get("run") or ""
		if not a2a_task:
			return
		try:
			frappe.db.set_value(
				"A2A Task",
				a2a_task,
				{
					# caller_agent_run, NOT agent_run: that one is the run DOING
					# the work and is what derives this task's state, so writing
					# the waiting caller there made a finished delegation report
					# the CALLER's suspension back as "input-required" and it
					# never looked terminal. Same trap as instance vs
					# caller_instance, one field along.
					"caller_agent_run": run_name or None,
					"caller_instance": self.name,
					# Deliberately NOT caller_wf_task_id: that field means "a
					# parked Service Task with this SpiffWorkflow id", and the
					# reconciler resumes it directly. Here the waiting thing is
					# an agent mid-turn, which resumes through its checkpoint.
					"wf_task_id": str(getattr(task, "id", "") or ""),
					"resume_enqueued": 0,
				},
				update_modified=False,
			)
		except Exception:
			frappe.log_error(
				title=f"A2A: could not bind the delegation to its waiting agent ({a2a_task})",
				message=frappe.get_traceback(),
			)
		# Deliberately NOT waiting_for_human: nobody is being asked for anything.
		# That field drives the "AI agent waiting for a human task" banner, and
		# setting it here had a delegation to another AGENT telling the viewer a
		# person was holding it up — sending someone to look for a task that
		# does not exist. A banner of its own needs a field of its own; until
		# then, saying nothing beats saying something false.
		self._log_task(
			# Its own prefix: a2ahuman:: means "a person must answer a remote's
			# question" and is an active-task row; this is only an audit entry
			# for an agent waiting on another agent.
			task_id=f"a2await::{a2a_task}",
			task_name=marker.get("label") or marker.get("tool") or "",
			action="Started",
			data={
				"source": "ai_agent_a2a_tool",
				"agent_bpmn_id": getattr(task.task_spec, "bpmn_id", None) or task.task_spec.name,
				"a2a_task": a2a_task,
				"arguments": marker.get("arguments") or {},
			},
		)

	# ── WI-001933: delegated-task results and remote questions ───────────────

	def _apply_a2a_result(self, task, marker: dict) -> bool:
		"""Apply a delegated task's outcome to its parked Service Task.

		Returns True when the task may now complete, False while the
		delegation is still running (it stays parked). A terminal failure
		with failOnError raises, so it lands on the existing bounded-retry →
		Errored path rather than a new failure mechanism.
		"""
		from one_bpmn.one_bpmn.connectors.a2a_client_ops import A2A_WAITING_KEY
		from one_bpmn.one_bpmn.integrations.a2a_client import A2ARemoteError

		a2a_task_name = marker.get("a2a_task")
		row = (
			frappe.db.get_value(
				"A2A Task",
				a2a_task_name,
				["state", "result", "error_message", "bpmn_id"],
				as_dict=True,
			)
			if a2a_task_name
			else None
		)
		if not row:
			return False

		terminal = {"completed", "failed", "canceled", "rejected", "timed-out"}
		if row.state not in terminal:
			return False

		bpmn_id = getattr(task.task_spec, "bpmn_id", None) or task.task_spec.name
		task_cfg = getattr(self, "_service_task_extensions", {}).get(bpmn_id) or {}
		result_var = task_cfg.get("resultVariable")
		fail_on_error = str(task_cfg.get("failOnError") or "").lower() in ("1", "true", "yes")

		task.data.pop(A2A_WAITING_KEY, None)

		if row.state == "completed":
			payload = frappe.parse_json(row.result or "{}") or {}
			if result_var:
				task.data[result_var] = payload
			return True

		if fail_on_error:
			raise A2ARemoteError(
				row.state, row.error_message or f"delegated task {row.state}"
			)
		if result_var:
			task.data[result_var] = {
				"a2a_state": row.state,
				"a2a_error": row.error_message or "",
			}
		return True

	def _on_a2a_input_required(self, a2a_task_name: str, prompt: str) -> None:
		"""The REMOTE agent asked a question. Spawn a human task to answer it.

		A simpler sibling of _on_ai_agent_suspended on purpose: that one is
		bound to a shape's user_task_extensions and an AI Agent Run
		checkpoint, while this pause lives entirely on the A2A Task row.
		"""
		row_data = frappe.db.get_value(
			"A2A Task",
			a2a_task_name,
			["input_assignee", "input_role", "remote_agent", "instance"],
			as_dict=True,
		)
		if not row_data:
			return
		label = f"Answer {row_data.remote_agent}: {(prompt or '').strip()[:80]}"
		row_id = f"{self.A2A_HUMAN_PREFIX}{frappe.generate_hash(length=10)}"
		assigned_user = row_data.input_assignee or self.initiated_by or ""

		self.append(
			"active_tasks",
			{
				"task_id": row_id,
				"task_name": label,
				"task_type": "A2A Human Task",
				"status": "Waiting",
				"started_at": now_datetime(),
				"assigned_user": assigned_user,
				"assigned_role": row_data.input_role or "",
				"target_doctype": self.context_doctype,
				"target_docname": self.context_docname,
			},
		)
		for user in split_users(assigned_user):
			try:
				add_frappe_assignment(self, user, label, a2a_task_name, task_id=row_id)
			except Exception:
				frappe.log_error(
					title=f"A2A HITL: assignment creation failed ({a2a_task_name})",
					message=frappe.get_traceback(),
				)
		self._log_task(
			task_id=row_id,
			task_name=label,
			action="Started",
			data={"source": "a2a_input_required", "a2a_task": a2a_task_name},
		)
		frappe.db.set_value(
			"A2A Task", a2a_task_name, "pending_human_task", row_id, update_modified=False
		)
		self.waiting_for_human = label
		self.modified = frappe.utils.now()
		self.db_update()
		self.update_children()

	def complete_a2a_human_task(self, task_id: str, data: dict = None) -> None:
		"""Send a person's answer back to the remote agent that asked.

		Mirror of complete_ai_human_task: the caller (instance_api.
		complete_task) has already validated assignment and permissions.
		"""
		from one_bpmn.one_bpmn.integrations import a2a_client

		data = data or {}
		row = next((r for r in self.active_tasks if r.task_id == task_id), None)
		if row is None or row.status != "Waiting":
			frappe.throw(_("Task '{0}' is not waiting for completion.").format(task_id))

		a2a_task_name = frappe.db.get_value(
			"A2A Task", {"pending_human_task": task_id, "state": "input-required"}, "name"
		)
		if not a2a_task_name:
			frappe.throw(_("No delegated task is waiting on '{0}'.").format(task_id))
		a2a_task = frappe.get_doc("A2A Task", a2a_task_name)

		answer = data.get("response") or data.get("answer") or ""
		_completed_at = now_datetime()
		prev_assigned = {
			u
			for r in self.active_tasks
			if r.status == "Waiting" and r.assigned_user
			for u in split_users(r.assigned_user)
		}
		row.status = "Completed"
		row.end_time = _completed_at
		if row.started_at:
			row.timer_duration = int(
				frappe.utils.time_diff_in_seconds(_completed_at, row.started_at)
			)
		self._log_task(task_id=task_id, task_name=row.task_name, action="Completed", data=data)

		still_assigned = {
			u
			for r in self.active_tasks
			if r.status == "Waiting" and r.assigned_user
			for u in split_users(r.assigned_user)
		}
		for user in prev_assigned - still_assigned:
			remove_frappe_assignment(self, user, status="Closed")

		self.waiting_for_human = ""
		self.modified = frappe.utils.now()
		self.modified_by = frappe.session.user
		self.db_update()
		self.update_children()

		try:
			result = a2a_client.message_send(
				a2a_task.remote_agent,
				answer,
				task_id=a2a_task.remote_task_id,
				context_id=a2a_task.context_id,
			)
		except Exception as exc:  # noqa: BLE001 — a dead remote fails the task
			a2a_task.db_set(
				{"state": "failed", "error_message": str(exc)[:500], "pending_human_task": ""},
				update_modified=True,
			)
			_enqueue_a2a_resume(self.name, a2a_task.wf_task_id, a2a_task.name)
			return

		state = a2a_client.remote_state(result) or "working"
		updates = {"pending_human_task": "", "state": state}
		if state == "completed":
			text = a2a_client.remote_text(result)
			updates.update(
				{
					"result": frappe.as_json({"text": text}),
					"status_message": text[:500],
					"completed_at": now_datetime(),
				}
			)
		a2a_task.db_set(updates, update_modified=True)

		if state in ("completed", "failed", "canceled", "rejected", "timed-out"):
			_enqueue_a2a_resume(self.name, a2a_task.wf_task_id, a2a_task.name)
		else:
			# Back to waiting: reset the backoff so the next poll is prompt.
			remote = frappe.get_doc("A2A Remote Agent", a2a_task.remote_agent)
			a2a_task.db_set(
				{
					"poll_attempts": 0,
					"next_poll_at": frappe.utils.add_to_date(
						now_datetime(), seconds=frappe.utils.cint(remote.poll_base_interval) or 60
					),
				},
				update_modified=False,
			)

	def _log_adhoc_activation(self, sp, task):
		"""WI-001359: 'Ad-Hoc Task Activated' audit entry. The existing
		instance+task_id+action dedup in _log_task prevents duplicates on
		engine restarts re-processing the same state."""
		self._log_task(
			task_id=str(task.id),
			task_name=bpmn_engine.get_task_display_name(task),
			action="Ad-Hoc Task Activated",
			data={
				"bpmn_id": getattr(task.task_spec, "bpmn_id", None) or task.task_spec.name,
				"parent_subprocess": sp.spec.name,
			},
		)

	def log_ai_task_selected(self, bpmn_id: str, chosen_tools: list, arguments: dict = None):
		"""WI-001359: 'AI Task Selected' audit entry — a lightweight
		cross-reference to the decision, not a duplicate of the full
		per-call record on AI Agent Tool Call (WI-001358)."""
		summary = json.dumps(arguments or {}, default=str)
		if len(summary) > 500:
			summary = summary[:500] + "…"
		self._log_task(
			task_id=f"{bpmn_id}::decision::{'+'.join(chosen_tools) or 'none'}",
			task_name=f"AI Task Selector ({bpmn_id})",
			action="AI Task Selected",
			data={"chosen_tools": chosen_tools, "arguments_summary": summary},
		)

	def _run_engine_inner(self, wf):
		wf.refresh_waiting_tasks()

		cap_hit = True
		for _ in range(20):  # safety cap — no real workflow needs > 20 passes
			bpmn_engine.do_engine_steps_gated(
				wf,
				did_complete_task=self._on_engine_task_complete,
				did_complete_adhoc_task=self._on_adhoc_task_complete,
			)

			# Find non-manual tasks left in STARTED state.  These are
			# ServiceTasks waiting for us to dispatch their action and
			# explicitly call task.complete().
			# Subworkflow containers (Sub-Process, Ad-hoc Subprocess, Call
			# Activity, Transaction) also sit in STARTED while their inner
			# workflow runs — force-completing them here abandons their
			# children and runs the parent process straight to the End Event
			# while inner user tasks are still pending. They complete on
			# their own when the inner workflow finishes.
			# Durable HITL: an ai_agent suspended for a human stays STARTED but
			# is WAITING — never re-parked, never re-dispatched. It leaves this
			# state only through the human_resume path.
			started_tasks = [
				t
				for t in wf.get_tasks(state=TaskState.STARTED)
				if not getattr(t.task_spec, "manual", False)
				and not isinstance(t.task_spec, SubWorkflowTask)
				and not self._task_waiting_human(t)
				and not self._task_waiting_a2a(t)
			]

			# WI-001495: AI service tasks never dispatch inline — leave them
			# parked in STARTED and queue ONLY their LLM work on the
			# bpmn_ai_agent worker (run_parked_ai_task dispatches and resumes).
			# Non-AI siblings in the same pass still dispatch inline below.
			if self._ai_parking_active():
				parked = [
					t for t in started_tasks if self._ai_service_type(t) == "ai_agent"
				]
				for t in parked:
					self._queue_parked_ai_job("service_task", str(t.id))
				started_tasks = [t for t in started_tasks if t not in parked]

			if not started_tasks:
				cap_hit = False
				break  # nothing left to advance — we're done

			for task in started_tasks:
				self._dispatch_service_task(task)
				# Durable HITL (inline engine / tests): the dispatch suspended
				# for a human — spawn the human task and leave this task
				# STARTED. The next pass excludes it via the marker.
				if self._task_waiting_human(task):
					self._on_ai_agent_suspended(task)
					continue
				# WI-001933: the dispatch delegated to a remote agent that has
				# not answered yet. Leave the task STARTED; the poller resumes
				# it through kind="a2a_result".
				if self._task_waiting_a2a(task):
					self.waiting_for_ai = 1
					continue
				self._on_engine_task_complete(task)
				task.complete()
				# Ad-hoc inner tasks: refresh the context doc and record the
				# activation outcome AFTER the dispatch's writes landed —
				# doc-based completion conditions evaluate right after this.
				if isinstance(
					getattr(task.workflow, "spec", None), bpmn_engine.AdHocSubprocessSpec
				) and getattr(task.task_spec, "bpmn_id", None):
					self._on_adhoc_task_complete(task)

		if cap_hit:
			# Flag — don't raise. State serializes correctly and the next
			# advance() resumes from here; ad-hoc subprocesses with many inner
			# tasks may legitimately need more passes per call (WI-001350).
			pending_adhoc = bpmn_engine.adhoc_pending_head_tasks(wf)
			frappe.log_error(
				title="BPMN _run_engine pass cap reached",
				message=(
					f"Instance {self.name}: 20-pass cap hit with work remaining. "
					f"Parked ad-hoc heads: {[t.task_spec.name for t in pending_adhoc]}. "
					"Execution resumes on the next advance() call."
				),
			)

		# Final refresh catches conditional events that became true after
		# the engine steps ran (e.g. script task updated a doc field that
		# a downstream catch event now matches).
		wf.refresh_waiting_tasks()

	def _on_adhoc_task_complete(self, task):
		"""
		Fired after each ad-hoc inner task completes (WI-001350 Scenario 7).

		Inline <bpmn:script> tasks read the context doc from the shared
		script-engine environment, which is populated once per API call.
		Refreshing after every inner completion lets a later inline script
		see values an earlier one just wrote via frappe.db.set_value().
		Server-Script-backed tasks are unaffected either way — they call
		frappe.get_doc() fresh on every execution.
		"""
		if self.context_doctype and self.context_docname:
			bpmn_engine.refresh_context_doc(
				task.workflow.top_workflow, self.context_doctype, self.context_docname
			)

		# If the AI Task Selector activated this task, attach what it actually
		# produced to the recording (AI Agent Tool Call.outcome). No-op when no
		# matching outcome-less tool call exists (plain adhoc, chained tasks).
		try:
			from one_bpmn.agents.observability import record_activation_outcome

			bpmn_id = getattr(task.task_spec, "bpmn_id", None) or task.task_spec.name
			outcome = self._compose_task_outcome(task, bpmn_id)
			record_activation_outcome(self.name, bpmn_id, outcome)
		except Exception:
			frappe.log_error(
				title="BPMN: activation outcome recording failed",
				message=frappe.get_traceback(),
			)

	def _compose_task_outcome(self, task, bpmn_id: str) -> str:
		"""One-line, factual summary of what a completed ad-hoc inner task did,
		derived from its compile-time config and the data it wrote."""
		svc_cfg = getattr(self, "_service_task_extensions", {}).get(bpmn_id) or {}
		script_cfg = getattr(self, "_script_task_extensions", {}).get(bpmn_id) or {}
		parts = []

		if svc_cfg.get("serviceType") == "update_field":
			target = svc_cfg.get("updateFieldDoctype") or self.context_doctype or "document"
			try:
				for row in json.loads(svc_cfg.get("updateFieldRows") or "[]"):
					parts.append(f'set {target}.{row.get("field")} = "{row.get("value")}"')
			except Exception:
				pass

		script_name = script_cfg.get("serverScript") or svc_cfg.get("serverScript")
		if script_name:
			written = {}
			try:
				from one_bpmn.api.ai_assistant import _server_script_result_keys

				for key in _server_script_result_keys(script_name):
					if key in (task.data or {}):
						written[key] = task.data[key]
			except Exception:
				pass
			if written:
				values = ", ".join(f"{k} = {v!r}" for k, v in written.items())
				parts.append(f'ran Server Script "{script_name}" → {values}')
			else:
				parts.append(f'ran Server Script "{script_name}"')

		if svc_cfg.get("notificationName"):
			parts.append(f'sent notification "{svc_cfg["notificationName"]}"')

		task_type = type(task.task_spec).__name__
		if not parts and "UserTask" in task_type:
			parts.append(f"completed by {frappe.session.user}")

		summary = "; ".join(parts) if parts else "completed"
		return f"Completed {now_datetime().strftime('%H:%M:%S')} — {summary}"

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

		# Send Tasks complete inside the engine sweep (they never sit in
		# STARTED like service tasks), so this callback is where their
		# real-world action happens. Guarded by state: the STARTED dispatch
		# loop also calls this hook pre-complete for service tasks, which a
		# SendTask can never be.
		if isinstance(task_spec, bpmn_engine.SendTask) and bpmn_id:
			task_cfg = getattr(self, "_service_task_extensions", {}).get(bpmn_id, {})
			if task_cfg.get("notificationName"):
				dispatch_send_notification(self, task, task_cfg, bpmn_id)

		# A completed subprocess parent ends its AI Task Selector run (if
		# one exists) — the only moment a selector run is genuinely over.
		if isinstance(task_spec, SubWorkflowTask):
			try:
				from one_bpmn.agents.observability import finalize_open_selector_runs

				finalize_open_selector_runs(self.name, bpmn_id or spec_name)
			except Exception:
				pass

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
				dispatch_email(self, task, task_cfg,
					amp_html=task_cfg.get("ampHtml") or None)
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

		elif service_type == "connector":
			# Data-driven provider connector (Google Drive/Docs/Slides, …).
			# Errors are handled inside dispatch_connector: logged and non-fatal,
			# re-raised only when the task's failOnError is set so the instance
			# can be marked Errored.
			dispatch_connector(self, task, task_cfg, bpmn_id)

		elif service_type == "push_notification":
			try:
				dispatch_push_notification(self, task, task_cfg, bpmn_id)
			except Exception:
				frappe.log_error(
					title=f"BPMN ServiceTask: push_notification failed for task {bpmn_id}",
					message=frappe.get_traceback(),
				)

		elif service_type == "ai_agent":
			dispatch_ai_agent(self, task, task_cfg, bpmn_id)

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
			prev_assigned = set()
			for row in self.active_tasks:
				if row.status == "Waiting" and row.assigned_user:
					prev_assigned.update(split_users(row.assigned_user))

		# Keep completed rows + rows still waiting that are still ready.
		# AI human-task rows are synthetic (no engine task behind them) — a
		# Waiting one belongs to a suspended agent and must survive rebuilds.
		self.active_tasks = [
			row
			for row in self.active_tasks
			if row.status == "Completed"
			or row.task_id in new_ready_ids
			or (
				row.status == "Waiting"
				and str(row.task_id).startswith(self.AI_HUMAN_PREFIX)
			)
		]

		existing_waiting_ids = {row.task_id for row in self.active_tasks if row.status == "Waiting"}

		# Map of user → (task_name, task_cfg) for newly created rows
		# Used to pass notification settings to add_frappe_assignment
		new_user_task_cfgs = {}

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
			# Stash bpmn_id as a transient attribute (not persisted) for
			# add_frappe_assignment to read the user_task_extensions config.
			self.active_tasks[-1]._bpmn_id = bpmn_id_key

			# Track the task_cfg so we can pass notification settings below.
			# assigned_user may be a comma-joined list (Table Field mode) —
			# every one of those users gets the same task_cfg for notifications.
			for u in split_users(assigned_user):
				new_user_task_cfgs[u] = (task_name, task_cfg)

			self._log_task(
				task_id=tid,
				task_name=task_name,
				action="Started",
			)

		# Diff: which users are now assigned across all Waiting tasks.
		# A Waiting row's assigned_user may list multiple people (Table Field
		# mode) — any one of them can complete it, so each gets its own entry.
		curr_assigned = {}
		for row in self.active_tasks:
			if row.status == "Waiting" and row.assigned_user:
				for u in split_users(row.assigned_user):
					curr_assigned[u] = {
						"task_name": row.task_name,
						"bpmn_id": getattr(row, "_bpmn_id", ""),
						"task_id": row.task_id,
					}

		# Close ToDos for users who were assigned but no longer are
		# A preceding script task can override the close status via
		# task.data["todo_close_status"] (same pattern as assigned_role) —
		# defaults to "Closed" for every process that never sets it.
		#
		# wf.task_tree.data is the workflow ROOT's data and is never updated
		# by downstream script tasks (verified: it stays {} for the whole
		# run) — task.data only inherits forward along the execution path,
		# so the hint must be read off a task that's actually downstream of
		# the script that set it. ready_user_tasks (computed above) are the
		# tasks immediately following wherever the engine just stopped, so
		# they carry the current data forward; wf.last_task is a fallback
		# for the case where nothing is left ready (e.g. process about to
		# complete).
		todo_close_status = "Closed"
		for _t in ready_user_tasks:
			_hint = _t.data.get("todo_close_status")
			if _hint:
				todo_close_status = _hint
				break
		else:
			_last_task = getattr(wf, "last_task", None)
			if _last_task is not None:
				todo_close_status = _last_task.data.get("todo_close_status") or "Closed"
		for user in prev_assigned - set(curr_assigned.keys()):
			remove_frappe_assignment(self, user, status=todo_close_status)

		# Create ToDos for users who are newly assigned
		for user, info in curr_assigned.items():
			if user not in prev_assigned:
				task_name_cfg = new_user_task_cfgs.get(user, (info["task_name"], {}))
				add_frappe_assignment(
					self, user, info["task_name"],
					info.get("bpmn_id", ""),
					task_id=info.get("task_id", ""),
					task_cfg=task_name_cfg[1] if isinstance(task_name_cfg, tuple) else {},
				)

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
			self._settle_goal_completion("Completed")
		elif (
			not wf.get_tasks(state=TaskState.READY)
			and not wf.get_tasks(state=TaskState.WAITING)
			and not wf.get_tasks(state=TaskState.STARTED)
		):
			# Fallback: no pending tasks at all but is_completed() returned
			# False.  Treat as complete to avoid a forever-stuck instance.
			self.status = "Completed"
			self.completed_at = now_datetime()
			self._settle_goal_completion("Completed")

	def _settle_goal_completion(self, instance_status: str):
		"""Whether the map reached its end event is the strongest evidence of
		whether its agents achieved their goals (WI-001823) — and it can only be
		read here, because a run finishes long before the instance does.

		Only fills in runs that could not decide for themselves; it never
		overwrites an outcome the executor already established. Never raises:
		recording an outcome must not be able to break the process that produced
		it.
		"""
		try:
			from one_bpmn.agents.goal_completion import settle_for_instance

			settle_for_instance(self.name, instance_status)
		except Exception:
			frappe.log_error(
				title="goal completion settle failed",
				message=frappe.get_traceback(),
			)

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

	def _refresh_user_task_extensions_from_model(self):
		"""
		Merge notification-related attributes from the **active** process model's
		compiled spec into this instance's ``_user_task_extensions``.

		The instance stores a snapshot of the spec at start time.  If the process
		model is re-deployed with new ``notifyAssignee`` / ``notifyAssigneeBody``
		settings *after* an instance has started, the instance's snapshot will be
		stale.  This method patches in those notification-only keys from the live
		model so that running instances transparently pick up notification changes.

		Only ``notifyAssignee`` and ``notifyAssigneeBody`` are refreshed — all
		other extension keys (assigneeMode, taskActions, etc.) continue to come
		from the instance's own snapshot to preserve consistency.
		"""
		_NOTIFY_KEYS = ("notifyAssignee", "notifyAssigneeBody")

		try:
			model_spec_json = frappe.db.get_value(
				"BPMN Process Model", self.process_model, "serialized_spec"
			)
			if not model_spec_json:
				return

			model_spec = self._load_json(model_spec_json) or {}
			model_user_exts = model_spec.get("user_task_extensions", {})

			for bpmn_id, model_cfg in model_user_exts.items():
				inst_cfg = self._user_task_extensions.setdefault(bpmn_id, {})
				for key in _NOTIFY_KEYS:
					if key in model_cfg:
						inst_cfg[key] = model_cfg[key]
					else:
						inst_cfg.pop(key, None)
		except Exception:
			frappe.log_error(
				title=f"BPMN: Failed to refresh notifyAssignee config for instance {self.name}",
				message=frappe.get_traceback(),
			)

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


def _job_retry_cap(instance, kind: str, task_id: str) -> int:
	"""
	WI-001497: bounded retries for job-level failures reuse the panel's
	aiMaxRetries setting (the same field that already governs the executor's
	in-process LLM retries) — no new fields. Falls back to the executor's
	default (2) when the config can't be resolved.
	"""
	try:
		spec = json.loads(instance.serialized_spec or "{}") or {}
		exts = spec.get("service_task_extensions", {}) or {}
		if kind == "adhoc_decision":
			cfg = exts.get(task_id) or {}
		else:
			# task_id is a runtime UUID — resolvable to a bpmn_id only via the
			# workflow (whose restore may be the thing that failed). When the
			# model has exactly one ai_agent task the config is unambiguous.
			ai_cfgs = [
				c for c in exts.values() if (c or {}).get("serviceType") == "ai_agent"
			]
			cfg = ai_cfgs[0] if len(ai_cfgs) == 1 else {}
		return int(cfg.get("aiMaxRetries", 2) or 2)
	except Exception:
		return 2


def _enqueue_a2a_resume(instance_name: str, wf_task_id: str, a2a_task_name: str) -> None:
	"""WI-001933: resume a parked delegation through the SAME worker path AI
	tasks use — row lock, engine_in_progress gate, bounded retries and
	Errored-on-exhaustion all come for free."""
	if not (instance_name and wf_task_id):
		return
	# Record that this task's step has been handed a resume job. The local
	# reconciler uses it to tell "finished and already woken" from "finished
	# between two checks and still parked" — without it, an agent that
	# completes in the gap leaves its caller parked forever.
	if a2a_task_name and frappe.db.exists("A2A Task", a2a_task_name):
		frappe.db.set_value("A2A Task", a2a_task_name, "resume_enqueued", 1, update_modified=False)
	frappe.enqueue(
		"one_bpmn.one_bpmn.doctype.bpmn_process_instance"
		".bpmn_process_instance.run_parked_ai_task",
		queue="bpmn_ai_agent",
		timeout=600,
		enqueue_after_commit=True,
		job_id=f"bpmn-ai-{instance_name}-a2a-{a2a_task_name}",
		deduplicate=True,
		instance_name=instance_name,
		kind="a2a_result",
		task_id=wf_task_id,
		run_as_user=frappe.session.user,
	)


def run_parked_ai_task(
	instance_name: str, kind: str, task_id: str, run_as_user: str = None, attempt: int = 0
):
	"""
	WI-001495: bpmn_ai_agent job — execute ONE parked AI unit (an ai_agent
	Service Task dispatch or an ai_task_selector decision) and resume the
	instance. Enqueued by _enqueue_parked_ai_jobs with
	job_id=f"bpmn-ai-{instance}-{task_id}" (deduplicate=True), so at most one
	job exists per parked unit.

	Failure policy (WI-001497):
	- LLM/provider failures are retried IN-PROCESS by the executor up to the
	  panel's aiMaxRetries and recorded on AI Agent Run.retry_count; when the
	  executor exhausts its retries the dispatch writes the error variables
	  and the flow continues — identical to inline dispatch (parity).
	- Job-level failures (engine restore, DB errors, crashes) re-enqueue this
	  job with attempt+1 while attempt < aiMaxRetries; the parked task stays
	  STARTED and the instance stays Active ("Waiting for AI execution").
	- On exhaustion the instance is marked Errored, the error is recorded on
	  the task's activity log, and the task stays parked so retry_ai_task
	  (manual retry) can re-kick it.
	"""
	if run_as_user:
		frappe.set_user(run_as_user)

	# Row lock serializes concurrent engine passes on the same instance
	instance = frappe.get_doc("BPMN Process Instance", instance_name, for_update=True)

	# WI-001498: the gate is held ONLY while this AI job actively executes.
	# complete_task rejects user actions while it is set; it is ALWAYS
	# cleared in the finally below (crash included), so a waiting instance
	# (parked AI, human task, catch event) never stays locked.
	frappe.db.set_value(
		"BPMN Process Instance", instance_name, "engine_in_progress", 1, update_modified=False
	)
	try:
		instance.resume_parked_ai(kind=kind, task_id=task_id)
	except Exception:
		retry_cap = _job_retry_cap(instance, kind, task_id)
		frappe.log_error(
			title=(
				f"BPMN parked AI job failed: {instance_name} "
				f"(attempt {attempt + 1}/{retry_cap + 1})"
			),
			message=frappe.get_traceback(),
		)
		if attempt < retry_cap:
			# Bounded retry: same unit, next attempt. Distinct job_id so the
			# dedup of the original job can't swallow the retry.
			frappe.enqueue(
				"one_bpmn.one_bpmn.doctype.bpmn_process_instance"
				".bpmn_process_instance.run_parked_ai_task",
				queue="bpmn_ai_agent",
				timeout=600,
				enqueue_after_commit=True,
				job_id=f"bpmn-ai-{instance_name}-{task_id}-r{attempt + 1}",
				deduplicate=True,
				instance_name=instance_name,
				kind=kind,
				task_id=task_id,
				run_as_user=run_as_user,
				attempt=attempt + 1,
			)
		else:
			# Exhausted: surface the failure. The task stays parked (STARTED)
			# so a manual retry can resume exactly where it stopped.
			frappe.db.set_value("BPMN Process Instance", instance_name, "status", "Errored")
			frappe.db.set_value(
				"BPMN Process Instance",
				instance_name,
				"waiting_for_ai",
				0,
				update_modified=False,
			)
			instance._log_task(
				task_id=task_id,
				task_name=f"AI job ({kind})",
				action="Errored",
				data={
					"kind": kind,
					"attempts": attempt + 1,
					"error": frappe.get_traceback()[-1000:],
				},
			)
	finally:
		# WI-001498: release the gate unconditionally — success, retry
		# scheduled, or exhausted. The instance must never stay locked.
		frappe.db.set_value(
			"BPMN Process Instance",
			instance_name,
			"engine_in_progress",
			0,
			update_modified=False,
		)
		frappe.publish_realtime(
			"bpmn_instance_updated",
			{
				"instance_name": instance_name,
				"status": frappe.db.get_value("BPMN Process Instance", instance_name, "status"),
				"waiting_for_ai": frappe.db.get_value(
					"BPMN Process Instance", instance_name, "waiting_for_ai"
				),
				"waiting_for_human": frappe.db.get_value(
					"BPMN Process Instance", instance_name, "waiting_for_human"
				),
				"context_doctype": instance.context_doctype or "",
				"context_docname": instance.context_docname or "",
			},
			after_commit=True,
			user="all",
		)
