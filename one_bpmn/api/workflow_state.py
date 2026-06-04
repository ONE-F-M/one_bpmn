# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import cint

from one_bpmn.api.utils import _is_bpmn_super_user


def _audit_and_notify(doc, actor: str, original_modified=None) -> None:
	"""
	Record the triggering user as modified_by and broadcast a doc_update event.

	Called by service task handlers after every document save, submit, or cancel
	so that:
	  - The ERPNext audit trail (modified_by) shows the user whose action caused
	    the automated change, not "Administrator" or the raw session user.
	  - Any open Frappe desk form for the document auto-reloads via WebSocket.

	When running inside a bpmn_engine_action context the modified timestamp is
	also reverted to original_modified to prevent optimistic-lock conflicts on
	the user's open form (same timestamp-sync workaround as before).
	"""
	if not doc or not doc.doctype or not doc.name:
		return

	actor = actor or frappe.session.user

	if getattr(frappe.flags, "bpmn_engine_action", False) and original_modified:
		# Revert modified timestamp AND record the actor in one DB write
		frappe.db.set_value(
			doc.doctype, doc.name,
			{"modified": original_modified, "modified_by": actor},
			update_modified=False,
		)
		doc.modified = original_modified
		doc.modified_by = actor
	else:
		# Not an engine action — just stamp the actor without touching modified
		frappe.db.set_value(doc.doctype, doc.name, "modified_by", actor, update_modified=False)
		doc.modified_by = actor

	frappe.publish_realtime(
		"doc_update",
		{"modified": str(doc.modified), "modified_by": doc.modified_by},
		doctype=doc.doctype,
		docname=doc.name,
		after_commit=True,
	)


def _apply_docstatus_directly(doc, target_state: str, doc_status_hint: str, actor: str = None) -> None:
	"""
	Fallback used by ``_apply_bpmn_workflow_state`` when the DocType has no
	active Frappe Workflow.

	Behaviour (driven by ``doc_status_hint`` from the BPMN Service Task):
	  "0"  → save as draft (no state change if already submitted)
	  "1"  → submit the document
	  "2"  → cancel the document
	  ""   → save; also set ``workflow_state`` or ``status`` field if it exists

	``target_state`` is set into the first available field from:
	  1. ``workflow_state`` (standard Frappe workflow field)
	  2. ``status`` (common status field on many DocTypes)
	"""
	# ── Determine which field holds the state ─────────────────────────────
	state_field = None
	if target_state:
		meta = frappe.get_meta(doc.doctype)
		if meta.has_field("workflow_state"):
			state_field = "workflow_state"
		elif meta.has_field("status"):
			state_field = "status"

	# Set the state field
	if state_field and target_state:
		doc.set(state_field, target_state)

	ds = str(doc_status_hint).strip()

	original_modified = doc.modified
	if ds == "1":
		if doc.docstatus == 0:
			doc.submit()
		# Already submitted — nothing to do
	elif ds == "2":
		if doc.docstatus == 1:
			doc.cancel()
		# If already cancelled or not submitted — nothing to do
	else:
		# Draft save (ds == "0" or unset)
		if doc.docstatus == 0:
			doc.save(ignore_permissions=True)
		elif doc.docstatus == 1:
			# Submitted doc — just save (amend notes etc.)
			doc.save(ignore_permissions=True)

	_audit_and_notify(doc, actor or frappe.session.user, original_modified)

	if target_state:
		doc.add_comment("Workflow", _(target_state))


