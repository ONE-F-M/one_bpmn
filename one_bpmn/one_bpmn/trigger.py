# Copyright (c) 2026, one-fm and contributors
# Universal BPMN trigger — fires for every Frappe document event.
#
# Wired up in hooks.py as:
#   doc_events = { "*": { "after_insert": "one_bpmn.one_bpmn.trigger.on_doc_event", ... } }
#
# For each event, this handler:
#   1. Skips internal/system doctypes to prevent recursion
#   2. Maps the Frappe hook method name to the trigger_event label stored on the model
#   3. Finds all active BPMN Process Models configured to fire on this doctype + event
#   4. Checks a workflow_state condition embedded in the BPMN XML start event
#   5. Skips models that already have a running instance for this document
#   6. Creates and starts a new BPMN Process Instance for each matching model

import io

import frappe
from frappe.utils import now_datetime

# Doctypes that belong to one_bpmn itself — never trigger workflows on these
# to avoid infinite recursion.
_INTERNAL_DOCTYPES = frozenset(
	{
		"BPMN Process Model",
		"BPMN Process Instance",
		"BPMN Active Task",
		"BPMN Activity Log",
		"BPMN Process DocType",
		"Processa Legacy Migration",
		"Legacy Migration Error Log",
	}
)

# Maps Frappe hook method names  →  the label stored in
# BPMN Process Model.trigger_event (Select field).
_FRAPPE_TO_TRIGGER_EVENT = {
	"after_insert": "After Insert",
	"on_update": "On Update",
	"after_save": "After Save",
	"on_submit": "On Submit",
	"on_cancel": "On Cancel",
	"on_update_after_submit": "On Update After Submit",
	"validate": "Validate",
	"before_save": "Before Save",
	"before_submit": "Before Submit",
	"before_cancel": "Before Cancel",
}

# Maps Frappe document events  →  the BPMN User Task action they represent.
# Used by the bidirectional sync: when a document changes outside of the BPMN
# engine (e.g. user submits the EDA directly from the Frappe form), any active
# process instance waiting for the corresponding User Task action is advanced.
_FRAPPE_EVENT_TO_TASK_ACTION = {
	"on_submit": "Submit",
	"on_cancel": "Cancel"
}

# Generic mapping: Frappe hook event → BPMN message suffix.
# This is NOT specific to any DocType — it applies universally to every
# document that has an active BPMN process.  When a user edits any such
# document, the process needs to know so it can react (e.g. sync changes
# to Google Tasks, send a notification, etc.).
#
# At runtime, _maybe_send_message() combines the DocType name with the
# suffix to build the full BPMN message name.  Examples:
#     ToDo        + on_update  →  "ToDo_Edit_Action"
#     Sales Order + on_update  →  "SalesOrder_Edit_Action"
#     Work Item   + on_update  →  "WorkItem_Edit_Action"
#
# The resulting message must match a <bpmn:message name="..."> defined in
# the corresponding BPMN diagram.  Only processes that have a matching
# IntermediateCatchEvent / EventBasedGateway will react to the message.
_FRAPPE_EVENT_TO_MESSAGE_SUFFIX = {
	"on_update":   "Edit_Action",
	"after_save":  "Edit_Action",
}

# SpiffWorkflow BPMN extension namespace
_SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"
_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"


# Entry point — called by every doc_event hook


