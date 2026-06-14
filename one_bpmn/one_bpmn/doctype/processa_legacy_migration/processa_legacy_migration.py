# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from SpiffWorkflow.util.task import TaskState
from SpiffWorkflow.bpmn.script_engine import TaskDataEnvironment

from one_bpmn.one_bpmn import engine as bpmn_engine
from one_bpmn.one_bpmn.engine import FrappeScriptEngine, get_serializer


class MigrationScriptEngine(FrappeScriptEngine):
	"""
	A lenient script engine for migration fast-forward.

	Suppresses all exceptions from script task execution so that
	validation scripts (e.g. "Validate PR Reviewer") don't abort
	the migration. Gateway routing still works because gateways
	evaluate BEFORE script tasks on error branches.
	"""

	def execute(self, task, script, **kwargs):
		try:
			super().execute(task, script, **kwargs)
		except Exception:
			frappe.log_error(
				title="Legacy Migration: script task execution failed",
				message=frappe.get_traceback(with_context=False),
			)


class ProcessaLegacyMigration(Document):
	"""
	Utility to migrate legacy Frappe documents into Processa BPMN workflows.

	Creates real BPMN Process Instances by fast-forwarding the SpiffWorkflow
	engine to the target state position, producing valid serialized workflow
	state that is fully actionable from Processa.
	"""

	def validate(self):
		if self.status not in ("Draft", ""):
			return

		if not self.process_model:
			frappe.throw(_("Process Model is required."))
		if not self.target_doctype:
			frappe.throw(_("Target DocType is required."))
		if not self.old_status:
			frappe.throw(_("Old Status is required."))
		if not self.target_status:
			frappe.throw(_("Target Status is required."))

		if self.old_status == self.target_status:
			frappe.throw(_("Old Status and Target Status cannot be the same."))

	def run_migration(self):
		"""
		Core migration method — iterates over matching documents and
		transitions each one. Designed to run in a background job.

		For each document:
		  1. Updates workflow_state / status to the target value
		  2. Optionally creates a BPMN Process Instance (fast-forwarded)
		  3. Logs any per-row failures to the error_logs child table

		Commits in batches of 50 to avoid long transactions.
		"""
		self.db_set({
			"status": "Running",
			"started_at": now_datetime(),
			"run_by": frappe.session.user,
			"migrated_count": 0,
			"failed_count": 0,
		})
		frappe.db.commit()

		state_field = self._get_state_field()
		if not state_field:
			self._mark_failed(
				_("DocType '{0}' has neither 'workflow_state' nor 'status' field.").format(
					self.target_doctype
				)
			)
			return

		# Fetch all matching document names
		doc_names = frappe.get_all(
			self.target_doctype,
			filters={state_field: self.old_status},
			pluck="name",
			ignore_permissions=True,
		)

		self.db_set("total_records", len(doc_names))
		frappe.db.commit()

		if not doc_names:
			self.db_set({
				"status": "Completed",
				"completed_at": now_datetime(),
			})
			frappe.db.commit()
			return

		migrated = 0
		failed = 0
		batch_size = 50

		for idx, doc_name in enumerate(doc_names):
			try:
				self._migrate_single_record(doc_name, state_field)
				migrated += 1
			except Exception:
				failed += 1
				error_tb = frappe.get_traceback(with_context=False)
				# Rollback the failed record's partial changes FIRST
				frappe.db.rollback()
				# THEN log the error (after rollback so it isn't wiped)
				self._log_row_error(doc_name, error_tb)
				frappe.db.commit()

			# Batch commit + progress update
			if (idx + 1) % batch_size == 0:
				self.db_set({
					"migrated_count": migrated,
					"failed_count": failed,
				})
				frappe.db.commit()
				frappe.publish_realtime(
					"legacy_migration_progress",
					{
						"migration_name": self.name,
						"migrated": migrated,
						"failed": failed,
						"total": len(doc_names),
					},
					user=self.run_by,
					after_commit=True,
				)

		# Final status
		final_status = "Completed" if migrated > 0 else "Failed"
		self.db_set({
			"status": final_status,
			"completed_at": now_datetime(),
			"migrated_count": migrated,
			"failed_count": failed,
		})
		frappe.db.commit()

		frappe.publish_realtime(
			"legacy_migration_progress",
			{
				"migration_name": self.name,
				"migrated": migrated,
				"failed": failed,
				"total": len(doc_names),
				"completed": True,
			},
			user=self.run_by,
			after_commit=True,
		)

	def _migrate_single_record(self, doc_name: str, state_field: str):
		"""
		Migrate a single document record:
		  1. Update the document's state field
		  2. Optionally create a BPMN Process Instance
		"""
		# ── 1. Update document state ──────────────────────────────────────
		# Set bpmn_engine_action flag to bypass the BPMN guard that blocks
		# direct state changes on BPMN-controlled documents.
		frappe.flags.bpmn_engine_action = True
		try:
			doc = frappe.get_doc(self.target_doctype, doc_name)
			doc.set(state_field, self.target_status)
			doc.save(ignore_permissions=True)
		finally:
			frappe.flags.bpmn_engine_action = False

		# ── 2. Create BPMN Process Instance ───────────────────────────────
		if self.create_process_instance:
			# Skip if an active instance already exists for this document
			existing = frappe.db.exists(
				"BPMN Process Instance",
				{
					"process_model": self.process_model,
					"context_doctype": self.target_doctype,
					"context_docname": doc_name,
					"status": "Active",
				},
			)
			if not existing:
				self._create_fast_forwarded_instance(doc)

		frappe.db.commit()

	def _create_fast_forwarded_instance(self, doc):
		"""
		Create a real BPMN Process Instance by fast-forwarding the
		SpiffWorkflow engine to the target state position.

		Algorithm:
		  1. Create a BpmnWorkflow from the model's serialized spec
		  2. Inject document field values as initial workflow data
		  3. Run the engine in a loop:
		     a. do_engine_steps() — runs gateways, script tasks
		     b. Complete STARTED service tasks WITHOUT dispatching real actions
		     c. Check if the target service task has been completed
		     d. If yes → STOP (workflow is at the next user task)
		     e. If no → auto-complete READY user tasks with doc data, loop
		  4. Serialize the workflow state and create the instance record
		"""
		model = frappe.get_doc("BPMN Process Model", self.process_model)
		if not model.serialized_spec:
			frappe.throw(
				_("Process model '{0}' has no compiled spec.").format(self.process_model)
			)

		spec = self._load_json(model.serialized_spec)
		service_exts = spec.get("service_task_extensions", {})
		user_exts = spec.get("user_task_extensions", {})
		script_exts = spec.get("script_task_extensions", {})

		# Build initial data from document fields
		data = {
			"context_doctype": self.target_doctype,
			"context_docname": doc.name,
		}
		for field in doc.meta.fields:
			val = doc.get(field.fieldname)
			if isinstance(val, (str, int, float, bool)) or val is None:
				data[field.fieldname] = val
		data["docstatus"] = int(doc.docstatus or 0)

		# Create workflow with migration-safe script engine
		from datetime import datetime as _dt

		_frappe = frappe
		extra = {"datetime": _dt, "frappe": _frappe, "doc": doc}
		env = TaskDataEnvironment(extra)
		migration_engine = MigrationScriptEngine(
			env,
			script_task_extensions=script_exts,
			context_doctype=self.target_doctype,
			context_docname=doc.name,
			initiated_by=frappe.session.user,
		)

		serializer = get_serializer()
		json_str = json.dumps(spec)
		wf = serializer.deserialize_json(json_str)
		wf.script_engine = migration_engine

		if data:
			wf.task_tree.data.update(data)

		# ── Fast-forward loop ─────────────────────────────────────────────
		target_reached = False
		completed_bpmn_ids = set()
		user_task_completions = {}  # bpmn_id → count (loop detection)
		activity_log_entries = []
		max_iterations = 100

		for _iter in range(max_iterations):
			wf.refresh_waiting_tasks()
			wf.do_engine_steps()

			# Complete STARTED non-manual tasks (service tasks) without dispatch
			started = [
				t for t in wf.get_tasks(state=TaskState.STARTED)
				if not getattr(t.task_spec, "manual", False)
			]

			for task in started:
				bpmn_id = getattr(task.task_spec, "bpmn_id", None) or ""
				task_cfg = service_exts.get(bpmn_id, {})

				# Record for activity log
				activity_log_entries.append({
					"task_id": str(task.id),
					"task_name": bpmn_engine.get_task_display_name(task),
					"action": "Completed",
				})
				completed_bpmn_ids.add(bpmn_id)

				# Check if this service task applies our target state
				if task_cfg.get("workflowState") == self.target_status:
					target_reached = True

				# Use target_task_id for exact matching if provided
				if self.target_task_id and bpmn_id == self.target_task_id:
					target_reached = True

				task.complete()

			if target_reached:
				# Run one more engine pass to advance past the target
				# service task and reach the next user task
				wf.refresh_waiting_tasks()
				wf.do_engine_steps()

				# Complete any remaining STARTED service tasks after target
				for t in wf.get_tasks(state=TaskState.STARTED):
					if not getattr(t.task_spec, "manual", False):
						bid = getattr(t.task_spec, "bpmn_id", None) or ""
						activity_log_entries.append({
							"task_id": str(t.id),
							"task_name": bpmn_engine.get_task_display_name(t),
							"action": "Completed",
						})
						t.complete()

				wf.refresh_waiting_tasks()
				wf.do_engine_steps()
				break

			# No service tasks were started — check for user tasks
			if not started:
				ready = bpmn_engine.get_ready_user_tasks(wf)
				if not ready:
					break  # Workflow completed or stuck

				# Auto-complete user tasks with document data to advance
				for task in ready:
					bpmn_id = getattr(task.task_spec, "bpmn_id", None) or ""
					count = user_task_completions.get(bpmn_id, 0)
					if count >= 3:
						frappe.throw(
							_(
								"Cannot advance workflow past task '{0}' — "
								"required data may be missing on document '{1}'."
							).format(
								bpmn_engine.get_task_display_name(task),
								doc.name,
							)
						)

					user_task_completions[bpmn_id] = count + 1

					# Inject doc data + first action
					task.data.update(data)
					ut_cfg = user_exts.get(bpmn_id, {})
					actions_raw = ut_cfg.get("taskActions", "")
					first_action = self._extract_first_action(actions_raw)
					if first_action:
						task.data["action"] = first_action

					activity_log_entries.append({
						"task_id": str(task.id),
						"task_name": bpmn_engine.get_task_display_name(task),
						"action": "Completed",
					})

					task.run()

		if not target_reached:
			frappe.throw(
				_(
					"Could not reach target state '{0}' in process model '{1}' "
					"for document '{2}'. The document data may not satisfy the "
					"workflow gateway conditions."
				).format(self.target_status, self.process_model, doc.name)
			)

		# ── Create the BPMN Process Instance ──────────────────────────────
		bpmn_engine.clean_doc_from_wf_data(wf)
		workflow_state = json.dumps(bpmn_engine.serialize_workflow(wf))

		instance = frappe.new_doc("BPMN Process Instance")
		instance.process_model = self.process_model
		instance.context_doctype = self.target_doctype
		instance.context_docname = doc.name
		instance.status = "Active"
		instance.initiated_by = frappe.session.user
		instance.started_at = now_datetime()
		instance.serialized_spec = model.serialized_spec
		instance.workflow_state = workflow_state

		# Populate active_tasks from the workflow's current READY user tasks
		ready_tasks = bpmn_engine.get_ready_user_tasks(wf)
		for task in ready_tasks:
			bpmn_id = getattr(task.task_spec, "bpmn_id", None) or ""
			ut_cfg = user_exts.get(bpmn_id, {})

			# Resolve assigned user from task data
			assigned_user = task.data.get("assigned_user") or ""
			assigned_role = task.data.get("assigned_role") or ""

			instance.append("active_tasks", {
				"task_id": str(task.id),
				"task_name": bpmn_engine.get_task_display_name(task),
				"task_type": bpmn_engine.get_task_type_label(task),
				"status": "Waiting",
				"started_at": now_datetime(),
				"assigned_user": assigned_user,
				"assigned_role": assigned_role,
				"task_actions": ut_cfg.get("taskActions", ""),
				"target_doctype": self.target_doctype,
				"target_docname": doc.name,
			})

		# Check if workflow completed immediately
		if wf.is_completed():
			instance.status = "Completed"
			instance.completed_at = now_datetime()

		instance.insert(ignore_permissions=True)

		# ── Create BPMN Activity Log entries ──────────────────────────────
		for entry in activity_log_entries:
			try:
				log = frappe.new_doc("BPMN Activity Log")
				log.instance = instance.name
				log.task_id = entry["task_id"]
				log.task_name = entry["task_name"]
				log.action = entry["action"]
				log.timestamp = now_datetime()
				log.user = frappe.session.user
				log.data = json.dumps({"migrated": True, "migration": self.name})
				log.insert(ignore_permissions=True)
			except Exception:
				frappe.log_error(
					title="Legacy Migration: Activity Log write failed",
					message=frappe.get_traceback(),
				)

		# Log the "Started" entries for currently waiting tasks
		for task in ready_tasks:
			try:
				log = frappe.new_doc("BPMN Activity Log")
				log.instance = instance.name
				log.task_id = str(task.id)
				log.task_name = bpmn_engine.get_task_display_name(task)
				log.action = "Started"
				log.timestamp = now_datetime()
				log.user = frappe.session.user
				log.data = json.dumps({"migrated": True, "migration": self.name})
				log.insert(ignore_permissions=True)
			except Exception:
				pass

	def _get_state_field(self) -> str:
		"""
		Determine which field holds the workflow state on the target DocType.
		Returns 'workflow_state', 'status', or empty string.
		"""
		meta = frappe.get_meta(self.target_doctype)
		if meta.has_field("workflow_state"):
			return "workflow_state"
		if meta.has_field("status"):
			return "status"
		return ""

	def _log_row_error(self, doc_name: str, error_message: str):
		"""Append a row to the error_logs child table for a single failed record."""
		try:
			frappe.get_doc({
				"doctype": "Legacy Migration Error Log",
				"parent": self.name,
				"parenttype": "Processa Legacy Migration",
				"parentfield": "error_logs",
				"document_doctype": self.target_doctype,
				"document_name": doc_name,
				"error_message": (error_message or "")[:65535],
				"timestamp": now_datetime(),
			}).db_insert()
		except Exception:
			frappe.log_error(
				title=f"Legacy Migration: error log insert failed for {doc_name}",
				message=frappe.get_traceback(),
			)

	def _mark_failed(self, message: str):
		"""Mark the migration as Failed with a top-level error."""
		self.db_set({
			"status": "Failed",
			"completed_at": now_datetime(),
		})
		frappe.db.commit()
		frappe.log_error(
			title=f"Legacy Migration {self.name} failed",
			message=message,
		)

	@staticmethod
	def _extract_first_action(actions_raw: str) -> str:
		"""
		Extract the first action label from a task_actions string.
		Handles both JSON array and legacy CSV formats.
		"""
		if not actions_raw:
			return ""
		trimmed = actions_raw.strip()
		if trimmed.startswith("["):
			try:
				parsed = json.loads(trimmed)
				if isinstance(parsed, list) and parsed:
					return parsed[0].get("action", "")
			except (TypeError, ValueError):
				pass
		# Legacy CSV
		parts = [a.strip() for a in trimmed.split(",") if a.strip()]
		return parts[0] if parts else ""

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


