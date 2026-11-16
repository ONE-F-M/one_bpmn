# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Cleanup for suites that create real conversations.

``create_conversation`` and the message helpers commit, so a conversation made
in ``setUp`` survives the test rollback. Left alone, every run of every suite in
this area adds rows that nobody will ever look at again — and they are no longer
invisible: the Processa sessions screen lists conversations, so leaked fixtures
turn into permanent clutter on somebody's admin screen.

Call :func:`drop_conversations` from ``tearDown`` with whatever the test made.
"""

import frappe

# Everything that points at a Chat Conversation and would be orphaned by
# deleting one. Child tables are cleared by parent, not by link.
_LINKED = (
	("Chat Message", "conversation"),
	("Chat Conversation Summary", "conversation"),
	("AI Response Feedback", "conversation"),
	("AI Skill Activation", "conversation"),
)


def drop_conversations(*names) -> None:
	"""Remove conversations and everything hanging off them.

	Accepts names, or iterables of names, so a suite can pass a single value or
	its whole list. Never raises: a cleanup failure must not mask the result of
	the test that just ran.
	"""
	flat = []
	for n in names:
		if not n:
			continue
		flat.extend([n] if isinstance(n, str) else list(n))
	if not flat:
		return

	try:
		for name in flat:
			for doctype, field in _LINKED:
				frappe.db.delete(doctype, {field: name})
			frappe.db.delete("Chat Session State Entry", {"parent": name})
			frappe.db.delete("Chat Session State", {"name": name})
			frappe.db.delete("Chat Conversation", {"name": name})
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
