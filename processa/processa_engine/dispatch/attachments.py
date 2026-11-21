"""Files a person attached to a chat turn, read for the model: images as images, text files as text."""

import base64
import mimetypes

import frappe
from frappe import _

IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
TEXT_TYPES = frozenset({"application/json", "application/xml"})
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 50_000


def read_attachments(file_urls: list | None) -> tuple[list, str]:
	"""The images to send with the prompt, and a text block with the text files and the files not read."""
	images, parts = [], []
	for url in file_urls or []:
		name = frappe.db.get_value("File", {"file_url": url}, "name")
		if not name:
			parts.append(_not_read(url.rsplit("/", 1)[-1], _("it could not be found")))
			continue
		file = frappe.get_doc("File", name)
		media_type = mimetypes.guess_type(file.file_name or "")[0] or ""
		if media_type in IMAGE_TYPES:
			content = file.get_content()
			if len(content) > MAX_IMAGE_BYTES:
				parts.append(_not_read(file.file_name, _("it is larger than 5 MB")))
			else:
				images.append({"media_type": media_type, "data": base64.b64encode(content).decode()})
		elif media_type.startswith("text/") or media_type in TEXT_TYPES:
			parts.append(_text_file(file))
		else:
			parts.append(_not_read(file.file_name, _("this file type cannot be read")))
	return images, "\n\n".join(parts)


def _text_file(file) -> str:
	content = file.get_content()
	text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
	if len(text) > MAX_TEXT_CHARS:
		return _not_read(file.file_name, _("it is longer than {0} characters").format(MAX_TEXT_CHARS))
	return _("Attached file {0}:").format(file.file_name) + f"\n```\n{text}\n```"


def _not_read(file_name: str, reason: str) -> str:
	return _(
		"The attached file {0} was not read: {1}. Tell the person this, then answer their message."
	).format(file_name, reason)
