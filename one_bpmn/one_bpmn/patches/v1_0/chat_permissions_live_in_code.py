"""Chat Conversation and Chat Message permissions come from their JSON again.

add_a2a_client_role granted the A2A Client role through add_permission(), which
copies every existing row into Custom DocPerm and lets that table govern from
then on. The doctype JSON has been dead weight since — the if_owner rule that
makes a conversation the creator's alone never reached a site.

Both doctypes are this app's own, so the rows belong in code. A2A Client's
grants now sit in the JSON, and carry if_owner like every other role: an inbound
turn creates its own conversation (run_chat_turn calls invoke_agent with no
conversation, so create_agent_conversation stamps the calling client as owner),
so a client never needs to reach one it did not start. The Custom DocPerm copies
go, and the doctypes are reloaded so the meta is rebuilt from the file.
"""

import frappe

DOCTYPES = ("Chat Conversation", "Chat Message")


def execute():
	for doctype in DOCTYPES:
		frappe.db.delete("Custom DocPerm", {"parent": doctype})
		frappe.reload_doc("one_bpmn", "doctype", frappe.scrub(doctype))
		frappe.clear_cache(doctype=doctype)
