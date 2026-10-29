import re

import frappe
from deep_translator import GoogleTranslator
from frappe import _
from frappe.utils.caching import redis_cache

MAX_EDITOR_TEXT = 5000
PLACEHOLDER_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)


class TranslationError(frappe.ValidationError):
	pass


def translate_text(text: str, target: str = "ar") -> str:
	"""Translate English text, keeping every {{ ... }} placeholder exactly as written."""
	if not (text or "").strip():
		return ""

	placeholders = PLACEHOLDER_RE.findall(text)
	masked = text
	for i, placeholder in enumerate(placeholders):
		masked = masked.replace(placeholder, _marker(i), 1)

	try:
		translated = GoogleTranslator(source="en", target=target).translate(masked)
	except Exception as e:
		frappe.log_error(title="Arabic translation failed", message=frappe.get_traceback())
		raise TranslationError(_("Translation service failed")) from e

	for i, placeholder in enumerate(placeholders):
		if (translated or "").count(_marker(i)) != 1:
			frappe.log_error(
				title="Arabic translation lost a placeholder",
				message=f"Placeholder {placeholder} did not come back.\nSent: {masked}\nGot: {translated}",
			)
			raise TranslationError(_("Translation changed a placeholder"))
		translated = translated.replace(_marker(i), placeholder)
	return translated


def _marker(i: int) -> str:
	return f"__PH{i}__"


@redis_cache(ttl=86400)
def translate_cached(text: str) -> str:
	"""translate_text to Arabic, shared across users; a failure raises and is not cached."""
	return translate_text(text)


@frappe.whitelist(methods=["POST"])
def translate(text: str, process_model: str = "") -> str:
	"""Arabic for the modeler's English field; needs write on the model, or create when unsaved."""
	if process_model:
		frappe.get_doc("BPMN Process Model", process_model).check_permission("write")
	else:
		frappe.has_permission("BPMN Process Model", "create", throw=True)

	if len(text or "") > MAX_EDITOR_TEXT:
		frappe.throw(
			_("Text is too long to translate. Keep it under {0} characters.").format(MAX_EDITOR_TEXT)
		)
	return translate_text(text)
