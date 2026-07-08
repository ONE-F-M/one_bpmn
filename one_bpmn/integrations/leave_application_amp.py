"""Leave Application config for the generic AMP workflow-action endpoint.

Kept inside ``one_bpmn`` (rather than ``one_fm``) so this rollout doesn't
require any change to the ``one_fm`` app — the ``amp_workflow_actions``
hook registration for Leave Application lives in ``one_bpmn/hooks.py``,
and this module holds the one small piece of doctype-aware logic that
registration needs (the "compute" step for "Propose New Dates").

``one_fm.overrides.leave_application.send_proposed_date_email`` is reused
unmodified as the "after" hook — it already existed before this feature
and isn't touched here.
"""

from __future__ import annotations


def compute_leave_propose_totals(doc, form_data):
	"""Set ``custom_total_propose_leave_days`` from the submitted proposed dates.

	Called by ``one_bpmn.api.workflow_actions.handle_workflow_action`` after
	``custom_propose_from_date``/``custom_propose_to_date`` have been set on
	*doc* but before it's saved, for the "Propose New Dates" AMP email
	action. Uses the same day-counting logic as the ERPNext UI's "Propose
	New Dates" dialog.
	"""
	from hrms.hr.doctype.leave_application.leave_application import get_number_of_leave_days

	doc.custom_total_propose_leave_days = get_number_of_leave_days(
		doc.employee,
		doc.leave_type,
		doc.custom_propose_from_date,
		doc.custom_propose_to_date,
	)
