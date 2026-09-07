# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001931: the A2A Client badge role.

Approved callers authenticate as service users carrying exactly this
role. It grants only what an inbound agent turn touches: the chat
records the turn produces. A2A Task permissions ride on that doctype's
own JSON (WI-001932), not here.
"""

import frappe
from frappe.permissions import add_permission, update_permission_property

from one_bpmn.agents.a2a.principal import A2A_CLIENT_ROLE, ensure_client_role

GRANTS = (
	("Chat Conversation", ("read", "write", "create")),
	("Chat Message", ("read", "create")),
)


def execute():
	ensure_client_role()
	for doctype, ptypes in GRANTS:
		add_permission(doctype, A2A_CLIENT_ROLE, 0)
		for ptype in ptypes:
			update_permission_property(doctype, A2A_CLIENT_ROLE, 0, ptype, 1)
	frappe.clear_cache()
