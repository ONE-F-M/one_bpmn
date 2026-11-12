# Copyright (c) 2026, one-fm and contributors
# The helpers shared by the API modules, and the permission gates that now use frappe.only_for.

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import a2a_admin, clarifications
from one_bpmn.api.common import distinct, parse_json_or_passthrough, shape_reply

PLAIN_USER = "zz-api-common@example.com"
EXTRACT_JSON = "one_bpmn.ai_agent_registry.definitions.shared.helpers.extract_json"


class TestDistinct(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		for status in ("Open", "Closed"):
			frappe.get_doc({"doctype": "ToDo", "description": "zz distinct", "status": status}).insert()

	def test_returns_the_values_present_sorted_ascending(self):
		values = distinct("ToDo", "status")
		self.assertIn("Open", values)
		self.assertIn("Closed", values)
		self.assertEqual(values, sorted(values))

	def test_unset_values_are_left_out(self):
		values = distinct("ToDo", "reference_type")
		self.assertTrue(all(values))

	def test_the_limit_caps_the_result(self):
		self.assertEqual(distinct("ToDo", "status", limit=1), distinct("ToDo", "status")[:1])


class TestParseJsonOrPassthrough(FrappeTestCase):
	def test_empty_values_give_the_fallback(self):
		self.assertIsNone(parse_json_or_passthrough(None))
		self.assertEqual(parse_json_or_passthrough("", {}), {})

	def test_dicts_and_lists_pass_through_unchanged(self):
		payload = {"a": 1}
		self.assertIs(parse_json_or_passthrough(payload), payload)
		items = [1, 2]
		self.assertIs(parse_json_or_passthrough(items, {}), items)

	def test_json_text_is_parsed(self):
		self.assertEqual(parse_json_or_passthrough('{"a": [1, 2]}'), {"a": [1, 2]})

	def test_invalid_json_gives_the_fallback(self):
		self.assertEqual(parse_json_or_passthrough("{not json", {"x": 1}), {"x": 1})
		self.assertIsNone(parse_json_or_passthrough("{not json"))


class TestShapeReply(FrappeTestCase):
	TRIGGERS = ("intent", "payload")
	COPIES = ("intent", "payload", "options")

	def test_a_reply_that_already_has_a_trigger_key_is_returned_as_is(self):
		result = {"response": "text", "intent": "CREATE"}
		with patch(EXTRACT_JSON) as extract:
			self.assertIs(shape_reply(result, self.TRIGGERS, self.COPIES), result)
		extract.assert_not_called()

	def test_the_contract_is_lifted_out_of_the_text(self):
		parsed = {"intent": "MODIFY", "response": " short ", "payload": "p", "options": [], "ignored": 1}
		result = {"response": "raw text", "keep": 1}
		with patch(EXTRACT_JSON, return_value=parsed):
			shaped = shape_reply(result, self.TRIGGERS, self.COPIES)

		self.assertEqual(shaped, {"response": "short", "keep": 1, "intent": "MODIFY", "payload": "p"})
		self.assertEqual(result, {"response": "raw text", "keep": 1}, "the input is not mutated")

	def test_a_blank_parsed_response_keeps_the_raw_text(self):
		with patch(EXTRACT_JSON, return_value={"intent": "MODIFY", "response": ""}):
			shaped = shape_reply({"response": "raw text"}, self.TRIGGERS, self.COPIES)
		self.assertEqual(shaped["response"], "raw text")

	def test_text_without_a_trigger_key_is_left_alone(self):
		result = {"response": "just chat"}
		with patch(EXTRACT_JSON, return_value={"response": "no trigger"}):
			self.assertIs(shape_reply(result, self.TRIGGERS, self.COPIES), result)
		with patch(EXTRACT_JSON, return_value=None):
			self.assertIs(shape_reply(result, self.TRIGGERS, self.COPIES), result)

	def test_a_non_text_response_is_left_alone(self):
		result = {"response": {"not": "text"}}
		with patch(EXTRACT_JSON, return_value=None) as extract:
			self.assertIs(shape_reply(result, self.TRIGGERS, self.COPIES), result)
		extract.assert_called_once_with("")


class TestApiPermissions(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("User", PLAIN_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": PLAIN_USER,
					"first_name": "ZZ API Common",
					"send_welcome_email": 0,
					"enabled": 1,
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_plain_user_is_refused_the_clarification_options(self):
		with self.set_user(PLAIN_USER), self.assertRaises(frappe.PermissionError):
			clarifications.clarification_filter_options()

	def test_a_plain_user_is_refused_an_a2a_admin_endpoint(self):
		with self.set_user(PLAIN_USER), self.assertRaises(frappe.PermissionError):
			a2a_admin.list_clients()

	def test_a_plain_user_gets_no_a2a_admin_permissions(self):
		with self.set_user(PLAIN_USER):
			self.assertEqual(a2a_admin.get_permissions(), {"administer": False, "read": False})

	def test_a_system_manager_gets_the_clarification_options(self):
		self.assertEqual(
			set(clarifications.clarification_filter_options()),
			{"agents", "people", "doctypes", "statuses"},
		)
		self.assertTrue(a2a_admin.get_permissions()["administer"])
