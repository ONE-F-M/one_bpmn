# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Step by step layout: the Decision card's content and actions on three screens."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.translate import clear_cache

from one_bpmn.email_builder import composer
from one_bpmn.email_builder.renderer import render_layout_amp, render_layout_html
from one_bpmn.tests.test_amp_validation import _validate_amp4email
from one_bpmn.tests.test_decision_card import _card_ctx

STATUS_URL = (
	"https://erp.example.com/api/method/one_bpmn.api.todo_actions.get_amp_task_status?status_token=abc"
)


def _steps_ctx(**extra):
	return _card_ctx(
		layout="steps",
		details=[
			{"label": {"en": "Reason", "ar": "السبب"}, "value": {"en": "Family travel", "ar": "سفر عائلي"}}
		],
		attachments=[{"name": "Booking.pdf", "url": "https://erp.example.com/file/abc"}],
		**extra,
	)


class TestStepsLayout(FrappeTestCase):
	def setUp(self):
		clear_cache()

	def test_steps_is_sent_with_the_card_context_and_actions(self):
		self.assertTrue(composer._sends_decision_card({"notifyLayout": "steps", "notifyAssigneeBody": "x"}))
		self.assertFalse(composer._sends_decision_card({"notifyLayout": "html"}))

		instance = frappe._dict(
			name="INST-S", doctype="BPMN Process Instance", context_doctype="", context_docname=""
		)
		with (
			patch.object(composer, "_build_layout_actions", return_value=[]),
			patch("one_bpmn.email_builder.fields.build_kick", return_value={"en": "k", "ar": "k"}),
		):
			ctx = composer._build_layout_context(
				instance, "a@x.com", "Review", "t", "review", {"notifyLayout": "steps"}
			)
		self.assertEqual(ctx["layout"], "steps")

	def test_amp_passes_the_validator_with_and_without_status(self):
		_validate_amp4email(render_layout_amp(_steps_ctx(status_url=STATUS_URL)), "steps_status")
		_validate_amp4email(render_layout_amp(_steps_ctx()), "steps_plain")

	def test_three_screens_in_order_with_only_the_first_shown(self):
		english = render_layout_amp(_steps_ctx()).split('lang="ar"')[0]

		order = [
			english.index('class="prog"'),
			english.index('<span class="step-t">The request'),
			english.index("Approve 3 days for Fatima?"),
			english.index('class="facts"'),
			english.index('<span class="step-t">What it changes'),
			english.index("Family travel"),
			english.index("Booking.pdf"),
			english.index('<span class="step-t">Your call'),
			english.index('class="acts"'),
		]
		self.assertEqual(order, sorted(order))
		self.assertEqual(english.count("Approve 3 days for Fatima?"), 2)
		self.assertIn('<div class="screen" [hidden]="(ui.step || 1) != 1">', english)
		self.assertIn('<div class="screen" hidden [hidden]="(ui.step || 1) != 2">', english)
		self.assertIn('<div class="screen" hidden [hidden]="(ui.step || 1) != 3">', english)
		self.assertNotIn("<amp-accordion", english)

	def test_next_and_back_change_the_step(self):
		html = render_layout_amp(_steps_ctx())
		self.assertIn('on="tap:AMP.setState({ui: {step: 2}})">Next</button>', html)
		self.assertIn('on="tap:AMP.setState({ui: {step: 1}})">Back</button>', html)
		self.assertIn("[class]=\"(ui.step || 1) >= 3 ? 'seg on' : 'seg'\"", html)
		for arabic in ("التالي", "السابق", "الخطوة 2 من 3", "قرارك"):
			self.assertIn(arabic, html)

	def test_the_error_banner_sits_above_the_buttons(self):
		steps = render_layout_amp(_steps_ctx())
		self.assertLess(steps.index("<div submit-error>"), steps.index('<div class="acts">'))

		card = render_layout_amp(_card_ctx())
		self.assertLess(card.index('<div class="acts">'), card.index("<div submit-error>"))

	def test_completed_or_reassigned_on_open_skips_the_screens(self):
		html = render_layout_amp(_steps_ctx(status_url=STATUS_URL))
		template = html.split("<template")[1]
		self.assertLess(template.index("{{^is_completed}}{{^is_reassigned}}"), template.index('class="prog"'))
		self.assertIn("{{#is_expired}}", template)

	def test_html_part_is_one_static_page_with_links(self):
		html = render_layout_html(_steps_ctx())
		self.assertNotIn("<button", html)
		self.assertNotIn("[hidden]", html)
		self.assertNotIn(" hidden ", html)
		english = html.split('lang="ar"')[0]
		self.assertLess(english.index('<span class="step-t">The request'), english.index("What it changes"))
		self.assertLess(english.index('<span class="step-t">What it changes'), english.index("Your call"))
		self.assertIn(
			'<a class="btn Success" href="https://erp.example.com/app/leave-application/LA-1"', english
		)
