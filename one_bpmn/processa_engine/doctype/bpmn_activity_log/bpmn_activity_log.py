# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class BPMNActivityLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action: DF.Literal["Started", "Completed", "Errored", "Skipped", "Timer Expired", "Error Boundary Activated", "Sub-Process Started", "Sub-Process Completed", "Message Received", "Ad-Hoc Task Activated", "AI Task Selected", "Cancelled", "Suspended", "Resumed", "Retried"]
		data: DF.JSON | None
		instance: DF.Link | None
		task_id: DF.Data | None
		task_name: DF.Data | None
		timestamp: DF.Datetime | None
		user: DF.Link | None
	# end: auto-generated types
	pass


def on_doctype_update():
	"""Index the duplicate check every engine step runs before it writes a log row."""
	frappe.db.add_index("BPMN Activity Log", ["instance", "task_id", "action"])