# ─────────────────────────────────────────────────────────────────────────────
# Whitelisted API methods
# ─────────────────────────────────────────────────────────────────────────────


@frappe.whitelist()
def enqueue_migration(migration_name: str) -> dict:
	"""
	Enqueue a legacy migration to run in the background.

	Args:
	    migration_name: Name of the Processa Legacy Migration document

	Returns:
	    dict with status
	"""
	frappe.only_for("System Manager")

	if not frappe.db.exists("Processa Legacy Migration", migration_name):
		frappe.throw(_("Migration '{0}' not found.").format(migration_name))

	doc = frappe.get_doc("Processa Legacy Migration", migration_name)
	if doc.status not in ("Draft", "Failed"):
		frappe.throw(
			_("Migration can only be run from Draft or Failed status. Current: {0}").format(
				doc.status
			)
		)

	# Reset counts for re-run
	doc.db_set({
		"migrated_count": 0,
		"failed_count": 0,
		"total_records": 0,
		"started_at": None,
		"completed_at": None,
	})

	# Clear previous error logs on re-run
	frappe.db.delete("Legacy Migration Error Log", {"parent": migration_name})
	frappe.db.commit()

	# Count matching records to decide sync vs async
	state_field = doc._get_state_field()
	record_count = 0
	if state_field:
		record_count = frappe.db.count(doc.target_doctype, {state_field: doc.old_status})

	ASYNC_THRESHOLD = 25

	if record_count > ASYNC_THRESHOLD:
		doc.db_set("status", "Queued")
		frappe.db.commit()

		frappe.enqueue(
			method="one_bpmn.one_bpmn.doctype.processa_legacy_migration.processa_legacy_migration._run_migration_job",
			queue="long",
			timeout=3600,
			migration_name=migration_name,
			user=frappe.session.user,
		)

		return {
			"status": "Queued",
			"message": _("{0} records found. Migration has been queued for background execution.").format(
				record_count
			),
		}
	else:
		# Run synchronously for small batches
		doc.run_migration()
		doc.reload()

		return {
			"status": doc.status,
			"message": _("Migration completed. Migrated: {0}, Failed: {1}").format(
				doc.migrated_count, doc.failed_count
			),
		}


