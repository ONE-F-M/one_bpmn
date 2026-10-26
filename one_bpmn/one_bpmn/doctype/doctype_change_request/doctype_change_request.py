# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A proposed DocType change logged for Process Owner approval.

Created by ``one_bpmn.api.docu_api.apply_doctype`` when the requesting user is
not a Process Owner of any process whose Process Doctypes table lists the
DocType. Applied by ``docu_api.approve_doctype_change``.
"""

from frappe.model.document import Document


class DoctypeChangeRequest(Document):
	pass
