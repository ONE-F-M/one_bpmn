from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.utils import translation
from one_bpmn.utils.translation import TranslationError, translate, translate_cached, translate_text

TRANSLATOR = "one_bpmn.utils.translation.GoogleTranslator"
FALLBACK = "one_bpmn.utils.translation.MyMemoryTranslator"
MODEL = "Test Translation Model"


def _fake(result_for):
	"""Patch target whose translate() maps the masked text through result_for."""
	return patch(TRANSLATOR, **{"return_value.translate.side_effect": result_for})


def _fallback(result_for):
	"""Patch MyMemory the same way."""
	return patch(FALLBACK, **{"return_value.translate.side_effect": result_for})


class TestTranslateText(FrappeTestCase):
	def test_placeholders_come_back_unchanged(self):
		with (
			_fake(lambda masked: masked.replace("Leave for", "إجازة لـ")) as translator,
			_fallback(lambda masked: "x") as fallback,
		):
			result = translate_text("Leave for {{ doc.employee_name }} on {{doc.from_date}}")
		self.assertEqual(result, "إجازة لـ {{ doc.employee_name }} on {{doc.from_date}}")
		sent = translator.return_value.translate.call_args.args[0]
		self.assertNotIn("{{", sent)
		fallback.assert_not_called()

	def test_google_failure_falls_back_to_mymemory(self):
		with (
			_fake(ConnectionError("captcha")),
			_fallback(lambda masked: masked.replace("Leave for", "إجازة لـ")) as fallback,
			patch("frappe.log_error") as log_error,
		):
			result = translate_text("Leave for {{ doc.employee_name }}")
		self.assertEqual(result, "إجازة لـ {{ doc.employee_name }}")
		self.assertEqual(fallback.return_value.translate.call_args.args[0], "Leave for [0]")
		log_error.assert_called_once()

	def test_mymemory_quota_warning_raises(self):
		warning = "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY."
		with _fake(ConnectionError("captcha")), _fallback(lambda masked: warning), patch("frappe.log_error"):
			with self.assertRaises(TranslationError):
				translate_text("Hello")

	def test_lost_marker_logs_and_raises(self):
		with (
			_fake(lambda masked: "إجازة"),
			_fallback(lambda masked: "إجازة"),
			patch("frappe.log_error") as log_error,
		):
			with self.assertRaises(TranslationError):
				translate_text("Leave for {{ doc.employee_name }}")
		self.assertEqual(log_error.call_count, 2)

	def test_changed_marker_raises(self):
		with (
			_fake(lambda masked: masked.replace("__PH0__", "__ph0__")),
			_fallback(lambda masked: masked.replace("[0]", "[ 0 ]")),
			patch("frappe.log_error"),
		):
			with self.assertRaises(TranslationError):
				translate_text("Hi {{ name }}")

	def test_service_error_logged_and_raised_from_cause(self):
		with (
			_fake(ConnectionError("timeout")),
			_fallback(ConnectionError("timeout")),
			patch("frappe.log_error") as log_error,
		):
			with self.assertRaises(TranslationError) as caught:
				translate_text("Hello")
		self.assertEqual(log_error.call_count, 2)
		self.assertIsInstance(caught.exception.__cause__, ConnectionError)

	def test_blank_text_skips_the_service(self):
		with _fake(lambda masked: "x") as translator:
			self.assertEqual(translate_text("   "), "")
			self.assertEqual(translate_text(""), "")
		translator.assert_not_called()


class TestTranslateCached(FrappeTestCase):
	def setUp(self):
		translate_cached.clear_cache()

	def tearDown(self):
		translate_cached.clear_cache()

	def test_second_call_served_from_cache(self):
		with _fake(lambda masked: "موافقة") as translator:
			self.assertEqual(translate_cached("Approve"), "موافقة")
			self.assertEqual(translate_cached("Approve"), "موافقة")
		self.assertEqual(translator.return_value.translate.call_count, 1)

	def test_failure_raises_and_is_not_cached(self):
		with _fake(ConnectionError("quota")), _fallback(ConnectionError("quota")), patch("frappe.log_error"):
			with self.assertRaises(TranslationError):
				translate_cached("Reject")
		with _fake(lambda masked: "رفض") as translator:
			self.assertEqual(translate_cached("Reject"), "رفض")
		translator.return_value.translate.assert_called_once()


class TestTranslateEndpoint(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("BPMN Process Model", MODEL):
			frappe.get_doc(
				{
					"doctype": "BPMN Process Model",
					"title": MODEL,
					"process_id": frappe.scrub(MODEL),
					"version": "1.0",
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_writer_gets_arabic(self):
		with _fake(lambda masked: "مرحبا"):
			self.assertEqual(translate("Hello", process_model=MODEL), "مرحبا")
			self.assertEqual(translate("Hello"), "مرحبا")

	def test_user_without_write_is_refused_before_the_service(self):
		frappe.set_user("Guest")
		with _fake(lambda masked: "x") as translator:
			with self.assertRaises(frappe.PermissionError):
				translate("Hello", process_model=MODEL)
			with self.assertRaises(frappe.PermissionError):
				translate("Hello")
		translator.assert_not_called()

	def test_post_only(self):
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[translation.translate], ["POST"])

	def test_long_text_refused_before_the_service(self):
		with _fake(lambda masked: "x") as translator:
			with self.assertRaises(frappe.ValidationError):
				translate("a" * 5001, process_model=MODEL)
		translator.assert_not_called()