def on_doc_event(doc, method: str):
	"""
	Universal handler wired to all Frappe document events via hooks.py.

	Handles two separate concerns:
	  A) Start a new BPMN Process Instance when a matching model is configured
		 to trigger on this doctype + event (e.g. After Insert).
	  B) Advance an existing active BPMN Process Instance when the document
		 changes outside of the BPMN engine — bidirectional sync (e.g. the
		 user submits the EDA directly from the Frappe form).

	Args:
		doc:    The Frappe Document that just changed
		method: The hook method name, e.g. 'after_insert', 'on_update'
	"""
	# 0. Never fire during migrations, installs, or patch execution
	if getattr(frappe.flags, "in_migrate", False) \
	   or getattr(frappe.flags, "in_install", False) \
	   or getattr(frappe.flags, "in_patch", False) \
	   or getattr(frappe.flags, "in_setup_wizard", False):
		return


	# 1. Never trigger on internal BPMN doctypes
	if doc.doctype in _INTERNAL_DOCTYPES:
		return

	# 1b. Skip if no valid session user (background jobs, system events)
	if not getattr(frappe.session, "user", None) or frappe.session.user == "None":
		return

	# 2. Map the Frappe hook name to the trigger_event label
	trigger_event = _FRAPPE_TO_TRIGGER_EVENT.get(method)
	if not trigger_event:
		return  # Event type we don't handle (e.g. autoname, db_insert)

	# ── A) Start new instances ────────────────────────────────────────────────
	models = _find_matching_models(doc.doctype, trigger_event)
	for model_name in models:
		try:
			_maybe_start_instance(doc, model_name)
		except Exception:
			frappe.log_error(
				title=f"BPMN trigger failed for {doc.doctype} / {model_name}",
				message=frappe.get_traceback(),
			)


	# ── B) Advance existing instances (bidirectional sync) ────────────────────
	# If this event maps to a User Task action (Submit → on_submit, etc.),
	# auto-complete any waiting task in an existing active instance.
	task_action = _FRAPPE_EVENT_TO_TASK_ACTION.get(method)
	if task_action:
		_maybe_advance_instances(doc, task_action)


	# ── C) Notify running processes about document changes ────────────────────
	# Sections A and B handle *starting* processes and *advancing* user tasks.
	# This section handles the third case: the document was edited by the user
	# (or by code) and we need to tell the already-running BPMN process about
	# the change.  For example, when a ToDo's status changes from Open → Closed,
	# the process needs that event to decide whether to send a notification or
	# sync the status to Google Tasks.
	#
	# How it works:
	#   1. Look up whether this Frappe event (on_update / after_save) has a
	#      corresponding BPMN message suffix ("Edit_Action").
	#   2. If yes, _maybe_send_message() finds every active BPMN instance
	#      linked to this document and delivers the message.
	#   3. The message unblocks the process's EventBasedGateway, which routes
	#      to the update branch of the BPMN diagram.
	#
	# Dedup: Frappe fires after_insert → on_update → after_save in one request.
	# _maybe_send_message() uses frappe.flags to ensure only one delivery.
	message_suffix = _FRAPPE_EVENT_TO_MESSAGE_SUFFIX.get(method)
	if message_suffix:
		_maybe_send_message(doc, message_suffix)


# Internal helpers


def _maybe_send_message(doc, message_suffix: str):
	"""
	Deliver a BPMN message to active instances when a document is edited.
	Builds message name as {DocType}_{suffix} and never blocks the save.
	"""

	# Skip if the document was just created in this request
	# (the instance is still in its creation flow, not waiting for edits)
	bpmn_created = frappe.flags.get("_bpmn_instances_just_started") or set()
	doc_id = f"{doc.doctype}:{doc.name}"
	if doc_id in bpmn_created:
		return

	# Dedup: only deliver once per doc per request
	# (Frappe fires on_update + after_save back-to-back)
	if not frappe.flags._bpmn_message_sent:
		frappe.flags._bpmn_message_sent = set()

	doc_key = f"{doc.doctype}:{doc.name}:{message_suffix}"
	if doc_key in frappe.flags._bpmn_message_sent:
		return
	frappe.flags._bpmn_message_sent.add(doc_key)

	# Build message name: e.g. "ToDo" + "Edit_Action" → "ToDo_Edit_Action"
	# Must match <bpmn:message name="..."> in the diagram
	doctype_clean = doc.doctype.replace(" ", "")
	message_name = f"{doctype_clean}_{message_suffix}"

	# Find active BPMN instances for this document
	try:
		active_instances = frappe.get_all(
			"BPMN Process Instance",
			filters={
				"context_doctype": doc.doctype,
				"context_docname": doc.name,
				"status": "Active",
			},
			pluck="name",
		)
	except Exception:
		return

	if not active_instances:
		return

	for instance_name in active_instances:
		try:
			instance = frappe.get_doc("BPMN Process Instance", instance_name)

			# Pass _old_status so scripts can detect status transitions
			# (by on_update time, the DB already has the new value)
			prev_doc = getattr(doc, "_doc_before_save", None)
			payload = {
				"triggered_by": frappe.session.user,
				"trigger_event": message_suffix,
			}
			if prev_doc:
				payload["_old_status"] = prev_doc.status

			instance.receive_message(
				message_name=message_name,
				payload=payload,
			)
		except frappe.ValidationError:
			# "No task is waiting for message" — expected when the instance
			# is active but not at a matching catch event. Silently skip.
			pass
		except Exception:
			# Unexpected error — log but never block the document save
			frappe.log_error(
				title=f"BPMN message delivery failed: {message_name} → {instance_name}",
				message=frappe.get_traceback(),
			)


