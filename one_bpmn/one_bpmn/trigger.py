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

# Maps Frappe document events  →  BPMN message names to deliver.
# Used by Section C: when a document with an active BPMN instance changes,
# deliver the corresponding BPMN message to the waiting EventBasedGateway.
# The message name MUST match the <bpmn:message name="..."> in the BPMN XML.
# Convention: {DocType}_{Action}_Action  e.g. ToDo_Edit_Action
#
# The mapping is generic: {frappe_event: message_name_suffix}
# The full message name is constructed as: {DocType}_{suffix}
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


	# ── C) Deliver messages to waiting instances ──────────────────────────────
	# If this event maps to a BPMN message (on_update → Edit_Action, etc.),
	# deliver the message to any active instance waiting at an EventBasedGateway.
	# Guard: only fire once per document per request to avoid duplicate messages
	# from Frappe's after_insert → on_update → after_save chain.
	message_suffix = _FRAPPE_EVENT_TO_MESSAGE_SUFFIX.get(method)
	if message_suffix:
		_maybe_send_message(doc, message_suffix)


# Internal helpers


def _maybe_send_message(doc, message_suffix: str):
	"""
	Deliver a BPMN message to any active instance waiting on this document.

	Constructs the full message name from the doctype + suffix convention:
	  {DocType (no spaces)}_{suffix}   e.g.  ToDo_Edit_Action

	Guards:
	  - Only sends once per document per request (frappe.flags dedup)
	  - Skips if no active instance exists for this document
	  - Swallows exceptions so document saves are never blocked

	The message is delivered to the instance's EventBasedGateway which will
	fire the matching IntermediateCatchEvent and continue the flow.
	"""
	# Guard: Don't send edit messages during document creation.
	# When a new document is inserted, Frappe fires after_insert → on_update → after_save
	# in a single request. The instance was JUST started by after_insert and is still in the
	# creation flow (not yet waiting). Sending Edit_Action here would crash or be a no-op.
	# We use frappe.flags (request-scoped) because doc attributes may not survive
	# if Frappe refreshes the doc object between hook calls.
	bpmn_created = frappe.flags.get("_bpmn_instances_just_started") or set()
	doc_id = f"{doc.doctype}:{doc.name}"
	if doc_id in bpmn_created:
		return

	# Per-request dedup: Frappe fires after_insert → on_update → after_save
	# in a single transaction. We only want to deliver the message once.
	# NOTE: frappe.flags is a _dict — missing keys return None, not AttributeError.
	if not frappe.flags._bpmn_message_sent:
		frappe.flags._bpmn_message_sent = set()

	doc_key = f"{doc.doctype}:{doc.name}:{message_suffix}"
	if doc_key in frappe.flags._bpmn_message_sent:
		return  # Already sent in this request
	frappe.flags._bpmn_message_sent.add(doc_key)

	# Construct the BPMN message name
	# Convention: DocType with spaces removed + suffix
	doctype_clean = doc.doctype.replace(" ", "")
	message_name = f"{doctype_clean}_{message_suffix}"

	# Find active instances for this document
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
			# Capture the previous status from Frappe's before-save snapshot.
			# By the time on_update fires, the DB already has the new value,
			# so the validate script can't detect status changes without this.
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
		except Exception:
			# Never block the document save — log and move on
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
	Handle document deletion: first deliver a Delete message to any active
	BPMN Process Instance so the delete flow in the diagram can execute
	(e.g. sync deletion to Google Tasks), then clean up the instance.

	If the message delivery fails or there's no matching catch event,
	fall back to direct deletion so we never block the document trash.
	"""
	# 1. Never clean up internal BPMN doctypes (standard safety check)
	if doc.doctype in _INTERNAL_DOCTYPES:
		return

	# 2. Find all instances linked to this document
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

	# 3. For active instances, deliver the Delete message so the BPMN
	#    delete flow can execute (e.g. sync deletion to Google Tasks).
	#    If message delivery succeeds, the diagram handles the lifecycle
	#    and the instance completes naturally — we do NOT force-delete it.
	delete_message = f"{doc.doctype.replace(' ', '')}_Delete_Action"
	message_delivered = set()

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
				message_delivered.add(inst.name)
			except Exception:
				frappe.log_error(
					title=f"BPMN delete message failed for {inst.name}",
					message=frappe.get_traceback(),
				)

	# 4. For instances where the message was delivered, unlink the
	#    context reference so Frappe's link-check allows the document
	#    deletion. The BPMN delete flow continues independently.
	for inst_name in message_delivered:
		try:
			frappe.db.set_value(
				"BPMN Process Instance", inst_name,
				{"context_docname": None},
				update_modified=False,
			)
		except Exception:
			frappe.log_error(
				title=f"Failed to unlink BPMN instance {inst_name}",
				message=frappe.get_traceback(),
			)

	# 5. Clean up instances where message delivery FAILED or
	#    the instance was not Active (already Completed/Errored/Cancelled).
	orphans = [i for i in instances if i.name not in message_delivered]

	if not orphans:
		return

	orphan_names = [i.name for i in orphans]
	frappe.db.delete("BPMN Activity Log", {"instance": ["in", orphan_names]})

	for inst in orphans:
		try:
			frappe.delete_doc("BPMN Process Instance", inst.name, ignore_permissions=True)
		except Exception:
			try:
				frappe.delete_doc(
					"BPMN Process Instance", inst.name, ignore_permissions=True, force=True
				)
			except Exception:
				frappe.log_error(
					title=f"Failed to delete BPMN instance {inst.name} linked to deleted {doc.doctype} {doc.name}",
					message=frappe.get_traceback(),
				)

