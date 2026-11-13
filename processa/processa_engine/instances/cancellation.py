# Copyright (c) 2026, one-fm and contributors
"""Cancel requests: a submitted document whose DocType has a cancellation map is cancelled only when that map approves.

The map approves by ending with the process variable cancellation_approved set to a true value; any other end is a rejection.
"""

import frappe
from frappe import _

from processa.processa_engine.instances.listing import CANCEL_REQUEST_EVENT, get_cancellation_maps
from processa.processa_engine.instances.starting import start_process

APPROVAL_VARIABLE = "cancellation_approved"


def request_cancellation(doctype: str, docname: str) -> dict:
	"""Start the DocType's cancellation map on a submitted document instead of cancelling it."""
	model_name = get_cancellation_maps().get(doctype)
	if not model_name:
		frappe.throw(_("{0} has no active cancellation process.").format(_(doctype)))

	doc = frappe.get_doc(doctype, docname)
	doc.check_permission("cancel")
	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted document can be cancelled."))

	pending = pending_cancellation(doctype, docname)
	if pending:
		frappe.throw(
			_("A cancellation of {0} {1} is already pending in process {2}.").format(
				_(doctype), docname, pending
			),
			title=_("Cancellation Pending"),
		)

	return start_process(
		model_name,
		doctype,
		docname,
		{"triggered_by": frappe.session.user, "trigger_doctype": doctype, "trigger_docname": docname},
	)


def pending_cancellation(doctype: str, docname: str) -> str | None:
	"""The running cancellation instance of a document, if any."""
	model_name = get_cancellation_maps().get(doctype)
	if not model_name:
		return None
	return frappe.db.get_value(
		"BPMN Process Instance",
		{
			"process_model": model_name,
			"context_doctype": doctype,
			"context_docname": docname,
			"status": ["in", ["Queued", "Active"]],
		},
		"name",
	)


def set_pending_cancellation_onload(doc, method: str) -> None:
	"""Tell the desk form that a cancellation is pending (onload doc_events hook)."""
	if doc.docstatus == 1 and doc.doctype in get_cancellation_maps():
		doc.set_onload("pending_cancellation", pending_cancellation(doc.doctype, doc.name))


def refuse_direct_cancel(doc) -> None:
	"""Refuse a cancel the engine did not make on a DocType that has a cancellation map."""
	if doc.doctype not in get_cancellation_maps():
		return
	frappe.throw(
		_(
			"Cannot cancel <b>{0} {1}</b> directly. {0} needs an approved cancellation: "
			"open the document and press Cancel to request it."
		).format(_(doc.doctype), doc.name),
		title=_("Cancellation Needs Approval"),
	)


def settle_cancellation(instance, wf) -> None:
	"""Cancel the context document when a completed cancellation map approved it."""
	if not (instance.context_doctype and instance.context_docname) or not wf.data.get(APPROVAL_VARIABLE):
		return
	if not frappe.db.exists(
		"BPMN Start Event Config",
		{
			"parent": instance.process_model,
			"parenttype": "BPMN Process Model",
			"trigger_event": CANCEL_REQUEST_EVENT,
		},
	):
		return

	doc = frappe.get_doc(instance.context_doctype, instance.context_docname)
	if doc.docstatus != 1:
		return
	# The approver may lack cancel permission; the requester's was checked when the request started.
	frappe.has_permission(doc.doctype, "cancel", doc, user=instance.initiated_by, throw=True)
	doc.flags.ignore_permissions = True  # the requester holds cancel permission, checked on the line above
	previous_flag = frappe.flags.bpmn_engine_action
	frappe.flags.bpmn_engine_action = True
	try:
		doc.cancel()
	finally:
		frappe.flags.bpmn_engine_action = previous_flag
