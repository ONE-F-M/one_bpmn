# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""One delegation, as a thing you can look at.

A delegation used to exist only as an A2A Task row, which knows who was asked
but not what the work was about: nothing tied the delegating instance, the
task, the worker's instance and the document being worked on together. This
record is that tie, and it is what a process owner opens to see which agent is
on which item and how far along it is.

It is written by ``a2a/delegation.py`` and read-only in the UI - every
field is derived from the run, so an edited copy would only ever be wrong.
"""

from frappe.model.document import Document


class AgentDelegation(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		a2a_task: DF.Link | None
		attempt_count: DF.Int
		cancelled_at: DF.Datetime | None
		cancelled_by: DF.Link | None
		deadline_restarted: DF.Check
		delegating_agent: DF.Link | None
		delegation_depth: DF.Int
		ended_at: DF.Datetime | None
		error_message: DF.SmallText | None
		handoff_count: DF.Int
		instruction: DF.SmallText | None
		limit_value: DF.Int
		manual_attempt_count: DF.Int
		notified_at: DF.Datetime | None
		notified_user: DF.Link | None
		orchestrator_instance: DF.Link | None
		outcome_reported_at: DF.Datetime | None
		reached_value: DF.Int
		redelegated_at: DF.Datetime | None
		redelegated_by: DF.Link | None
		reference_doctype: DF.Link | None
		reference_name: DF.DynamicLink | None
		started_at: DF.Datetime | None
		status: DF.Literal["Delegated", "In Progress", "Needs Review", "Completed", "Failed", "Cancelled"]
		stopped_reason: DF.Literal["", "max_recursion_depth", "max_task_handoffs", "delegation_deadline_minutes", "turn_cap", "max_delegation_retries", "cancelled"]
		worker_agent: DF.Link
		worker_instance: DF.Link | None
	# end: auto-generated types
	pass