def _find_matching_models(doctype: str, trigger_event: str) -> list:
	"""
	Return names of all active BPMN Process Models whose trigger matches
	the given doctype + event combination.

	Triggers are now primarily defined in the ``BPMN Start Event Config``
	child table, allowing multiple start events per model.
	"""
	# 1. Search BPMN Start Event Config (Source of Truth)
	# This catches models where triggerDoctype/triggerEvent are configured
	# on start events in the BPMN diagram.
	child_matches = frappe.get_all(
		"BPMN Start Event Config",
		filters={
			"trigger_type": "DocType Event",
			"trigger_doctype": doctype,
			"trigger_event": trigger_event,
			"parenttype": "BPMN Process Model",
		},
		fields=["parent"],
	)
	candidate_names = [r.parent for r in child_matches if r.parent]

	# 2. Check BPMN Process DocType (Multi-DocType support)
	# This is a separate child table used for models that apply to a list
	# of doctypes with the same start event logic.
	multi_doc_matches = frappe.get_all(
		"BPMN Process DocType",
		filters={
			"doctype_name": doctype,
			"parenttype": "BPMN Process Model",
		},
		fields=["parent"],
	)
	candidate_names.extend([r.parent for r in multi_doc_matches if r.parent])

	if not candidate_names:
		return []

	# Final filter for active models and deduplication
	active_models = frappe.get_all(
		"BPMN Process Model",
		filters={
			"name": ["in", list(set(candidate_names))],
			"is_active": 1,
		},
		pluck="name",
	)

	return active_models


def _maybe_start_instance(doc, model_name: str):
	"""
	Evaluate conditions for one model against the current document.
	Starts a new BPMN Process Instance only if all checks pass.
	"""
	model = frappe.get_doc("BPMN Process Model", model_name)

	# Must have a compiled spec — silently skip if not yet compiled
	if not model.serialized_spec:
		return

	# The BPMN attribute spiffworkflow:triggerWorkflowState is compared against
	# both doc.workflow_state (Frappe native workflow) and doc.status (custom
	# status fields like Work Item.status) so either convention works.
	required_state = _get_trigger_workflow_state(model.bpmn_xml)
	if required_state:
		doc_state = getattr(doc, "workflow_state", None) or getattr(doc, "status", None)
		if doc_state != required_state:
			return

	# Prevent duplicate: skip if there's already an Active instance
	# for this exact document + model combination
	existing = frappe.db.exists(
		"BPMN Process Instance",
		{
			"process_model": model_name,
			"context_doctype": doc.doctype,
			"context_docname": doc.name,
			"status": "Active",
		},
	)
	if existing:
		return

	# All checks passed — create and start the instance
	instance = frappe.new_doc("BPMN Process Instance")
	instance.process_model = model_name
	instance.context_doctype = doc.doctype
	instance.context_docname = doc.name
	instance.status = "Active"
	instance.initiated_by = frappe.session.user
	instance.started_at = now_datetime()
	instance.insert(ignore_permissions=True)

	# Mark the doc BEFORE start() so Section C doesn't send Edit_Action
	# during creation. start() may execute script tasks that save the doc,
	# triggering nested on_update → Section C. The flag must be set first.
	# Use frappe.flags (request-scoped) — survives across all hook calls.
	if not frappe.flags._bpmn_instances_just_started:
		frappe.flags._bpmn_instances_just_started = set()
	frappe.flags._bpmn_instances_just_started.add(f"{doc.doctype}:{doc.name}")

	# start() runs the engine and saves the instance
	instance.start(
		initial_data={
			"triggered_by": frappe.session.user,
			"trigger_doctype": doc.doctype,
			"trigger_docname": doc.name,
		}
	)



