"""Tests for the layout email shell: render_layout_amp and render_layout_html.

Run with: bench run-tests --app one_bpmn --module one_bpmn.tests.test_layout_renderer
"""

from __future__ import annotations

import re
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase
from frappe.translate import clear_cache

from one_bpmn.email_builder import renderer
from one_bpmn.email_builder.renderer import render_layout_amp, render_layout_html
from one_bpmn.tests.test_amp_validation import _validate_amp4email

TEST_LAYOUT = {"decision_card": "one_bpmn/tests/fixtures/layouts/test_layout.html"}
STATUS_URL = (
	"https://erp.example.com/api/method/one_bpmn.api.todo_actions.get_amp_task_status?status_token=abc"
)


def _ctx(**extra):
	return {
		"layout": "decision_card",
		"subject": "Leave request",
		"kick": {"en": "Leave Application · Final approval", "ar": "طلب إجازة · الموافقة النهائية"},
		"question": {"en": "Approve 3 days for Fatima?", "ar": "هل توافق على 3 أيام لفاطمة؟"},
		"action_label": {"en": "Approve", "ar": "موافقة"},
		"facts": [
			{
				"label": {"en": f"Fact {i}", "ar": f"حقيقة {i}"},
				"value": {"en": f"Value {i}", "ar": f"قيمة {i}"},
			}
			for i in range(1, 8)
		],
		"details": [
			{"label": {"en": "Reason", "ar": "السبب"}, "value": {"en": "Family travel", "ar": "سفر عائلي"}}
		],
		"attachments": [{"name": "Flight booking.pdf", "url": "https://erp.example.com/file/abc"}],
		"open_link": "https://erp.example.com/app/leave-application/LA-0001",
		**extra,
	}


