# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Switching user without wrecking the caller's session.

``frappe.set_user`` does three things and only the first is ever wanted: it sets
``session.user``, it overwrites ``session.sid`` with the username, and it empties
``session.data``. Restoring the user alone leaves the other two wrecked, and the
damage lands on the next request, not this one: ``Session.update`` writes the
gutted session dict back into the cache under the real cookie sid, so the browser
then reads a session with no user in it and every page dies with "User None is
disabled. Please contact your System Manager."
"""

from __future__ import annotations

from contextlib import contextmanager

import frappe


@contextmanager
def as_user(user: str | None):
	"""Run the block as ``user``, then hand the caller back its session intact.

	A falsy user, or the user we already are, is a no-op rather than an error:
	callers switch to a user they looked up, and "nobody to switch to" is a normal
	answer there.
	"""
	original = frappe.session.user
	if not user or user == original:
		yield
		return

	saved_sid = frappe.session.sid
	saved_data = frappe.session.data
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(original)
		frappe.session.sid = saved_sid
		frappe.session.data = saved_data