# Bidirectional sync — advance existing instances on doc events


def _maybe_advance_instances(doc, task_action: str):
	"""
	When a document changes outside the BPMN engine (e.g. user submits the EDA
	directly from the Frappe form), find any active BPMN Process Instance for
	that document and auto-complete the waiting User Task whose task_actions
	contains the given action.

	Design notes:
	  - Only advances tasks in READY state (state=16) — never touches completed
		or future tasks.
	  - The advance() call will dispatch the downstream service tasks (e.g.
		"Set to Submitted") which gracefully no-op if the doc is already in
		the target state, preventing recursion and duplicate submissions.
	  - Any failure is logged but never crashes the original document save.
	"""
	try:
		active_instances = frappe.get_all(
			"BPMN Process Instance",
			filters={
				"context_doctype": doc.doctype,
				"context_docname": doc.name,
				"status": "Active",
			},
			pluck="name",
		)
	except Exception:
		return

	for instance_name in active_instances:
		try:
			_advance_instance_on_doc_event(instance_name, task_action)
		except Exception:
			frappe.log_error(
				title=f"BPMN auto-advance failed for instance {instance_name}",
				message=frappe.get_traceback(),
			)


def _advance_instance_on_doc_event(instance_name: str, task_action: str):
	"""
	Load the instance, find the first Waiting User Task that accepts
	task_action, and call advance() to complete it and run the engine forward.

	task_action is a single action string, e.g. "Submit" or "Cancel".
	task_actions on the row is either:
	  - JSON array: [{"action":"Submit"},{"action":"Save"}]
	  - Legacy CSV:  "Submit,Save"
	"""
	instance = frappe.get_doc("BPMN Process Instance", instance_name)

	# find the matching task row
	matching_row = None
	for row in instance.active_tasks:
		if row.status != "Waiting":
			continue
		raw = (row.task_actions or "").strip()
		if raw.startswith("["):
			import json as _json
			try:
				parsed = _json.loads(raw)
				actions = [
					a.get("action", "").strip()
					for a in (parsed if isinstance(parsed, list) else [])
					if isinstance(a, dict) and a.get("action", "").strip()
				]
			except (TypeError, ValueError):
				# Invalid JSON — fall back to legacy CSV parsing rather than
				# silently producing an empty list that can never match.
				frappe.log_error(
					title="BPMN trigger: malformed task_actions JSON",
					message=f"task_actions={raw!r} on instance {instance_name}",
				)
				actions = [a.strip() for a in raw.split(",") if a.strip()]
		else:
			actions = [a.strip() for a in raw.split(",") if a.strip()]
		if task_action in actions:
			matching_row = row
			break

	if not matching_row:
		return  # No waiting task matches — nothing to advance

	# advance() will:
	#  1. Complete the User Task
	#  2. Run the engine forward (service tasks, script tasks, etc.)
	#  3. Save the instance with updated workflow_state
	# Note: downstream service tasks that try to re-submit the doc will
	# gracefully no-op because _apply_docstatus_directly guards against
	# re-submitting an already-submitted document.
	#
	# advance() signature: advance(self, task_id: str, data: dict = None)
	# The action is passed inside data so it matches the API convention.
	instance.advance(task_id=matching_row.task_id, data={"action": task_action})


def _get_trigger_workflow_state(bpmn_xml: str):
	"""
	Parse the BPMN XML and return the value of
	spiffworkflow:triggerWorkflowState on the start event, if set.

	Example BPMN attribute:
		<bpmn:startEvent spiffworkflow:triggerWorkflowState="Open" ...>

	Returns None if no condition is set or if parsing fails.
	"""
	if not bpmn_xml or not bpmn_xml.strip():
		return None
	try:
		from lxml import etree

		root = etree.fromstring(bpmn_xml.strip().encode("utf-8"))
		attr_key = f"{{{_SPIFF_NS}}}triggerWorkflowState"
		for start in root.iter(f"{{{_BPMN_NS}}}startEvent"):
			state = start.get(attr_key)
			if state:
				return state
	except Exception:
		pass
	return None


