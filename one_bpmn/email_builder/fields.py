"""Field builders for email content.

``build_attachment_links`` turns the files attached to a document into
signed download links that work without an ERPNext session.
"""

from __future__ import annotations

from urllib.parse import urlencode

import frappe

from one_bpmn.utils.token import generate_file_token

DOWNLOAD_METHOD = "/api/method/one_bpmn.api.todo_actions.download_attachment"


def build_attachment_links(doc, expiry_hours: int = 72) -> list[dict]:
	"""Return ``[{file_name, url}]`` for every file attached to ``doc``.

	Args:
		doc: The document whose attachments are linked (needs ``doctype`` and ``name``).
		expiry_hours: Hours until each signed link expires.

	Returns:
		One dict per attached file, oldest first. ``url`` is an absolute signed link.
	"""
	files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": doc.doctype,
			"attached_to_name": doc.name,
			"is_folder": 0,
		},
		fields=["name", "file_name"],
		order_by="creation asc, name asc",
	)

	links = []
	for row in files:
		token = generate_file_token(row.name, doc.doctype, doc.name, expiry_hours)
		links.append(
			{
				"file_name": row.file_name or row.name,
				"url": frappe.utils.get_url(f"{DOWNLOAD_METHOD}?{urlencode({'token': token})}"),
			}
		)
	return links