def _apply_bpmn_workflow_state(
	doctype: str,
	docname: str,
	target_state: str,
	doc_status_hint: str = "",
	only_allow_role: str = "",
	triggered_by: str = None,
) -> None:
	"""
	Apply a Frappe Workflow state transition to a document.

	This is the backend implementation for the BPMN Service Task
	``serviceType = apply_workflow``.  It mirrors Frappe's own
	``frappe.model.workflow.apply_workflow`` exactly:

	1. Permission check  — ``onlyAllowEdit`` role guard (if configured)
	2. Load fresh doc    — always works from DB to prevent stale data
	3. Workflow lookup   — finds the active Workflow for the DocType
	4. State validation  — verifies the target state exists in the workflow
	5. Transition lookup — finds a valid transition from current → target
	6. Self-approval     — delegates to Frappe's ``has_approval_access``
	7. State + docstatus — calls doc.save / doc.submit / doc.cancel
	8. Workflow comment  — adds a "Workflow" type comment (same as Frappe)

	Args:
		doctype:         The Frappe DocType (e.g. ``Employee Daily Action``)
		docname:         The document name
		target_state:    The workflow state to move to (e.g. ``Submitted``)
		only_allow_role: If non-empty, only users with this role may perform
						 the action (mirrors the Frappe workflow state's
						 ``allow_edit`` field)
		triggered_by:    The user who triggered the BPMN instance
						 (used in place of frappe.session.user when the engine
						 runs in a background worker context)

	Raises:
		frappe.PermissionError  — role check failed
		frappe.ValidationError  — invalid state or illegal docstatus transition
	"""
	from frappe.model.workflow import get_workflow_name, get_workflow, has_approval_access
	from frappe.model.docstatus import DocStatus

	actor = triggered_by or frappe.session.user

	# ── 1. Role guard ─────────────────────────────────────────────────────────
	if only_allow_role and not _is_bpmn_super_user(actor):
		user_roles = frappe.get_roles(actor)
		if only_allow_role not in user_roles:
			frappe.throw(
				_("Only users with the role '{0}' can perform this workflow action.").format(only_allow_role),
				frappe.PermissionError,
			)

	# ── 2. Load fresh doc ─────────────────────────────────────────────────────
	doc = frappe.get_doc(doctype, docname)

	# ── 3. Workflow lookup (graceful — doctype may not have a Frappe Workflow) ─
	# get_workflow_name() returns None when no active Frappe Workflow is
	# configured.  Calling get_workflow(doctype) when no name exists passes
	# None to frappe.get_cached_doc() which raises "Workflow not found".
	# We check the name first to avoid that exception.
	workflow_name = get_workflow_name(doctype)
	workflow = None
	if workflow_name:
		try:
			workflow = get_workflow(doctype)
		except Exception:
			workflow = None

	if not workflow:
		# ── FALLBACK: No Frappe Workflow configured on this DocType ────────────
		# Apply docstatus transition directly (Draft → Submit → Cancel) and
		# optionally set workflow_state / workflow_field if they exist on the doc.
		_apply_docstatus_directly(doc, target_state, doc_status_hint, actor=actor)
		return

	# ── 4. State validation ───────────────────────────────────────────────────
	next_state_row = next((s for s in workflow.states if s.state == target_state), None)
	if not next_state_row:
		frappe.throw(
			_("Workflow state '{0}' not found in Workflow '{1}'.").format(target_state, workflow.name)
		)

	# ── 5. Transition lookup ──────────────────────────────────────────────────
	current_state = doc.get(workflow.workflow_state_field)
	transition = None
	for t in workflow.transitions:
		if t.state == current_state and t.next_state == target_state:
			transition = t
			break

	# If no transition exists AND we're not already in the target state,
	# we cannot move there.
	if transition is None and current_state != target_state:
		frappe.throw(
			_("No valid Workflow transition from '{0}' to '{1}' exists in Workflow '{2}'.").format(
				current_state, target_state, workflow.name
			),
			frappe.ValidationError,
		)

	# ── 6. Self-approval check ────────────────────────────────────────────────
	if transition and not has_approval_access(actor, doc, transition):
		frappe.throw(_("Self approval is not allowed"))

	# ── 7. Apply state + docstatus ────────────────────────────────────────────
	# Check idempotency FIRST - if already in the target state and docstatus
	# matches, skip all transitions to avoid side effects on re-run.
	if current_state == target_state:
		return

	doc.set(workflow.workflow_state_field, target_state)

	if next_state_row.update_field:
		doc.set(next_state_row.update_field, next_state_row.update_value)

	new_docstatus = DocStatus(cint(next_state_row.doc_status or 0))
	# If the BPMN diagram explicitly specifies Document Status, use it as an
	# override (e.g. the state row in Frappe says 0 but the diagram says 1).
	if doc_status_hint in ("0", "1", "2"):
		new_docstatus = DocStatus(cint(doc_status_hint))

	original_modified = doc.modified
	if doc.docstatus.is_draft() and new_docstatus.is_draft():
		doc.save(ignore_permissions=True)
	elif doc.docstatus.is_draft() and new_docstatus.is_submitted():
		from frappe.core.doctype.submission_queue.submission_queue import queue_submission
		from frappe.utils.scheduler import is_scheduler_inactive

		if doc.meta.queue_in_background and not is_scheduler_inactive():
			queue_submission(doc, "Submit")
			return
		doc.submit()
	elif doc.docstatus.is_submitted() and new_docstatus.is_submitted():
		doc.save(ignore_permissions=True)
	elif doc.docstatus.is_submitted() and new_docstatus.is_cancelled():
		doc.cancel()
	else:
		frappe.throw(
			_("Illegal document status transition to state '{0}'.").format(target_state),
			frappe.ValidationError,
		)

	_audit_and_notify(doc, actor, original_modified)

	# ── 8. Workflow comment (same as Frappe's apply_workflow) ─────────────────
	doc.add_comment("Workflow", _(target_state))
