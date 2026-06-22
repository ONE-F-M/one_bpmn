"""Comment submission API endpoint for AMP email forms.

Provides a whitelisted Frappe endpoint that allows authenticated users to
submit comments on documents directly from AMP-powered emails.  The
endpoint validates input, checks permissions, persists the comment via
the standard Frappe comment API, and returns the new comment's name.

Typical usage from an AMP ``<amp-form>``::

	POST /api/method/one_bpmn.api.comment.submit_comment
	Content-Type: application/x-www-form-urlencoded

	comment=Looks+good&doctype=Task&name=TASK-00001
"""

from __future__ import annotations

import frappe


@frappe.whitelist(allow_guest=False)
def submit_comment(comment: str, doctype: str, name: str) -> dict:
	"""Add a comment to a Frappe document.

	This endpoint is designed to be called from AMP-for-Email forms.  Only
	authenticated users with **read** permission on the target document are
	allowed to post comments.

	Args:
		comment: The comment body text.  Must be non-empty after stripping
			whitespace.
		doctype: The target DocType (e.g. ``"Task"``, ``"Issue"``).
		name: The document name / ID within the given DocType
			(e.g. ``"TASK-00001"``).

	Returns:
		A dict confirming success::

			{"ok": True, "comment_name": "Comment-xxxx"}

	Raises:
		frappe.exceptions.ValidationError: If *comment* is empty.
		frappe.exceptions.PermissionError: If the current user lacks read
			access to the specified document.
	"""
	if not comment or not comment.strip():
		frappe.throw("Comment cannot be empty.")

	if not frappe.has_permission(doctype, "read", name):
		frappe.throw(
			"You do not have permission to comment on this document.",
			frappe.PermissionError,
		)

	doc = frappe.get_doc(doctype, name)
	new_comment = doc.add_comment("Comment", comment.strip())
	frappe.db.commit()

	return {"ok": True, "comment_name": new_comment.name}
