"""Tests for the Decision card email: layout switch, actions and their states, tokens, rendering.

Run with: bench run-tests --app one_bpmn --module one_bpmn.tests.test_decision_card
"""

from __future__ import annotations

import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.translate import clear_cache

from one_bpmn.api import todo_actions
from one_bpmn.email_builder import composer
from one_bpmn.email_builder.renderer import render_layout_amp, render_layout_html
from one_bpmn.tests.test_amp_validation import _validate_amp4email
from one_bpmn.utils.token import verify_action_token

APPROVED, REJECTED = "Test Card Approved", "Test Card Rejected"
MAP_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
	xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="Defs">
	<bpmn:process id="leave" isExecutable="true">
		<bpmn:userTask id="review" name="Review Leave" />
		<bpmn:sequenceFlow id="f1" sourceRef="review" targetRef="gw" />
		<bpmn:exclusiveGateway id="gw" default="f_return" />
		<bpmn:sequenceFlow id="f_approve" sourceRef="gw" targetRef="set_approved">
			<bpmn:conditionExpression>action == "Approve"</bpmn:conditionExpression>
		</bpmn:sequenceFlow>
		<bpmn:sequenceFlow id="f_reject" sourceRef="gw" targetRef="note">
			<bpmn:conditionExpression>action == 'Reject'</bpmn:conditionExpression>
		</bpmn:sequenceFlow>
		<bpmn:sequenceFlow id="f_return" sourceRef="gw" targetRef="end" />
		<bpmn:scriptTask id="note" name="Log" />
		<bpmn:sequenceFlow id="f2" sourceRef="note" targetRef="set_rejected" />
		<bpmn:serviceTask id="set_approved" spiffworkflow:serviceType="apply_workflow" spiffworkflow:workflowState="{APPROVED}" />
		<bpmn:serviceTask id="set_rejected" spiffworkflow:serviceType="apply_workflow" spiffworkflow:workflowState="{REJECTED}" />
		<bpmn:endEvent id="end" />
	</bpmn:process>
