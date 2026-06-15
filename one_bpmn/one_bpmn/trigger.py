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


# Internal helpers


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
	Automatically delete any BPMN Process Instance linked to a document
	when that document is deleted (on_trash).

	This ensures that orphaned process instances don't clutter the database
	when their parent documents are removed.
	"""
	# 1. Never clean up internal BPMN doctypes (standard safety check)
	if doc.doctype in _INTERNAL_DOCTYPES:
		return

	# 2. Find all instances (Active or otherwise) linked to this document
	instances = frappe.get_all(
		"BPMN Process Instance",
		filters={
			"context_doctype": doc.doctype,
			"context_docname": doc.name,
		},
		pluck="name",
	)

	if not instances:
		return

	# 3. Clean up dependent Activity Logs first
	# This avoids orphaned records and allows us to delete the instance without force=True
	frappe.db.delete("BPMN Activity Log", {"instance": ["in", instances]})

	# 4. Delete the instances permanently
	# We use ignore_permissions=True to ensure cleanup happens regardless
	# of the current user's delete permissions on BPMN Process Instance.
	for instance_name in instances:
		try:
			# Try standard deletion first (cleaner)
			frappe.delete_doc("BPMN Process Instance", instance_name, ignore_permissions=True)
		except Exception:
			# Fallback to force delete if normal deletion fails (e.g. due to other unknown links)
			# to ensure we don't block the parent document from being deleted.
			try:
				frappe.delete_doc(
					"BPMN Process Instance", instance_name, ignore_permissions=True, force=True
				)
			except Exception:
				frappe.log_error(
					title=f"Failed to delete BPMN instance {instance_name} linked to deleted {doc.doctype} {doc.name}",
					message=frappe.get_traceback(),
				)

