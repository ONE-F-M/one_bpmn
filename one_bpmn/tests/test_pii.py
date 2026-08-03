# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Tests for PII input screening (WI-001644).

Two things have to hold for this control to be worth having:

  1. It catches the values it claims to catch, and it puts them back at the
     tool boundary so lookups still resolve.
  2. It does NOT mangle ordinary text. A screen with a high false-positive
     rate gets disabled in week two, at which point it protects nothing —
     so roughly half of these tests are negative cases.
"""

import unittest

import frappe

from one_bpmn.security import pii


# A Civil ID that satisfies the weighted checksum, built for this test.
def _valid_civil_id() -> str:
	base = "28901011234"
	weights = (2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
	total = sum(int(base[i]) * weights[i] for i in range(11))
	check = 11 - (total % 11)
	if check > 9:  # not a usable ID; nudge the serial and retry
		base = "28901011235"
		total = sum(int(base[i]) * weights[i] for i in range(11))
		check = 11 - (total % 11)
	return base + str(check)


CIVIL_ID = _valid_civil_id()
CARD = "4111111111111111"  # Luhn-valid test PAN


class TestPIIDetection(unittest.TestCase):
	"""What gets caught."""

	def test_kuwait_civil_id_is_tokenised(self):
		result = pii.redact(f"Please find the employee with civil id {CIVIL_ID}")
		self.assertNotIn(CIVIL_ID, result.text)
		self.assertIn("[CIVIL_ID_1]", result.text)
		self.assertEqual(result.mapping["[CIVIL_ID_1]"], CIVIL_ID)

	def test_email_is_tokenised(self):
		result = pii.redact("mail it to a.adekunle@one-fm.com please")
		self.assertNotIn("a.adekunle@one-fm.com", result.text)
		self.assertIn("[EMAIL_1]", result.text)

	def test_kuwait_phone_with_country_code(self):
		result = pii.redact("reach me on +965 55123456")
		self.assertIn("[PHONE_1]", result.text)

	def test_bare_phone_needs_a_context_word(self):
		with_context = pii.redact("his mobile is 55123456")
		without_context = pii.redact("invoice total 55123456 fils")
		self.assertIn("[PHONE_1]", with_context.text)
		self.assertNotIn("[PHONE", without_context.text)

	def test_iban_is_tokenised(self):
		result = pii.redact("salary goes to KW81CBKU0000000000001234560101")
		self.assertIn("[IBAN_1]", result.text)

	def test_payment_card_is_tokenised(self):
		result = pii.redact(f"card {CARD} was declined")
		self.assertIn("[CARD_1]", result.text)

	def test_passport_needs_a_context_word(self):
		with_context = pii.redact("passport number A1234567 expires soon")
		without_context = pii.redact("part A1234567 is out of stock")
		self.assertIn("[PASSPORT_1]", with_context.text)
		self.assertNotIn("[PASSPORT", without_context.text)

	def test_repeated_value_gets_one_stable_token(self):
		result = pii.redact(f"{CIVIL_ID} and again {CIVIL_ID}")
		self.assertEqual(result.text.count("[CIVIL_ID_1]"), 2)
		self.assertEqual(len(result.mapping), 1)

	def test_several_types_in_one_message(self):
		result = pii.redact(
			f"employee {CIVIL_ID}, email x@one-fm.com, passport number B7654321"
		)
		self.assertEqual(
			sorted(result.counts), ["CIVIL_ID", "EMAIL", "PASSPORT"]
		)


class TestFalsePositives(unittest.TestCase):
	"""What must survive untouched — the reason this control stays switched on."""

	def test_twelve_digits_failing_the_checksum_is_left_alone(self):
		# An order reference, not a Civil ID. Shape matches; checksum does not.
		text = "reference 100000000000 was posted"
		self.assertEqual(pii.redact(text).text, text)

	def test_long_number_failing_luhn_is_left_alone(self):
		text = "batch 1234567812345678 completed"
		self.assertEqual(pii.redact(text).text, text)

	def test_ordinary_sentence_is_untouched(self):
		text = "Show me all leave applications approved in March 2026."
		self.assertEqual(pii.redact(text).text, text)

	def test_document_names_are_untouched(self):
		text = "open HR-EMP-00123 and PO-2026-00045 for me"
		self.assertEqual(pii.redact(text).text, text)

	def test_empty_and_non_string_input(self):
		self.assertEqual(pii.redact("").text, "")
		self.assertEqual(pii.redact(None).text, "")


class TestRestoration(unittest.TestCase):
	"""Reversibility — the reason tokens are used instead of ``****``."""

	def test_restore_returns_the_original_text(self):
		original = f"look up {CIVIL_ID}"
		result = pii.redact(original)
		self.assertEqual(pii.restore(result.text, result.mapping), original)

	def test_tool_arguments_are_restored_at_any_depth(self):
		result = pii.redact(f"find {CIVIL_ID}")
		handle = pii.begin_turn(result)
		try:
			args = {
				"doctype": "Employee",
				"filters": {"one_fm_civil_id": "[CIVIL_ID_1]"},
				"or_filters": [{"custom_id": "[CIVIL_ID_1]"}],
			}
			restored = pii.restore_arguments(args)
			self.assertEqual(restored["filters"]["one_fm_civil_id"], CIVIL_ID)
			self.assertEqual(restored["or_filters"][0]["custom_id"], CIVIL_ID)
			self.assertEqual(restored["doctype"], "Employee")
		finally:
			pii.end_turn(handle)

	def test_mapping_does_not_leak_past_the_turn(self):
		result = pii.redact(f"find {CIVIL_ID}")
		handle = pii.begin_turn(result)
		pii.end_turn(handle)
		self.assertFalse(pii.current_mapping())
		# With no mapping, a token is left as-is rather than resolved by a
		# stale mapping from someone else's turn.
		self.assertEqual(pii.restore_arguments({"q": "[CIVIL_ID_1]"}), {"q": "[CIVIL_ID_1]"})

	def test_hook_mapping_does_not_create_a_turn(self):
		# A Chat Message saved outside any turn must not strand a mapping in
		# the surrounding context — there would be no end_turn to clear it.
		pii.merge_mapping({"[CIVIL_ID_9]": "289010112345"})
		self.assertFalse(pii.current_mapping())


class TestToolSpecWrapping(unittest.TestCase):
	"""Every tool the system builds is a ToolSpec, so wrapping there covers
	shape tools, pooled tools and Server-Script-built tools alike."""

	def test_tool_receives_the_real_value(self):
		from one_bpmn.agents.llm_provider.base import ToolSpec

		seen = {}

		def lookup(civil_id=None):
			seen["civil_id"] = civil_id
			return "ok"

		spec = ToolSpec(fn=lookup, name="lookup", description="")
		result = pii.redact(f"find {CIVIL_ID}")
		handle = pii.begin_turn(result)
		try:
			spec.fn(civil_id="[CIVIL_ID_1]")
		finally:
			pii.end_turn(handle)
		self.assertEqual(seen["civil_id"], CIVIL_ID)

	def test_human_tools_are_not_wrapped(self):
		from one_bpmn.agents.llm_provider.base import ToolSpec

		def noop():
			return None

		spec = ToolSpec(fn=noop, name="approve", description="", human=True)
		self.assertIs(spec.fn, noop)

	def test_wrapping_is_not_applied_twice(self):
		from one_bpmn.agents.llm_provider.base import ToolSpec

		def noop(**kwargs):
			return None

		first = ToolSpec(fn=noop, name="t", description="")
		second = ToolSpec(fn=first.fn, name="t", description="")
		self.assertIs(second.fn, first.fn)


class TestChatMessageHook(unittest.TestCase):
	"""The stored transcript must not hold raw PII.

	This is load-bearing rather than defensive: every map-driven agent's
	"Save User Message" script re-reads ``Chat Message.text`` and prefers it
	over the payload, so redaction that stops at the payload is undone.
	"""

	def setUp(self):
		self.conversation = frappe.get_doc({
			"doctype": "Chat Conversation",
			"title": "PII screening test",
			"user": frappe.session.user,
		}).insert()

	def tearDown(self):
		frappe.db.rollback()

	def _message(self, text, message_type="User"):
		return frappe.get_doc({
			"doctype": "Chat Message",
			"conversation": self.conversation.name,
			"sender": frappe.session.user,
			"text": text,
			"message_type": message_type,
		}).insert()

	def test_user_message_is_stored_redacted(self):
		doc = self._message(f"my civil id is {CIVIL_ID}")
		stored = frappe.db.get_value("Chat Message", doc.name, "text")
		self.assertNotIn(CIVIL_ID, stored)
		self.assertIn("[CIVIL_ID_1]", stored)

	def test_the_map_reread_now_returns_redacted_text(self):
		doc = self._message(f"my civil id is {CIVIL_ID}")
		# Exactly what "<Agent> – Save User Message" does.
		reread = frappe.get_doc("Chat Message", doc.name).text
		self.assertNotIn(CIVIL_ID, reread)

	def test_bot_messages_are_not_touched(self):
		# Output screening is a separate control; this one must not silently
		# half-apply to the response path.
		doc = self._message(f"the id on file is {CIVIL_ID}", message_type="Bot")
		self.assertIn(CIVIL_ID, frappe.db.get_value("Chat Message", doc.name, "text"))

	def test_token_matches_the_entry_point_token(self):
		# redact() is deterministic, so the hook and screen_input agree — the
		# map's re-read text lines up with the turn's mapping.
		doc = self._message(f"my civil id is {CIVIL_ID}")
		stored = frappe.db.get_value("Chat Message", doc.name, "text")
		self.assertEqual(pii.redact(f"my civil id is {CIVIL_ID}").text, stored)


class TestInvokeAgentEndToEnd(unittest.TestCase):
	"""The whole path: invoke_agent → runner → adapter.

	The adapter is faked so no request leaves the machine, but everything up to
	it is the real code — the real config resolution, the real runner, the real
	persistence. What the fake captures is exactly what would have gone on the
	wire to the model provider.
	"""

	AGENT = "platform_prompt_engineer"  # Live, Direct API, no process map

	def tearDown(self):
		frappe.db.rollback()

	def test_civil_id_never_reaches_the_provider(self):
		from unittest.mock import patch

		from one_bpmn.api import agent_invocation

		captured = {}

		class FakeCompletion:
			text = "acknowledged"

		class FakeAdapter:
			async def complete(self, system=None, user=None, **kwargs):
				captured["system"] = system
				captured["user"] = user
				return FakeCompletion()

		message = f"the employee civil id is {CIVIL_ID}, look them up"
		with patch(
			"one_bpmn.agents.llm_provider.get_llm_adapter_from_settings",
			return_value=FakeAdapter(),
		):
			result = agent_invocation.invoke_agent(self.AGENT, message)

		# 1. The provider saw the token, not the value.
		self.assertNotIn(CIVIL_ID, captured["user"])
		self.assertIn("[CIVIL_ID_1]", captured["user"])

		# 2. The conversation log stored the token, not the value.
		stored = frappe.get_all(
			"Chat Message",
			filters={"conversation": result["conversation"], "message_type": "User"},
			pluck="text",
		)
		self.assertTrue(stored)
		self.assertNotIn(CIVIL_ID, stored[0])

		# 3. The mapping did not survive the turn.
		self.assertFalse(pii.current_mapping())


class TestPerAgentOptOut(unittest.TestCase):
	def test_disabled_agent_is_passed_through(self):
		result = pii.screen_input(f"id {CIVIL_ID}", {"pii_screening": "Disabled"})
		self.assertIn(CIVIL_ID, result.text)
		self.assertFalse(result.enabled)

	def test_default_is_enabled(self):
		# An agent saved before the field existed has no value — screened.
		result = pii.screen_input(f"id {CIVIL_ID}", {"pii_screening": None})
		self.assertNotIn(CIVIL_ID, result.text)

	def test_hook_honours_the_turn_opt_out(self):
		off = pii.screen_input(f"id {CIVIL_ID}", {"pii_screening": "Disabled"})
		handle = pii.begin_turn(off, enabled=off.enabled)
		try:
			doc = frappe._dict(message_type="User", text=f"id {CIVIL_ID}", get=lambda k: None)
			pii.screen_chat_message(doc)
			self.assertIn(CIVIL_ID, doc.text)
		finally:
			pii.end_turn(handle)
