# Copyright (c) 2026, one-fm and contributors
"""Runtime failure records: halt the instance, log the traceback for admins, show the user only a Reference ID."""

import sys

import frappe
from frappe import _

from one_bpmn.processa_engine.runtime.common import log_task, settle_goal_completion


def fail_runtime(instance, phase: str):
	"""Record the failure in flight and raise a sanitized Reference ID error. Call from inside an except block."""
	in_flight = sys.exc_info()[1]
	if in_flight is not None:
		from one_bpmn.ai_agent_guardrails.refusal import AgentRefusal

		# A security control's refusal is a decision with its own message, not a fault to halt on.
		if isinstance(in_flight, AgentRefusal):
			raise in_flight

		# A permission error names only what the user lacks: show it and keep the instance running.
		if isinstance(in_flight, frappe.PermissionError):
			if not str(in_flight).strip():
				frappe.throw(
					_(
						"You do not have permission to complete this step. "
						"Ask your administrator for access, then try again."
					),
					exc=frappe.PermissionError,
				)
			raise in_flight

	ref_id = record_runtime_failure(instance, phase)
	frappe.throw(
		_(
			"This process could not continue and has been halted due to an "
			"internal error. Quote Reference ID {0} to your administrator for "
			"assistance."
		).format(ref_id),
		title=_("Process Halted"),
	)


def record_runtime_failure(instance, phase: str) -> str:
	"""Mark the instance Errored, commit it and log the live traceback under a new Reference ID, which it returns.

	Both sinks, the Error Log and the BPMN Activity Log, are admin-only. Call from inside an except block.
	"""
	ref_id = frappe.generate_hash(length=12).upper()

	detail = (
		f"Reference ID: {ref_id}\n"
		f"Phase: {phase}\n"
		f"Instance: {instance.name}\n"
		f"Process Model: {instance.process_model}\n"
		f"Context: {instance.context_doctype or '-'} / {instance.context_docname or '-'}\n"
		f"Initiated by: {instance.initiated_by or '-'}\n"
		f"\n{frappe.get_traceback()}"
	)
	# log_error cuts the title at about 140 characters, so the Reference ID goes first.
	frappe.log_error(title=f"BPMN runtime failure [{ref_id}] - {instance.name}", message=detail)

	try:
		frappe.db.set_value(
			"BPMN Process Instance", instance.name, "status", "Errored", update_modified=False
		)
		instance.status = "Errored"
		settle_goal_completion(instance, "Errored")
		log_task(
			instance,
			task_id=f"runtime-failure::{ref_id}",
			task_name=f"Runtime failure ({phase})",
			action="Errored",
			data={"reference_id": ref_id, "phase": phase},
		)
		# The sanitized error the caller raises next rolls the request back; the Errored state must survive it.
		frappe.db.commit()
	except Exception:
		frappe.log_error(
			title=f"BPMN: failed to persist Errored state [{ref_id}]",
			message=frappe.get_traceback(),
		)

	return ref_id