# BPMN Document Guard


def guard_bpmn_document(doc, method: str):
	"""
	Blocks native Frappe submit / cancel / workflow transitions when a BPMN
	Process Instance is actively controlling this document.

	Wired via hooks.py:
		doc_events = { "*": { "before_submit": _BPMN_GUARD, ... } }

	Decision logic:
	  1. Skip internal BPMN doctypes (prevent recursion).
	  2. If frappe.flags.bpmn_engine_action is True, this call originates from
		 the BPMN engine itself (service task) — allow it through.
	  3. Query for an Active BPMN Process Instance on this document.
		 - No instance → Frappe workflow rules apply normally. Allow.
		 - Active instance found → Block with a user-friendly error asking
		   the user to use the Actions menu instead.
	"""
	# 1. Never guard internal BPMN doctypes
	if doc.doctype in _INTERNAL_DOCTYPES:
		return

	# 2. Allow the BPMN engine's own service tasks to modify documents
	if getattr(frappe.flags, "bpmn_engine_action", False):
		return

	# 3. Check for an active BPMN instance controlling this document
	active_instance = frappe.db.get_value(
		"BPMN Process Instance",
		{
			"context_doctype": doc.doctype,
			"context_docname": doc.name,
			"status": "Active",
		},
		"name",
	)

	if not active_instance:
		return  # No active BPMN — Frappe can do whatever it likes

	# Active BPMN found — block the native action
	_action_labels = {
		"before_submit": "submit",
		"before_cancel": "cancel",
		"before_workflow_action": "change the workflow state of",
	}
	action_verb = _action_labels.get(method, "modify")

	frappe.throw(
		frappe._(
			"Cannot {0} <b>{1} {2}</b> directly. "
			"This document is controlled by a BPMN process (<b>{3}</b>). "
			"Use the <b>Actions</b> menu to proceed."
		).format(action_verb, doc.doctype, doc.name, active_instance),
		title=frappe._("Action Blocked — BPMN Process Active"),
	)


def delete_linked_bpmn_instances(doc, method: str):
	"""
	On document trash:
	  1. Try to deliver a Delete message to active instances so the BPMN
	     delete flow can run (e.g. delete the linked Google Task).
	  2. Cancel all active instances and unlink them so Frappe can
	     proceed with the document deletion.
	"""
	if doc.doctype in _INTERNAL_DOCTYPES:
		return

	# Find all BPMN instances linked to this document
	instances = frappe.get_all(
		"BPMN Process Instance",
		filters={
			"context_doctype": doc.doctype,
			"context_docname": doc.name,
		},
		fields=["name", "status"],
	)

	if not instances:
		return

	# Set flag to prevent guards from blocking
	frappe.flags.bpmn_engine_action = True

	try:
		# Step 1: Try to deliver Delete message to active instances
		# so the BPMN delete flow can execute (e.g. delete Google Task)
		delete_message = f"{doc.doctype.replace(' ', '')}_Delete_Action"
		for inst in instances:
			if inst.status == "Active":
				try:
					instance_doc = frappe.get_doc("BPMN Process Instance", inst.name)
					instance_doc.receive_message(
						message_name=delete_message,
						payload={
							"deleted_by": frappe.session.user,
							"deleted_doctype": doc.doctype,
							"deleted_docname": doc.name,
						},
					)
				except frappe.ValidationError:
					# No task waiting for this message — diagram has no delete
					# catch event. That's fine, fall through to cancel.
					pass
				except Exception:
					frappe.log_error(
						title=f"BPMN delete message failed for {inst.name}",
						message=frappe.get_traceback(),
					)

		# Step 2: Cancel active instances and unlink the document
		for inst in instances:
			try:
				updates = {"context_docname": None}
				if inst.status == "Active":
					updates["status"] = "Cancelled"
				frappe.db.set_value(
					"BPMN Process Instance", inst.name,
					updates,
					update_modified=False,
				)
			except Exception:
				frappe.log_error(
					title=f"Failed to unlink BPMN instance {inst.name}",
					message=frappe.get_traceback(),
				)
	finally:
		frappe.flags.bpmn_engine_action = False

