# Copyright (c) 2026, one-fm and contributors
# WI-001751: an assertion with no value must be refused, and refused legibly.
#
# The case editor let an llm_judge row be saved with a blank Rubric.
# _set_assertions dropped the empty value, so doc.save() raised a bare
# "MandatoryError: [AI Eval Case, <hash>]: value" — which named the doctype and
# the field but neither the assertion nor what belonged in it, and reached the UI
# as a 417 with a stack trace and no message.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_eval_case, make_eval_suite
from one_bpmn.api.eval_api import create_eval_case, update_eval_case

test_ignore = ["AI Eval Suite"]


class TestEvalAssertionValidation(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		# process_model=None: create_eval_case copies the suite's process_model
		# onto the case and inserts WITHOUT ignore_links, so the factory's
		# placeholder "_Test BPMN Model" would fail link validation.
		self.suite = make_eval_suite(process_model=None).name

	def _create(self, assertions):
		return create_eval_case(
			suite=self.suite,
			title="_Assertion probe " + frappe.generate_hash(length=6),
			input_user_prompt="say something",
			assertions=assertions,
		)

	def test_blank_llm_judge_rubric_is_refused_with_a_useful_message(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._create([{
				"assertion_type": "llm_judge",
				"value": "",
				"judge_provider": "Claude",
				"pass_threshold": 4,
			}])
		msg = str(ctx.exception)
		self.assertIn("llm_judge", msg)
		self.assertIn("rubric", msg.lower())
		# The old failure said only "MandatoryError: value".
		self.assertNotIn("MandatoryError", msg)

	def test_message_names_which_assertion(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._create([
				{"assertion_type": "contains", "value": "ok"},
				{"assertion_type": "regex", "value": "   "},
			])
		self.assertIn("Assertion 2", str(ctx.exception))

	def test_each_type_says_what_its_value_is(self):
		wanted = {
			"contains": "substring",
			"regex": "pattern",
			"equals": "exact text",
			"schema_valid": "JSON Schema",
		}
		for kind, phrase in wanted.items():
			with self.assertRaises(frappe.ValidationError) as ctx:
				self._create([{"assertion_type": kind, "value": ""}])
			self.assertIn(phrase, str(ctx.exception), f"{kind} should mention {phrase}")

	def test_a_complete_assertion_still_saves(self):
		name = self._create([{"assertion_type": "contains", "value": "approved"}])
		case = frappe.get_doc("AI Eval Case", name)
		self.assertEqual(len(case.assertions), 1)
		self.assertEqual(case.assertions[0].value, "approved")

	def test_no_assertions_at_all_is_still_allowed(self):
		"""A case with none passes trivially and is surfaced as such in the UI —
		that is a warning, not a reason to block authoring."""
		name = self._create([])
		self.assertEqual(len(frappe.get_doc("AI Eval Case", name).assertions), 0)

	def test_editing_a_case_blank_is_refused_too(self):
		case = make_eval_case(
			suite=self.suite, assertions=[{"assertion_type": "contains", "value": "keep"}]
		)
		with self.assertRaises(frappe.ValidationError):
			update_eval_case(name=case.name, assertions=[{"assertion_type": "contains", "value": ""}])
		# The refusal must not have wiped what was already there.
		case.reload()
		self.assertEqual(case.assertions[0].value, "keep")
