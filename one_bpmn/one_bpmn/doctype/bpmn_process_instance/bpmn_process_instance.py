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

		# Inject user data into task
		if data:
			task.data.update(data)

		# Mark the active_tasks row as Completed
		for row in self.active_tasks:
			if row.task_id == task_id:
				row.status = "Completed"

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
		self._sync_active_tasks(wf)

		self._check_completion(wf)

		# ignore_version=True prevents TimestampMismatchError when a concurrent
		# doc_update event (e.g. from the realtime broadcast causing the Frappe
		# form to reload) updates the DB timestamp between get_doc() and save().
		# advance() is the authoritative writer of workflow state so bypassing
		# the optimistic-lock check is correct here.
		self.save(ignore_permissions=True, ignore_version=True)

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
				"task_action_mode": getattr(row, "task_action_mode", None) or "manual",
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

		For 'frappe_workflow' mode: calls Frappe's get_transitions(doc) so
		only transitions the CURRENT USER is allowed to take (filtered by
		role, current workflow state, and Python conditions on the transition)
		are shown — identical to Frappe's native workflow action panel.

		For 'manual' mode: parses the stored task_actions (JSON or CSV)
		and returns comma-separated action names.
		"""
		mode = getattr(row, "task_action_mode", None) or "manual"
		if mode == "frappe_workflow":
			if not (self.context_doctype and self.context_docname):
				return ""
			try:
				from frappe.model.workflow import get_transitions

				doc = frappe.get_doc(self.context_doctype, self.context_docname)
				transitions = get_transitions(doc)
				return ",".join(str(t["action"]) for t in transitions)
			except Exception:
				pass
			return ""
		# Manual mode — extract just the action names
		raw = getattr(row, "task_actions", "") or ""
		actions = self._parse_task_actions_json(raw)
		return ",".join(a.get("action", "") for a in actions if a.get("action"))

	def _resolve_task_actions_detail(self, row) -> list:
		"""
		Return the full structured action list with per-action flags.

		For 'frappe_workflow' mode: returns actions from Frappe transitions
		(no per-action flags since they come from the Frappe Workflow).

		For 'manual' mode: returns the parsed JSON/CSV list of action dicts
		with all per-action metadata (confirmTransition, requireDigitalSignature).
		"""
		mode = getattr(row, "task_action_mode", None) or "manual"
		if mode == "frappe_workflow":
			if not (self.context_doctype and self.context_docname):
				return []
			try:
				from frappe.model.workflow import get_transitions

				doc = frappe.get_doc(self.context_doctype, self.context_docname)
				transitions = get_transitions(doc)
				return [{"action": str(t["action"])} for t in transitions]
			except Exception:
				pass
			return []
		raw = getattr(row, "task_actions", "") or ""
		return self._parse_task_actions_json(raw)

	def _apply_frappe_workflow_action(self, action: str) -> None:
		"""
		Apply a Frappe workflow action on the context document.

		Mirrors exactly what happens when a user clicks an action button
		in Frappe's native form view:
		  1. apply_workflow() validates the transition (role + self-approval).
		  2. Updates workflow_state_field on the document.
		  3. Handles docstatus changes (draft→submit, submitted→cancel, etc.).
		  4. Adds a Workflow comment to the document's timeline.

		Raises frappe.ValidationError / WorkflowTransitionError on failure.
		"""
		if not (self.context_doctype and self.context_docname):
			frappe.throw(_("Cannot apply Frappe workflow: no context document linked to this instance."))
		from frappe.model.workflow import apply_workflow as frappe_apply_workflow

		doc = frappe.get_doc(self.context_doctype, self.context_docname)
		frappe_apply_workflow(doc, action)

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
			triggered_by = self.initiated_by or frappe.session.user

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
				from one_bpmn.api import _apply_bpmn_workflow_state

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
				self._dispatch_email_notification(task, task_cfg)
			except Exception:
				# Email failures are non-fatal: log and continue so the
				# workflow can complete even if the email account is not
				# configured or the mail server is unreachable.
				frappe.log_error(
					title=f"BPMN ServiceTask: send_email failed for task {bpmn_id}",
					message=frappe.get_traceback(),
				)

		elif service_type == "update_field":
			self._dispatch_update_field(task, task_cfg, bpmn_id)

		elif service_type == "google_chat":
			# Error handling is fully inside _dispatch_google_chat;
			# failures are non-fatal and logged there.
			self._dispatch_google_chat(task, task_cfg, bpmn_id)

		elif service_type == "push_notification":
			try:
				self._dispatch_push_notification(task, task_cfg, bpmn_id)
			except Exception:
				frappe.log_error(
					title=f"BPMN ServiceTask: push_notification failed for task {bpmn_id}",
					message=frappe.get_traceback(),
				)

		return True  # default: complete the task

	def _dispatch_update_field(self, task, task_cfg: dict, bpmn_id: str) -> None:
		"""
		Update one or more fields on a document in a single service task.

		Reads ``updateFieldRows`` — a JSON array of ``{field, value}`` objects —
		and applies them in a single ``frappe.db.set_value`` call.  Every value
		is Jinja2-rendered before being written.

		Backward-compatible: if ``updateFieldRows`` is absent, falls back to the
		legacy single-field ``updateFieldName`` / ``updateFieldValue`` keys so
		existing diagrams continue to work unchanged.

		Service task configuration keys (from BPMN XML):
		    updateFieldDoctype  — DocType to update (falls back to context_doctype)
		    updateFieldRows     — JSON: [{"field": "status", "value": "Approved"}, ...]
		    updateFieldName     — (legacy) single field name
		    updateFieldValue    — (legacy) single field value
		"""
		import json as _json

		doctype = task_cfg.get("updateFieldDoctype") or self.context_doctype
		docname = self.context_docname

		if not (doctype and docname):
			frappe.log_error(
				title=f"BPMN ServiceTask: update_field misconfigured ({bpmn_id})",
				message=f"Task {bpmn_id} is missing doctype={doctype!r} or docname={docname!r}.",
			)
			return

		rows_json = task_cfg.get("updateFieldRows", "")
		if rows_json:
			try:
				rows = _json.loads(rows_json)
				if not isinstance(rows, list):
					frappe.log_error(
						title=f"BPMN ServiceTask: update_field misconfigured ({bpmn_id})",
						message=(
							f"updateFieldRows decoded to {type(rows).__name__}, expected list. "
							f"Raw value: {rows_json!r}"
						),
					)
					return
			except Exception:
				frappe.log_error(
					title=f"BPMN ServiceTask: update_field invalid JSON ({bpmn_id})",
					message=f"updateFieldRows is not valid JSON: {rows_json!r}",
				)
				return
		else:
			legacy_field = task_cfg.get("updateFieldName", "")
			legacy_value = task_cfg.get("updateFieldValue", "")
			if not legacy_field:
				frappe.log_error(
					title=f"BPMN ServiceTask: update_field misconfigured ({bpmn_id})",
					message=f"Task {bpmn_id} has no updateFieldRows and no updateFieldName.",
				)
				return
			rows = [{"field": legacy_field, "value": legacy_value}]

		if not rows:
			return

		try:
			doc = frappe.get_doc(doctype, docname)
		except Exception:
			frappe.log_error(
				title=f"BPMN ServiceTask: update_field doc load failed ({bpmn_id})",
				message=frappe.get_traceback(),
			)
			return

		updates = {}
		for row in rows:
			if not isinstance(row, dict):
				frappe.logger("one_bpmn").warning(
					f"BPMN update_field: skipping non-dict row {row!r} "
					f"(task={bpmn_id}, instance={self.name})"
				)
				continue
			fieldname = (row.get("field") or "").strip()
			raw_value = row.get("value", "")
			if not fieldname:
				continue
			if "{{" in str(raw_value) or "{%" in str(raw_value):
				try:
					raw_value = frappe.render_template(
						raw_value,
						{"doc": doc, "instance": self, "frappe": frappe},
					)
				except Exception:
					frappe.log_error(
						title=f"BPMN ServiceTask: update_field Jinja render failed ({bpmn_id})",
						message=frappe.get_traceback(),
					)
			updates[fieldname] = raw_value

		if not updates:
			return

		try:
			old_flag = getattr(frappe.flags, "bpmn_engine_action", False)
			frappe.flags.bpmn_engine_action = True
			try:
				frappe.db.set_value(doctype, docname, updates)
			finally:
				frappe.flags.bpmn_engine_action = old_flag

			frappe.logger("one_bpmn").info(
				f"BPMN update_field: {doctype}/{docname} fields={list(updates.keys())} "
				f"(task={bpmn_id}, instance={self.name})"
			)
		except Exception:
			frappe.log_error(
				title=f"BPMN ServiceTask: update_field failed ({bpmn_id})",
				message=frappe.get_traceback(),
			)
			raise

	def _dispatch_google_chat(self, task, task_cfg: dict, bpmn_id: str) -> None:
		"""
		Send a Google Chat message from a Service Task with serviceType='google_chat'.

		Supports two delivery targets:
		    individual — send a direct message to a user by email address
		    space      — post a message to a Google Chat space by space ID

		Configuration keys (from BPMN XML):
		    gchatType    — "individual" or "space"
		    gchatEmail   — recipient email (individual mode)
		    gchatSpaceId — space ID e.g. "spaces/XXXXXXX" (space mode)
		    gchatMessage — message body; Jinja2 supported

		Credentials: the site must have a Google service account JSON key stored in
		site_config.json under "google_chat_service_account_json" (the full JSON content
		as a string or dict).  The service account must have the Google Chat API scope
		https://www.googleapis.com/auth/chat.bot and be a member of the target space.

		Failures are non-fatal: the workflow continues and the error is logged.
		"""
		gchat_type = task_cfg.get("gchatType", "").strip()
		gchat_email = (task_cfg.get("gchatEmail") or "").strip()
		gchat_space_id = (task_cfg.get("gchatSpaceId") or "").strip()
		raw_message = (task_cfg.get("gchatMessage") or "").strip()

		# Validate gchatType is one of the supported values
		if gchat_type not in ("individual", "space"):
			frappe.log_error(
				title=f"BPMN ServiceTask: google_chat misconfigured ({bpmn_id})",
				message=(
					f"gchatType={gchat_type!r} is not a valid destination type. "
					f"Expected 'individual' or 'space'."
				),
			)
			return

		if not raw_message:
			frappe.log_error(
				title=f"BPMN ServiceTask: google_chat misconfigured ({bpmn_id})",
				message="gchatMessage is empty.",
			)
			return

		if gchat_type == "individual" and not gchat_email:
			frappe.log_error(
				title=f"BPMN ServiceTask: google_chat misconfigured ({bpmn_id})",
				message="gchatType=individual but gchatEmail is empty.",
			)
			return

		if gchat_type == "space" and not gchat_space_id:
			frappe.log_error(
				title=f"BPMN ServiceTask: google_chat misconfigured ({bpmn_id})",
				message="gchatType=space but gchatSpaceId is empty.",
			)
			return

		# Render Jinja2 in the message body
		if "{{" in raw_message or "{%" in raw_message:
			try:
				doc = (
					frappe.get_doc(self.context_doctype, self.context_docname)
					if (self.context_doctype and self.context_docname)
					else frappe._dict()
				)
				raw_message = frappe.render_template(
					raw_message,
					{"doc": doc, "instance": self, "frappe": frappe},
				)
			except Exception:
				frappe.log_error(
					title=f"BPMN ServiceTask: google_chat Jinja render failed ({bpmn_id})",
					message=frappe.get_traceback(),
				)

		# Load service account credentials from site config
		sa_json = frappe.conf.get("google_chat_service_account_json")
		if not sa_json:
			frappe.log_error(
				title=f"BPMN ServiceTask: google_chat credentials missing ({bpmn_id})",
				message="'google_chat_service_account_json' not found in site_config.json.",
			)
			return

		try:
			import json as _json
			import requests
			from google.oauth2 import service_account
			from google.auth.transport.requests import Request as GoogleRequest

			SCOPES = ["https://www.googleapis.com/auth/chat.bot"]
			sa_info = sa_json if isinstance(sa_json, dict) else _json.loads(sa_json)
			credentials = service_account.Credentials.from_service_account_info(sa_info, scopes=SCOPES)
			credentials.refresh(GoogleRequest())
			access_token = credentials.token

			headers = {
				"Authorization": f"Bearer {access_token}",
				"Content-Type": "application/json",
			}
			payload = {"text": raw_message}

			if gchat_type == "individual":
				# Create or find a DM space with the user, then post
				dm_url = "https://chat.googleapis.com/v1/spaces:findDirectMessage"
				params = {"name": f"users/{gchat_email}"}
				dm_resp = requests.get(dm_url, headers=headers, params=params, timeout=10)
				if dm_resp.status_code == 200:
					space_name = dm_resp.json().get("name", "")
				else:
					# Fall back to setup DM space
					setup_resp = requests.post(
						"https://chat.googleapis.com/v1/spaces:setup",
						headers=headers,
						json={
							"space": {"spaceType": "DIRECT_MESSAGE"},
							"memberships": [{"member": {"name": f"users/{gchat_email}", "type": "HUMAN"}}],
						},
						timeout=10,
					)
					setup_resp.raise_for_status()
					space_name = setup_resp.json().get("name", "")

				msg_url = f"https://chat.googleapis.com/v1/{space_name}/messages"
			else:
				space_name = gchat_space_id.strip().rstrip("/")
				msg_url = f"https://chat.googleapis.com/v1/{space_name}/messages"

			resp = requests.post(msg_url, headers=headers, json=payload, timeout=10)
			resp.raise_for_status()

			frappe.logger("one_bpmn").info(
				f"BPMN google_chat: message sent to {gchat_type}={gchat_email or gchat_space_id} "
				f"(task={bpmn_id}, instance={self.name})"
			)

		except Exception:
			frappe.log_error(
				title=f"BPMN ServiceTask: google_chat API call failed ({bpmn_id})",
				message=frappe.get_traceback(),
			)

	def _dispatch_push_notification(self, task, task_cfg: dict, bpmn_id: str) -> None:
		"""
		Send push notifications from a Service Task with serviceType='push_notification'.

		Recipient resolution (union of all three sources):
		  - pushToUsers      : comma-separated Frappe User IDs (email)
		  - pushToDocFields  : field names on the context doc that hold User IDs
		  - pushToRoles      : roles — all users holding those roles receive the push

		Title and Message support Jinja2 via frappe.render_template():
		  {{ doc.field_name }}    — context document fields
		  {{ instance.name }}     — BPMN instance name

		Uses one_fm.utils.send_push_notification() which sends via Firebase Cloud
		Messaging.  Falls back gracefully if one_fm is not installed.

		Failures are non-fatal: the workflow continues and the error is logged.
		"""

		# ── Resolve the template context document ─────────────────────────
		doc = frappe._dict()
		if self.context_doctype and self.context_docname:
			try:
				doc = frappe.get_doc(self.context_doctype, self.context_docname)
			except Exception:
				pass

		# ── Jinja helper ──────────────────────────────────────────────────
		jinja_ctx = {
			"doc": doc,
			"instance": self,
			"frappe": frappe,
		}

		def render(text):
			if not text:
				return ""
			try:
				return frappe.render_template(text, jinja_ctx)
			except Exception:
				return text  # return raw on template error

		# ── Build recipient user list ─────────────────────────────────────
		recipient_users = []

		# 1. Direct user IDs (comma-separated Frappe User emails)
		raw_users = task_cfg.get("pushToUsers", "")
		if raw_users:
			recipient_users += [u.strip() for u in raw_users.split(",") if u.strip()]

		# 2. Document field values (fields on doc that hold User IDs)
		raw_fields = task_cfg.get("pushToDocFields", "")
		if raw_fields and doc:
			for field_name in raw_fields.split(","):
				field_name = field_name.strip()
				if not field_name:
					continue
				val = doc.get(field_name, "")
				if val:
					recipient_users.append(str(val).strip())

		# 3. Role members — fetch all users with the configured roles
		raw_roles = task_cfg.get("pushToRoles", "")
		if raw_roles:
			for role_name in raw_roles.split(","):
				role_name = role_name.strip()
				if not role_name:
					continue
				user_roles = frappe.get_all(
					"Has Role",
					filters={"role": role_name, "parenttype": "User"},
					fields=["parent"],
				)
				for ur in user_roles:
					if ur.parent:
						recipient_users.append(ur.parent)

		# De-duplicate preserving order
		seen = set()
		recipient_users = [u for u in recipient_users if u not in seen and not seen.add(u)]

		if not recipient_users:
			frappe.log_error(
				title=f"BPMN push_notification: No recipients resolved ({bpmn_id})",
				message=(
					f"Service Task {task_cfg} on instance {self.name} produced "
					f"no recipient users. Push notification will not be sent."
				),
			)
			return

		# ── Resolve User → Employee mapping ───────────────────────────────
		# one_fm's send_push_notification requires an Employee ID, not a User email.
		employee_map = {}
		for user_id in recipient_users:
			emp_id = frappe.db.get_value("Employee", {"user_id": user_id, "status": "Active"}, "name")
			if emp_id:
				employee_map[user_id] = emp_id
			else:
				frappe.logger("one_bpmn").warning(
					f"BPMN push_notification: no active Employee found for user "
					f"{user_id!r} — skipping (task={bpmn_id}, instance={self.name})"
				)

		if not employee_map:
			frappe.log_error(
				title=f"BPMN push_notification: No employees resolved ({bpmn_id})",
				message=(
					f"None of the {len(recipient_users)} recipient users have "
					f"linked active Employee records. Push notification will not be sent."
				),
			)
			return

		# ── Render title + message ────────────────────────────────────────
		title = render(task_cfg.get("pushTitle", "")) or f"Notification from {self.name}"
		message = render(task_cfg.get("pushMessage", "")) or title

		# ── Import push notification sender ───────────────────────────────
		try:
			from one_fm.utils import send_push_notification
		except ImportError:
			frappe.log_error(
				title=f"BPMN push_notification: one_fm not installed ({bpmn_id})",
				message=(
					"Cannot send push notifications — one_fm app is not installed. "
					"The send_push_notification function is required."
				),
			)
			return

		# ── Send to each employee ─────────────────────────────────────────
		sent_count = 0
		for user_id, emp_id in employee_map.items():
			try:
				send_push_notification(emp_id, title, message)
				sent_count += 1
			except Exception:
				frappe.log_error(
					title=f"BPMN push_notification: send failed for {emp_id} ({bpmn_id})",
					message=frappe.get_traceback(),
				)

		frappe.logger("one_bpmn").info(
			f"BPMN push_notification: sent {sent_count}/{len(employee_map)} "
			f"notifications (task={bpmn_id}, instance={self.name})"
		)

	def _dispatch_email_notification(self, task, task_cfg: dict) -> None:
		"""
		Send an email notification from a Service Task with serviceType='send_email'.

		Recipient resolution (union of all three sources):
		  - emailTo          : direct comma-separated email addresses
		  - emailToDocFields : field names on the context doc that hold email addresses
		  - emailToRoles     : roles — all users holding those roles receive the email

		Subject and Body support Jinja2 via frappe.render_template():
		  {{ doc.field_name }}    — context document fields
		  {{ instance.name }}     — BPMN instance name
		  {{ frappe.session }}    — session info

		If emailUseDoctype is true AND emailDoctype is set, an alternate doc
		is loaded from that doctype (using context_docname) for the template
		context.  Defaults to the main context document.
		"""
		import frappe.utils.jinja as jinja_utils

		# ── Resolve the template context document ─────────────────────────
		ctx_doctype = task_cfg.get("emailDoctype") or self.context_doctype
		ctx_docname = self.context_docname
		use_doctype = task_cfg.get("emailUseDoctype", "") == "true"

		doc = frappe._dict()
		if ctx_doctype and ctx_docname:
			try:
				doc = frappe.get_doc(ctx_doctype, ctx_docname)
			except Exception:
				pass

		# ── Jinja helper ──────────────────────────────────────────────────
		jinja_ctx = {
			"doc": doc,
			"instance": self,
			"frappe": frappe,
		}

		def render(text):
			if not text:
				return ""
			try:
				return frappe.render_template(text, jinja_ctx)
			except Exception:
				return text  # return raw on template error

		# ── Build recipient list ──────────────────────────────────────────
		recipients = []

		# 1. Direct email addresses
		raw_to = task_cfg.get("emailTo", "")
		if raw_to:
			recipients += [e.strip() for e in raw_to.split(",") if e.strip()]

		# 2. Document field values (fields on doc that contain email addresses)
		raw_fields = task_cfg.get("emailToDocFields", "")
		if raw_fields and doc:
			for field_name in raw_fields.split(","):
				field_name = field_name.strip()
				if not field_name:
					continue
				val = doc.get(field_name, "")
				if val and "@" in str(val):
					recipients.append(str(val).strip())

		# 3. Role members — fetch all users with the configured roles
		raw_roles = task_cfg.get("emailToRoles", "")
		if raw_roles:
			for role_name in raw_roles.split(","):
				role_name = role_name.strip()
				if not role_name:
					continue
				user_roles = frappe.get_all(
					"Has Role",
					filters={"role": role_name, "parenttype": "User"},
					fields=["parent"],
				)
				for ur in user_roles:
					user_email = frappe.db.get_value("User", ur.parent, "email")
					if user_email and "@" in user_email:
						recipients.append(user_email)

		# De-duplicate preserving order
		seen = set()
		recipients = [r for r in recipients if r not in seen and not seen.add(r)]

		if not recipients:
			frappe.log_error(
				title="BPMN send_email: No recipients resolved",
				message=(
					f"Service Task {task_cfg} on instance {self.name} produced "
					f"no recipient email addresses. Email will not be sent."
				),
			)
			return

		# ── Render subject + body ─────────────────────────────────────────
		subject = render(task_cfg.get("emailSubject", "") or f"Notification from {self.name}")
		body = render(task_cfg.get("emailBody", "") or subject)
		cc = task_cfg.get("emailCc", "") or None

		# ── Send via one_fm.processor.sendemail if available ─────────
		# Uses the same branded template and notification preference
		# checks as the rest of the one_fm app (checks if user has
		# notifications enabled, email notifications enabled, and
		# preferred company email).
		# Falls back to frappe.sendmail if one_fm isn't installed.
		try:
			from one_fm.processor import sendemail as onefm_sendemail

			onefm_sendemail(
				recipients=recipients,
				subject=subject,
				header=[subject],
				message=body,
				cc=cc,
				reference_doctype=self.context_doctype or self.doctype,
				reference_name=self.context_docname or self.name,
			)
		except ImportError:
			frappe.logger("one_bpmn").warning(
				"one_fm.processor not available — falling back to frappe.sendmail"
			)
			frappe.sendmail(
				recipients=recipients,
				subject=subject,
				message=body,
				cc=cc.split(",") if cc else [],
				reference_doctype=self.context_doctype or self.doctype,
				reference_name=self.context_docname or self.name,
				now=False,
			)

	def _sync_active_tasks(self, wf):
		"""
		Rebuild the active_tasks child table to reflect the current
		set of READY User Tasks in the workflow.

		- Keeps rows that are already Completed (for audit visibility)
		- Adds new rows for newly READY user tasks
		- Removes rows for tasks that are no longer READY
		"""
		ready_user_tasks = bpmn_engine.get_ready_user_tasks(wf)
		new_ready_ids = {str(t.id) for t in ready_user_tasks}

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
			async_user = self._resolve_assignment(task)
			if async_user:
				assigned_user = async_user

			# Resolve task actions (action buttons) from user_task_extensions --
			bpmn_id_key = getattr(task.task_spec, "bpmn_id", None) or ""
			task_cfg = getattr(self, "_user_task_extensions", {}).get(bpmn_id_key, {})
			task_actions = task_cfg.get("taskActions", "")
			task_action_mode = task_cfg.get("taskActionMode", "manual")

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
					"task_action_mode": task_action_mode,
				},
			)

			self._log_task(
				task_id=tid,
				task_name=task_name,
				action="Started",
			)

	def _resolve_assignment(self, task) -> str:
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

		Returns the resolved user email/name, or empty string if unresolvable.
		"""
		extensions = getattr(self, "_user_task_extensions", {})
		bpmn_id = getattr(task.task_spec, "bpmn_id", None) or ""
		task_cfg = extensions.get(bpmn_id, {})

		mode = task_cfg.get("assigneeMode", "")

		# ── User ──────────────────────────────────────────────────────────────
		if mode == "User":
			return task_cfg.get("assigneeUser", "")

		# ── DocField ──────────────────────────────────────────────────────────
		if mode == "DocField":
			doctype = task_cfg.get("targetDoctype") or self.context_doctype
			docfield = task_cfg.get("assigneeDocfield", "")
			if doctype and docfield and self.context_docname:
				try:
					user = frappe.db.get_value(doctype, self.context_docname, docfield)
					return user or ""
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
				model = frappe.get_doc("BPMN Process Model", self.process_model)
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
					from one_bpmn.api import _update_round_robin_in_model

					_update_round_robin_in_model(self.process_model, bpmn_id, assignee)
				except Exception:
					pass

				return assignee
			except Exception:
				frappe.log_error(
					title="BPMN: Round Robin assignment failed",
					message=frappe.get_traceback(),
				)
				return users[0] if users else ""

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
				return assignee

			except Exception:
				frappe.log_error(
					title="BPMN: Load Balancing assignment failed",
					message=frappe.get_traceback(),
				)
				return users[0] if users else ""

		return ""

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
				log.data = json.dumps(data, default=str)
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