@frappe.whitelist()
def preview_migration(target_doctype: str, old_status: str) -> dict:
	"""
	Preview the number of records that would be affected by the migration.

	Args:
	    target_doctype: The DocType to migrate
	    old_status:     The current status to filter by

	Returns:
	    dict with count and sample document names
	"""
	frappe.only_for("System Manager")

	if not target_doctype or not old_status:
		frappe.throw(_("target_doctype and old_status are required."))

	meta = frappe.get_meta(target_doctype)
	state_field = ""
	if meta.has_field("workflow_state"):
		state_field = "workflow_state"
	elif meta.has_field("status"):
		state_field = "status"
	else:
		return {"count": 0, "samples": [], "error": _("DocType has no workflow_state or status field.")}

	count = frappe.db.count(target_doctype, {state_field: old_status})
	samples = frappe.get_all(
		target_doctype,
		filters={state_field: old_status},
		pluck="name",
		limit=10,
		ignore_permissions=True,
	)

	return {
		"count": count,
		"samples": samples,
		"state_field": state_field,
	}


@frappe.whitelist()
def get_bpmn_service_tasks(process_model: str) -> list:
	"""
	Extract service tasks with apply_workflow type from a BPMN Process Model.

	Returns a list of dicts with id, name, and workflowState for each
	service task that sets a workflow state.
	"""
	frappe.only_for("System Manager")

	if not process_model:
		return []

	model = frappe.get_doc("BPMN Process Model", process_model)
	if not model.serialized_spec:
		return []

	spec = model.serialized_spec
	if isinstance(spec, str):
		try:
			spec = json.loads(spec)
		except (TypeError, ValueError):
			return []

	service_exts = spec.get("service_task_extensions", {})
	result = []

	for bpmn_id, cfg in service_exts.items():
		if cfg.get("serviceType") == "apply_workflow" and cfg.get("workflowState"):
			result.append({
				"id": bpmn_id,
				"name": cfg.get("taskName", bpmn_id),
				"workflow_state": cfg.get("workflowState"),
			})

	return sorted(result, key=lambda x: x.get("name", ""))


def _run_migration_job(migration_name: str, user: str = None):
	"""
	Background job wrapper for run_migration().
	Sets the session user so permission checks work correctly.
	"""
	if user:
		frappe.set_user(user)

	try:
		doc = frappe.get_doc("Processa Legacy Migration", migration_name)
		doc.run_migration()
	except Exception:
		frappe.db.rollback()
		frappe.db.set_value("Processa Legacy Migration", migration_name, {
			"status": "Failed",
			"completed_at": now_datetime(),
		})
		frappe.db.commit()
		frappe.log_error(
			title=f"Legacy Migration {migration_name} crashed",
			message=frappe.get_traceback(),
		)
