# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
"""Apply a workflow state or docstatus to a document for a BPMN service task, then record the actor and notify."""

import frappe
from frappe import _
from frappe.utils import cint

from one_bpmn.api.utils import _is_bpmn_super_user


def _audit_and_notify(doc, actor: str, original_modified=None) -> None:
	"""Stamp *actor* as modified_by and publish doc_update so open desk forms reload.
	Inside a bpmn_engine_action, modified is restored to original_modified to avoid a timestamp conflict on the open form."""
	if not doc or not doc.doctype or not doc.name:
		return

	actor = actor or frappe.session.user

	if getattr(frappe.flags, "bpmn_engine_action", False) and original_modified:
		frappe.db.set_value(
			doc.doctype, doc.name,
			{"modified": original_modified, "modified_by": actor},
			update_modified=False,
		)
		doc.modified = original_modified
		doc.modified_by = actor
	else:
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
	"""Fallback for a DocType with no active Workflow: set *target_state* on workflow_state, else status, if present.
	``doc_status_hint`` "1" submits a draft, "2" cancels a submitted doc, anything else saves."""
	state_field = None
	if target_state:
		meta = frappe.get_meta(doc.doctype)
		if meta.has_field("workflow_state"):
			state_field = "workflow_state"
		elif meta.has_field("status"):
			state_field = "status"

	if state_field and target_state:
		doc.set(state_field, target_state)

	ds = str(doc_status_hint).strip()

	original_modified = doc.modified
	if ds == "1":
		if doc.docstatus == 0:
			doc.submit()
	elif ds == "2":
		if doc.docstatus == 1:
			doc.cancel()
	else:
		if doc.docstatus == 0:
			doc.save(ignore_permissions=True)  # the BPMN service task acts for the process
		elif doc.docstatus == 1:
			doc.save(ignore_permissions=True)  # the BPMN service task acts for the process

	_audit_and_notify(doc, actor or frappe.session.user, original_modified)

	if target_state:
		doc.add_comment("Workflow", _(target_state))


def apply_bpmn_workflow_state(
	doctype: str,
	docname: str,
	target_state: str,
	doc_status_hint: str = "",
	only_allow_role: str = "",
	triggered_by: str = None,
) -> None:
	"""Move a document to *target_state* the way frappe.model.workflow.apply_workflow does, for the apply_workflow service task.
	Checks only_allow_role, the transition and self-approval; with no active Workflow it falls back to _apply_docstatus_directly.
	*triggered_by* stands in for session.user when the engine runs in a background worker."""
	from frappe.model.workflow import get_workflow_name, get_workflow, has_approval_access
	from frappe.model.docstatus import DocStatus

	actor = triggered_by or frappe.session.user

	if only_allow_role and not _is_bpmn_super_user(actor):
		user_roles = frappe.get_roles(actor)
		if only_allow_role not in user_roles:
			frappe.throw(
				_("Only users with the role '{0}' can perform this workflow action.").format(only_allow_role),
				frappe.PermissionError,
			)

	doc = frappe.get_doc(doctype, docname)

	# get_workflow raises when no Workflow is active, so check the name first.
	workflow_name = get_workflow_name(doctype)
	workflow = None
	if workflow_name:
		try:
			workflow = get_workflow(doctype)
		except Exception:
			workflow = None

	if not workflow:
		_apply_docstatus_directly(doc, target_state, doc_status_hint, actor=actor)
		return

	next_state_row = next((s for s in workflow.states if s.state == target_state), None)
	if not next_state_row:
		frappe.throw(
			_("Workflow state '{0}' not found in Workflow '{1}'.").format(target_state, workflow.name)
		)

	current_state = doc.get(workflow.workflow_state_field)
	transition = None
	for t in workflow.transitions:
		if t.state == current_state and t.next_state == target_state:
			transition = t
			break

	if transition is None and current_state != target_state:
		frappe.throw(
			_("No valid Workflow transition from '{0}' to '{1}' exists in Workflow '{2}'.").format(
				current_state, target_state, workflow.name
			),
			frappe.ValidationError,
		)

	if transition and not has_approval_access(actor, doc, transition):
		frappe.throw(_("Self approval is not allowed"))

	if current_state == target_state:
		return

	doc.set(workflow.workflow_state_field, target_state)

	if next_state_row.update_field:
		doc.set(next_state_row.update_field, next_state_row.update_value)

	new_docstatus = DocStatus(cint(next_state_row.doc_status or 0))
	# A Document Status set in the diagram overrides the Workflow state row.
	if doc_status_hint in ("0", "1", "2"):
		new_docstatus = DocStatus(cint(doc_status_hint))

	original_modified = doc.modified
	if doc.docstatus.is_draft() and new_docstatus.is_draft():
		doc.save(ignore_permissions=True)  # the BPMN service task acts for the process
	elif doc.docstatus.is_draft() and new_docstatus.is_submitted():
		from frappe.core.doctype.submission_queue.submission_queue import queue_submission
		from frappe.utils.scheduler import is_scheduler_inactive

		if doc.meta.queue_in_background and not is_scheduler_inactive():
			queue_submission(doc, "Submit")
			return
		doc.submit()
	elif doc.docstatus.is_submitted() and new_docstatus.is_submitted():
		doc.save(ignore_permissions=True)  # the BPMN service task acts for the process
	elif doc.docstatus.is_submitted() and new_docstatus.is_cancelled():
		doc.cancel()
	else:
		frappe.throw(
			_("Illegal document status transition to state '{0}'.").format(target_state),
			frappe.ValidationError,
		)

	_audit_and_notify(doc, actor, original_modified)

	doc.add_comment("Workflow", _(target_state))
