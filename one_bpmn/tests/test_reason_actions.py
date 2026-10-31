# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""One-tap reasons: the reason panel in the Decision card and the reason saved by handle_amp_action."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.translate import clear_cache

from one_bpmn.api import todo_actions
from one_bpmn.email_builder import composer
from one_bpmn.email_builder.renderer import render_layout_amp, render_layout_html
from one_bpmn.tests.test_amp_validation import _validate_amp4email
from one_bpmn.tests.test_decision_card import _card_ctx
from one_bpmn.tests.test_todo_actions import _make_token, _mock_secret, _setup_request

CHIPS = [["Dates clash", "تعارض التواريخ"], ["Not enough notice", ""]]


def _reason_cfg(**settings):
	return {
		"notifyActions": json.dumps(
			{"Reject": {"reason": True, "reasonField": "description", "chips": CHIPS, **settings}}
		)
	}


class TestReasonSaved(FrappeTestCase):
	def setUp(self):
		clear_cache()
		self.todo = frappe.get_doc(
			{"doctype": "ToDo", "description": "Original", "allocated_to": "Administrator"}
		).insert()
		self.instance = frappe._dict(context_doctype="ToDo", context_docname=self.todo.name)

	def tearDown(self):
		frappe.set_user("Administrator")

	def _act(self, cfg=None, user="Administrator", **form):
		"""Post a Reject from the email; returns the response, the complete_task mock and the status code."""
		_setup_request()
		frappe.local.response.http_status_code = None
		token = _make_token(action="Reject", user=user)
		real_get_doc = frappe.get_doc

		def get_doc(*args, **kwargs):
			if args and args[0] == "BPMN Process Instance":
				return frappe._dict(context_doctype="", context_docname="")
			return real_get_doc(*args, **kwargs)

		with (
			_mock_secret(),
			patch("one_bpmn.api.instance_api.complete_task", return_value={"status": "Running"}) as complete,
			patch.object(todo_actions, "_get_instance_context", return_value=self.instance),
			patch.object(todo_actions, "_get_task_config", return_value=cfg or _reason_cfg()),
			patch.object(todo_actions, "_get_workflow_state_and_style", return_value=("", "")),
			patch.object(frappe, "get_doc", side_effect=get_doc),
		):
			result = todo_actions.handle_amp_action(token=token, **form)
		frappe.set_user("Administrator")
		return result, complete, frappe.local.response.http_status_code

	def _saved(self):
		return frappe.db.get_value("ToDo", self.todo.name, "description")

	def _comment(self, complete):
		return json.loads(complete.call_args.kwargs["data"])["comment"]

	def test_an_arabic_reader_saves_the_arabic_chip(self):
		result, complete, _status = self._act(reason_chip="0", reason_lang="ar")

		self.assertEqual(self._saved(), "تعارض التواريخ")
		self.assertEqual(self._comment(complete), "تعارض التواريخ")
		self.assertEqual(result["reason_saved"]["en"], "Reason saved to Description")
		self.assertTrue(result["reason_saved"]["ar"].startswith("تم حفظ السبب في"))

	def test_an_english_reader_saves_the_english_chip(self):
		self._act(reason_chip="0", reason_lang="en")
		self.assertEqual(self._saved(), "Dates clash")

	def test_a_chip_with_no_arabic_saves_the_english(self):
		self._act(reason_chip="1", reason_lang="ar")
		self.assertEqual(self._saved(), "Not enough notice")

	def test_free_text_is_saved_as_typed_and_joined_after_the_chip(self):
		self._act(reason_text="Back on Monday", reason_lang="en")
		self.assertEqual(self._saved(), "Back on Monday")

		self._act(reason_chip="0", reason_text="  Back on Monday ", reason_lang="en")
		self.assertEqual(self._saved(), "Dates clash\nBack on Monday")

	def test_an_unknown_language_is_english(self):
		self._act(reason_chip="0", reason_lang="fr")
		self.assertEqual(self._saved(), "Dates clash")

	def test_no_reason_is_a_400_and_nothing_changes(self):
		result, complete, status = self._act(reason_text="   ", reason_lang="en")

		self.assertEqual(status, 400)
		self.assertEqual(result["error"], "A reason is required for Reject.")
		complete.assert_not_called()
		self.assertEqual(self._saved(), "Original")

	def test_a_missing_field_is_a_logged_400_and_the_task_stays_open(self):
		with patch.object(todo_actions.frappe, "log_error") as log_error:
			result, complete, status = self._act(
				_reason_cfg(reasonField="no_such_field"), reason_chip="0", reason_lang="en"
			)

		self.assertEqual(status, 400)
		self.assertIn("no_such_field", result["error"])
		log_error.assert_called_once()
		complete.assert_not_called()

	def test_no_write_permission_is_a_403_and_nothing_is_written(self):
		_result, complete, status = self._act(user="Guest", reason_chip="0", reason_lang="en")

		self.assertEqual(status, 403)
		complete.assert_not_called()
		self.assertEqual(self._saved(), "Original")

	def test_a_legacy_post_with_a_comment_only_works_as_before(self):
		result, complete, status = self._act(comment="Looks wrong")

		self.assertIsNone(status)
		self.assertEqual(self._comment(complete), "Looks wrong")
		self.assertEqual(result["reason_saved"], {"en": "", "ar": ""})
		self.assertEqual(self._saved(), "Original")

	def test_an_action_without_a_reason_ignores_the_panel_fields(self):
		self._act({"notifyActions": "{}"}, reason_chip="0", reason_lang="en")
		self.assertEqual(self._saved(), "Original")


