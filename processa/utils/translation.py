import re

import frappe
from deep_translator import MyMemoryTranslator
from frappe import _
from frappe.integrations.utils import make_post_request
from frappe.utils.caching import redis_cache

GOOGLE_TRANSLATE_URL = "https://translation.googleapis.com/language/translate/v2"
MAX_EDITOR_TEXT = 5000
PLACEHOLDER_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)
GOOGLE_MARKER = "__PH{}__"
MYMEMORY_MARKER = "[{}]"
MYMEMORY_QUOTA_WARNING = "MYMEMORY WARNING"


class TranslationError(frappe.ValidationError):
	pass


def translate_text(text: str) -> str:
	"""English to Arabic, keeping every {{ ... }} placeholder exactly as written.
	Uses Google Cloud Translation when Processa Settings has its key, and MyMemory otherwise or when Google fails."""
	if not (text or "").strip():
		return ""

	key = frappe.get_cached_doc("Processa Settings").get_password(
		"google_translate_api_key", raise_exception=False
	)
	if key:
		try:
			return _translate(lambda masked: _google_translate(masked, key), text, GOOGLE_MARKER)
		except Exception:
			frappe.log_error(title="Arabic translation failed on Google", message=frappe.get_traceback())

	email = frappe.db.get_value("Email Account", {"default_outgoing": 1}, "email_id")
	try:
		translated = _translate(
			MyMemoryTranslator(source="en-GB", target="ar-SA", email=email).translate, text, MYMEMORY_MARKER
		)
		if translated.startswith(MYMEMORY_QUOTA_WARNING):
			raise TranslationError(translated)
	except Exception as e:
		frappe.log_error(title="Arabic translation failed on MyMemory", message=frappe.get_traceback())
		raise TranslationError(_("Translation service failed")) from e
	return translated


def _translate(translate, text: str, marker: str) -> str:
	"""Mask placeholders with marker, translate, and put them back; raise if one did not survive."""
	placeholders = PLACEHOLDER_RE.findall(text)
	masked = text
	for i, placeholder in enumerate(placeholders):
		masked = masked.replace(placeholder, marker.format(i), 1)

	translated = translate(masked) or ""
	for i, placeholder in enumerate(placeholders):
		# services sometimes return a marker with spaces inside it, such as "[0 ]"
		returned = re.compile(r"\s*".join(map(re.escape, marker.format(i))))
		if len(returned.findall(translated)) != 1:
			raise TranslationError(
				f"Placeholder {placeholder} did not come back.\nSent: {masked}\nGot: {translated}"
			)
		translated = returned.sub(lambda _match: placeholder, translated)
	return translated


def _google_translate(text: str, key: str) -> str:
	"""One Cloud Translation v2 call; the key goes in a header so it never reaches a logged URL.
	Referer is this site's URL, which a key restricted to websites needs."""
	response = make_post_request(
		GOOGLE_TRANSLATE_URL,
		headers={"X-goog-api-key": key, "Referer": frappe.utils.get_url() + "/"},
		json={"q": text, "source": "en", "target": "ar", "format": "text"},
	)
	return response["data"]["translations"][0]["translatedText"]


@redis_cache(ttl=86400)
def translate_cached(text: str) -> str:
	"""translate_text to Arabic, shared across users; a failure raises and is not cached."""
	return translate_text(text)


def translate_for_editor(text: str, process_model: str = "") -> str:
	"""Arabic for the modeler's English field; needs write on the model, or create when unsaved.
	Service behind the whitelisted processa.api.translation.translate."""
	if process_model:
		frappe.get_doc("BPMN Process Model", process_model).check_permission("write")
	else:
		frappe.has_permission("BPMN Process Model", "create", throw=True)

	if len(text or "") > MAX_EDITOR_TEXT:
		frappe.throw(
			_("Text is too long to translate. Keep it under {0} characters.").format(MAX_EDITOR_TEXT)
		)
	return translate_text(text)