</bpmn:definitions>"""

TASK_ACTIONS = '[{"action":"Approve"},{"action":"Reject","confirmTransition":"true"},{"action":"Return"},{"action":"Sign Off","requireDigitalSignature":"true"}]'


def _instance():
	return frappe._dict(
		name="TEST-CARD-INST", doctype="BPMN Process Instance", context_doctype="", context_docname=""
	)


def _map_reads():
	real = frappe.db.get_value

	def get_value(*args, **kwargs):
		doctype, fieldname = args[0], args[2] if len(args) > 2 else kwargs.get("fieldname")
		if doctype == "BPMN Process Instance" and fieldname == "process_model":
			return "Test Card Map"
		if doctype == "BPMN Process Model" and fieldname == "bpmn_xml":
			return MAP_XML
		return real(*args, **kwargs)

	return patch.object(frappe.db, "get_value", side_effect=get_value)


def _no_machine_translation():
	return patch("one_bpmn.utils.translation.translate_cached", side_effect=lambda text: f"ar:{text}")


class TestDecisionCardActions(FrappeTestCase):
	def setUp(self):
		clear_cache()
		for state, style in ((APPROVED, "Success"), (REJECTED, "Danger")):
			if not frappe.db.exists("Workflow State", state):
				frappe.get_doc(
					{"doctype": "Workflow State", "workflow_state_name": state, "style": style}
				).insert()

	def test_action_states_follow_each_branch_to_its_apply_workflow_task(self):
		with _map_reads():
			states = composer._action_states(_instance(), "review", ["Approve", "Reject", "Return"])
		self.assertEqual(states, {"Approve": (APPROVED, "Success"), "Reject": (REJECTED, "Danger")})

	def test_actions_carry_primary_confirm_sign_state_and_tokens(self):
		cfg = {"taskActions": TASK_ACTIONS, "notifyActions": '{"Reject": {"primary": true}}'}
		with _map_reads(), _no_machine_translation():
			actions = composer._build_layout_actions(
				_instance(), "a@x.com", "task-1", "review", cfg, 24, "https://erp/app/x/1"
			)
		by_name = {a["label"]["en"]: a for a in actions}
		self.assertEqual([a["label"]["en"] for a in actions], ["Approve", "Reject", "Return", "Sign Off"])
		self.assertTrue(by_name["Reject"]["primary"])
		self.assertFalse(by_name["Approve"]["primary"])
		self.assertTrue(by_name["Reject"]["confirm"])
		self.assertEqual((by_name["Approve"]["state"], by_name["Approve"]["style"]), (APPROVED, "Success"))
		self.assertEqual(by_name["Return"]["style"], "")
		self.assertEqual(by_name["Sign Off"]["token"], "")
		self.assertEqual(by_name["Sign Off"]["url"], "https://erp/app/x/1")
		self.assertEqual(by_name["Return"]["label"]["ar"], frappe._("Return", lang="ar"))
		payload = verify_action_token(by_name["Approve"]["token"])
		self.assertEqual((payload["action"], payload["user"]), ("Approve", "a@x.com"))
		self.assertAlmostEqual(payload["expires"] - time.time(), 24 * 3600, delta=60)

	def test_arabic_label_falls_back_to_machine_translation_then_english(self):
		with _no_machine_translation():
			self.assertEqual(composer._arabic("Zq Custom Step"), "ar:Zq Custom Step")
		from one_bpmn.utils.translation import TranslationError

		with patch("one_bpmn.utils.translation.translate_cached", side_effect=TranslationError("down")):
			self.assertEqual(composer._arabic("Zq Custom Step"), "Zq Custom Step")

	def test_first_action_is_primary_by_default(self):
		with _map_reads(), _no_machine_translation():
			actions = composer._build_layout_actions(
				_instance(), "a@x.com", "t", "review", {"taskActions": TASK_ACTIONS}, 72, ""
			)
		self.assertEqual([a["primary"] for a in actions], [True, False, False, False])

	def test_token_hours_default_to_72_outside_1_to_720(self):
		self.assertEqual(composer._token_hours("24"), 24)
		for raw in ("", None, "abc", "0", "721", "-5"):
			self.assertEqual(composer._token_hours(raw), 72, raw)

	def test_card_is_sent_for_card_or_an_empty_task_only(self):
		self.assertTrue(composer._sends_decision_card({"notifyLayout": "card"}))
		self.assertTrue(composer._sends_decision_card({}))
		self.assertFalse(composer._sends_decision_card({"notifyLayout": "html"}))
		self.assertFalse(composer._sends_decision_card({"notifyAssigneeBody": "PHA+SGk8L3A+"}))
		self.assertFalse(composer._sends_decision_card({"notifyAssigneeTemplate": "Leave Approval"}))

	def test_html_layout_keeps_todays_path(self):
		cfg = {
			"notifyAssignee": "true",
			"notifyLayout": "html",
			"notifyAssigneeSubject": "Hi",
			"notifyAssigneeBody": "",
		}
		with (
			patch.object(composer, "_send_decision_card") as card,
			patch.object(composer, "_send_email") as send,
		):
			composer.compose_and_send_task_email(_instance(), "a@x.com", "Review", "t", "review", cfg)
		card.assert_not_called()
		send.assert_called_once()

	def test_card_layout_sends_the_card(self):
		with (
			patch.object(composer, "_send_decision_card") as card,
			patch.object(composer, "_send_email") as send,
		):
			composer.compose_and_send_task_email(
				_instance(), "a@x.com", "Review", "t", "review", {"notifyAssignee": "true"}
			)
		card.assert_called_once()
		send.assert_not_called()

	def test_receipt_names_the_state_in_both_languages(self):
		with patch.object(todo_actions, "_get_workflow_state_and_style", return_value=(APPROVED, "Success")):
			receipt = todo_actions._receipt("INST", "Leave Application")
		self.assertEqual(receipt["state_style"], "Success")
		self.assertEqual(receipt["state_label"]["en"], APPROVED)
		self.assertEqual(receipt["receipt"]["en"], f"Leave Application is now {APPROVED}")
		self.assertTrue(receipt["receipt"]["ar"])
		self.assertTrue(receipt["completed_at"])


def _card_ctx(**extra):
	actions = [
		{
			"key": "approve",
			"label": {"en": "Approve", "ar": "موافقة"},
			"primary": True,
			"confirm": False,
			"sign": False,
			"state": APPROVED,
			"style": "Success",
			"url": "",
			"token": "tok-a",
		},
		{
			"key": "reject",
			"label": {"en": "Reject", "ar": "رفض"},
			"primary": False,
			"confirm": True,
			"sign": False,
			"state": REJECTED,
			"style": "Danger",
			"url": "",
			"token": "tok-r",
		},
		{
			"key": "sign_off",
			"label": {"en": "Sign Off", "ar": "توقيع"},
			"primary": False,
			"confirm": False,
			"sign": True,
			"state": "",
			"style": "",
			"url": "https://erp.example.com/app/leave-application/LA-1",
			"token": "",
		},
	]
	return {
		"layout": "decision_card",
		"kick": {"en": "Leave Application · Review", "ar": "طلب إجازة · مراجعة"},
		"question": {"en": "Approve 3 days for Fatima?", "ar": "هل توافق على 3 أيام لفاطمة؟"},
		"facts": [{"label": {"en": "Employee", "ar": "الموظف"}, "value": {"en": "Fatima", "ar": "فاطمة"}}],
		"details": [],
		"attachments": [],
		"open_link": "https://erp.example.com/app/leave-application/LA-1",
		"action_endpoint": "https://erp.example.com/api/method/one_bpmn.api.todo_actions.handle_amp_action",
		"actions": actions,
		**extra,
	}


class TestDecisionCardRender(FrappeTestCase):
	def setUp(self):
		clear_cache()

	def test_amp_card_passes_the_validator_with_and_without_status(self):
		status = "https://erp.example.com/api/method/one_bpmn.api.todo_actions.get_amp_task_status?status_token=abc"
		_validate_amp4email(render_layout_amp(_card_ctx(status_url=status)), "card_status")
		_validate_amp4email(render_layout_amp(_card_ctx()), "card_plain")

	def test_amp_card_blocks_buttons_and_confirm(self):
		html = render_layout_amp(_card_ctx())
		self.assertLess(html.index("Leave Application · Review"), html.index("Approve 3 days for Fatima?"))
		self.assertLess(html.index("Approve 3 days for Fatima?"), html.index('value="tok-a"'))
		self.assertIn('class="btn Success">Approve</button>', html)
		self.assertIn(
			'class="btn subtle" on="tap:AMP.setState({ui: {armed: \'reject\'}})">Reject</button>', html
		)
		self.assertIn("hidden [hidden]=\"ui.armed != 'reject'\"", html)
		self.assertIn('value="tok-r" class="btn Danger">Tap again to confirm</button>', html)
		self.assertIn('<a class="btn subtle" href="https://erp.example.com/app/leave-application/LA-1"', html)
		self.assertIn("submit-success:AMP.setState({ui: {done: true, result: event.response}})", html)
		self.assertIn("Nothing changed in ERPNext. Try again.", html)
		for arabic in ("اضغط مرة أخرى للتأكيد", "إلغاء", "لم يتم الحفظ."):
			self.assertIn(arabic, html)

	def test_html_part_links_every_button_to_the_document(self):
		html = render_layout_html(_card_ctx())
		self.assertNotIn("<button", html)
		self.assertNotIn("<form", html)
		self.assertEqual(
			html.count('href="https://erp.example.com/app/leave-application/LA-1" target="_blank">'), 6 + 2
		)
		self.assertLess(html.index("Approve 3 days for Fatima?"), html.index("هل توافق على 3 أيام لفاطمة؟"))
