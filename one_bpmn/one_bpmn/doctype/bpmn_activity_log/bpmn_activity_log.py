# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class BPMNActivityLog(Document):
	pass


def on_doctype_update():
	"""Index the duplicate check every engine step runs before it writes a log row."""
	frappe.db.add_index("BPMN Activity Log", ["instance", "task_id", "action"])
