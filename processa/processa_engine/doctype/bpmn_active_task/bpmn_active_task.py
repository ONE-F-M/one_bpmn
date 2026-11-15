# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class BPMNActiveTask(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		assigned_role: DF.Link | None
		assigned_user: DF.Data | None
		end_time: DF.Datetime | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		relieved_user: DF.Data | None
		reliever_user: DF.Data | None
		started_at: DF.Datetime | None
		status: DF.Literal["Waiting", "Completed", "Errored", "Cancelled"]
		target_docname: DF.DynamicLink | None
		target_doctype: DF.Link | None
		task_actions: DF.SmallText | None
		task_id: DF.Data | None
		task_name: DF.Data | None
		task_type: DF.Literal["User Task", "Script Task", "Service Task", "Send Task", "Manual Task", "AI Human Task"]
		timer_duration: DF.Duration | None
	# end: auto-generated types
	pass