class TestLayoutRenderer(FrappeTestCase):
	def setUp(self):
		clear_cache()
		self.patcher = patch.dict(renderer.LAYOUT_TEMPLATES, TEST_LAYOUT)
		self.patcher.start()

	def tearDown(self):
		self.patcher.stop()

	def test_amp_with_status_passes_the_validator(self):
		_validate_amp4email(render_layout_amp(_ctx(status_url=STATUS_URL)), "layout_status")

	def test_amp_without_status_passes_the_validator(self):
		html = render_layout_amp(_ctx())
		self.assertNotIn("<amp-list", html)
		_validate_amp4email(html, "layout_plain")

	def test_amp_opens_in_english_and_carries_the_arabic(self):
		html = render_layout_amp(_ctx(status_url=STATUS_URL))
		self.assertIn('<div lang="en" dir="ltr" [hidden]="ui.lang != \'en\'">', html)
		self.assertIn('<div lang="ar" dir="rtl" hidden [hidden]="ui.lang != \'ar\'">', html)
		self.assertIn('{"lang": "en"}', html)
		self.assertIn("on=\"tap:AMP.setState({ui: {lang: 'ar'}})\"", html)
		for arabic in ("التفاصيل", "فتح في ERPNext", "محتوى هذه الرسالة سري", "هل توافق على 3 أيام لفاطمة؟"):
			self.assertIn(arabic, html)

	def test_amp_design_rules(self):
		html = render_layout_amp(_ctx())
		css = re.search(r"<style amp-custom>(.*?)</style>", html, re.DOTALL).group(1)
		self.assertIn("font-family:Arial, Helvetica, sans-serif", css)
		for banned in ("@font-face", "@import", "!important", "<link"):
			self.assertNotIn(banned, html)
		self.assertRegex(html, r'<amp-img src="https://[^"]+" alt="ONE Facilities Management" width="120"')
		self.assertIn("max-width:640px", css)
		self.assertIn("min-height:54px", css)

	def test_footer_is_shown_in_full_in_both_languages(self):
		html = render_layout_amp(_ctx())
		self.assertEqual(html.count("Open in ERPNext"), 1)
		self.assertIn("The content of this email is confidential", html)
		self.assertIn("9th Floor, Humoud Tower", html)
		self.assertIn("support@one-fm.com", html)
		self.assertNotIn("legal", html)

	def test_facts_stop_at_six_and_details_fold_with_attachments(self):
		html = render_layout_amp(_ctx())
		self.assertIn("Fact 6", html)
		self.assertNotIn("Fact 7", html)
		accordion = re.search(r"<amp-accordion.*?</amp-accordion>", html, re.DOTALL).group(0)
		self.assertIn("Family travel", accordion)
		self.assertIn('href="https://erp.example.com/file/abc"', accordion)

	def test_status_drives_the_receipt_hiding_and_buttons(self):
		html = render_layout_amp(_ctx(status_url=STATUS_URL))
		template = re.search(r'<template type="amp-mustache">(.*?)</template>', html, re.DOTALL).group(1)
		self.assertIn('class="receipt st-{{workflow_state_style}}"', template)
		self.assertIn("By {{completed_by}}", template)
		self.assertIn("Now with {{assigned_to}}", template)
		hidden_part = template.split("{{^is_completed}}{{^is_reassigned}}", 1)[1].split(
			"{{/is_reassigned}}", 1
		)[0]
		self.assertIn("Approve 3 days for Fatima?", hidden_part)
		self.assertIn("Fact 1", hidden_part)
		waiting = template.split("{{#is_waiting}}", 1)[1].split("{{/is_waiting}}", 1)[0]
		self.assertIn('name="token"', waiting)
		expired = template.split("{{#is_expired}}", 1)[1].split("{{/is_expired}}", 1)[0]
		self.assertIn("These buttons have expired", expired)
		self.assertIn('href="https://erp.example.com/app/leave-application/LA-0001"', expired)
		self.assertIn(
			'<div fallback><a class="btn" href="https://erp.example.com/app/leave-application/LA-0001"', html
		)

	def test_text_is_escaped_and_cannot_open_a_mustache_tag(self):
		ctx = _ctx(status_url=STATUS_URL)
		ctx["question"] = {"en": "<b>Pay</b> {{ doc.secret }}", "ar": "x"}
		html = render_layout_amp(ctx)
		self.assertIn("&lt;b&gt;Pay&lt;/b&gt;", html)
		self.assertNotIn("{{ doc.secret }}", html)
		self.assertIn("{\u200b{ doc.secret }\u200b}", html)

	def test_html_part_is_a_fragment_english_then_arabic(self):
		html = render_layout_html(_ctx())
		for tag in ("<html", "<head", "<body", "<amp-img", "<amp-", "[hidden]"):
			self.assertNotIn(tag, html)
		self.assertLess(html.index('lang="en"'), html.index('lang="ar"'))
		self.assertIn("Family travel", html)
		self.assertIn("Open in ERPNext", html)
		self.assertIn("فتح في ERPNext", html)
		self.assertIn("محتوى هذه الرسالة سري", html)
		self.assertNotIn("The content of this email is confidential", html)
		self.assertNotIn("9th Floor", html)

	def test_unknown_layout_raises_before_any_template_is_read(self):
		for layout in ("../../../etc/passwd", "decision_card.html", "", None):
			with self.subTest(layout=layout), patch.object(renderer, "_get_template") as get_template:
				with self.assertRaises(ValueError):
					render_layout_amp(_ctx(layout=layout))
				with self.assertRaises(ValueError):
					render_layout_html(_ctx(layout=layout))
				get_template.assert_not_called()

	def test_list_placeholder_is_the_tallest_english_variant(self):
		html = render_layout_amp(_ctx(status_url=STATUS_URL))
		placeholder = html.split('<div placeholder class="ph">', 1)[1].split("<div fallback>", 1)[0]
		self.assertNotIn("{{", placeholder)
		self.assertIn('name="token"', placeholder)
		self.assertIn("These buttons have expired", placeholder)
		self.assertIn("Approve 3 days for Fatima?", placeholder)
		self.assertNotIn("هل توافق", placeholder)