def _reason_card(**extra):
	ctx = _card_ctx(**extra)
	reject = next(a for a in ctx["actions"] if a["key"] == "reject")
	reject.update(
		reason=True,
		reason_question={"en": "Reason for Reject", "ar": "سبب رفض"},
		chips=[
			{"en": "Dates clash", "ar": "تعارض التواريخ"},
			{"en": "Not enough notice", "ar": "إشعار قصير"},
		],
	)
	return ctx


class TestReasonPanel(FrappeTestCase):
	def setUp(self):
		clear_cache()

	def test_the_reason_panel_passes_the_validator_with_and_without_status(self):
		status = "https://erp.example.com/api/method/one_bpmn.api.todo_actions.get_amp_task_status?status_token=abc"
		_validate_amp4email(render_layout_amp(_reason_card(status_url=status)), "reason_status")
		_validate_amp4email(render_layout_amp(_reason_card()), "reason_plain")

	def test_the_action_opens_a_panel_that_posts_chip_text_and_language(self):
		html = render_layout_amp(_reason_card())

		self.assertIn("on=\"tap:AMP.setState({ui: {open: 'reject', armed: ''}})\">Reject</button>", html)
		self.assertNotIn("ui.armed != 'reject'", html)
		self.assertIn("hidden [hidden]=\"ui.open != 'reject'\"", html)
		self.assertIn('<input type="hidden" name="token" value="tok-r">', html)
		self.assertIn('<input type="hidden" name="reason_lang" value="ar" [value]="ui.lang">', html)
		self.assertIn('<amp-selector name="reason_chip"', html)
		self.assertIn('<span class="chip" option="0">تعارض التواريخ</span>', html)
		self.assertIn('<textarea name="reason_text"', html)
		self.assertIn("Pick a reason or write one.", html)
		self.assertIn("اختر سبباً أو اكتب واحداً.", html)
		self.assertIn('[text]="ui.result.reason_saved.en || \'\'"', html)
		self.assertIn("result: event.response.message}})", html)
		self.assertIn('custom-element="amp-selector"', html)

	def test_the_html_part_has_no_panel(self):
		self.assertNotIn("reason_chip", render_layout_html(_reason_card()))

	def test_the_card_carries_each_actions_reason_settings(self):
		task_cfg = {
			"taskActions": '[{"action":"Reject"},{"action":"Sign","requireDigitalSignature":"true"}]',
			"notifyActions": json.dumps(
				{"Reject": {"reason": True, "chips": CHIPS}, "Sign": {"reason": True, "chips": CHIPS}}
			),
		}
		instance = frappe._dict(name="INST-R", context_doctype="", context_docname="")
		with (
			patch.object(composer, "_action_states", return_value={}),
			patch.object(composer, "_arabic", side_effect=lambda text: f"ar:{text}"),
		):
			reject, sign = composer._build_layout_actions(
				instance, "a@x.com", "t", "review", task_cfg, 72, ""
			)

		self.assertTrue(reject["reason"])
		self.assertEqual(reject["chips"][1], {"en": "Not enough notice", "ar": "Not enough notice"})
		self.assertEqual(reject["reason_question"]["en"], "Reason for Reject")
		self.assertFalse(sign["reason"])
