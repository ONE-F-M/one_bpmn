# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class BPMNStartEventConfig(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		bpmn_element_id: DF.Data | None
		cron_expression: DF.Data | None
		event_type: DF.Literal["", "None", "Conditional", "Timer", "Signal"]
		last_started_at: DF.Datetime | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		trigger_doctype: DF.Link | None
		trigger_event: DF.Literal["After Insert", "Validate", "Before Save", "On Update", "Before Submit", "On Submit", "Before Cancel", "On Cancel", "Before Update After Submit", "On Update After Submit"]
		trigger_type: DF.Literal["DocType Event", "Scheduler Event", "API"]
		workflow_state_condition: DF.Data | None
	# end: auto-generated types

	pass
