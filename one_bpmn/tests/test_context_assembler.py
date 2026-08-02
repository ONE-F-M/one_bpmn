# Copyright (c) 2026, one-fm and contributors
# Static Context Orchestration in Execution Loops (WI-001639).
#
# The static layer's contract is that it is a pure function of the agent's
# configuration: Instructions -> Examples -> Guard Rails, byte-identical every
# time. These tests pin that contract, plus the rule that an agent with no
# examples and no guard rails produces exactly the prompt it produced before
# this story — so adding the fields changes nothing until they are filled in.
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.context_assembler import (
	EXAMPLES_HEADER,
	GUARDRAILS_HEADER,
	build_dynamic_preamble,
	build_static_context,
	build_static_context_from_config,
)

INSTRUCTIONS = "You are a careful assistant."

EXAMPLES = [
	{"input": "add two numbers", "expected_output": "4", "note": "keep it terse"},
	{"input": "greet the user", "expected_output": "Hello."},
]

GUARDRAILS = [
	{"guardrail": "Keep every file under 300 lines.", "category": "Code Quality"},
	{"guardrail": "No query inside a loop.", "category": "Performance"},
	{"guardrail": "Never echo the whole script back.", "category": "Cost & Tokens"},
]


class TestStaticContextComposition(FrappeTestCase):
	def test_sections_appear_in_fixed_order(self):
		out = build_static_context(INSTRUCTIONS, EXAMPLES, GUARDRAILS)

		self.assertLess(out.index(INSTRUCTIONS), out.index(EXAMPLES_HEADER))
		self.assertLess(out.index(EXAMPLES_HEADER), out.index(GUARDRAILS_HEADER))

	def test_guardrails_are_numbered_continuously_across_categories(self):
		out = build_static_context("", None, GUARDRAILS)

		self.assertIn("1. Keep every file under 300 lines.", out)
		self.assertIn("2. No query inside a loop.", out)
		self.assertIn("3. Never echo the whole script back.", out)
		self.assertIn("**Code Quality**", out)
		self.assertIn("**Cost & Tokens**", out)

	def test_examples_render_input_output_and_note(self):
		out = build_static_context("", EXAMPLES, None)

		self.assertIn("### Example 1", out)
		self.assertIn("add two numbers", out)
		self.assertIn("Expected output:", out)
		self.assertIn("Note: keep it terse", out)
		# Second example has no note — no stray "Note:" line for it.
		self.assertEqual(out.count("Note:"), 1)


class TestStaticContextDeterminism(FrappeTestCase):
	def test_repeated_calls_are_byte_identical(self):
		"""The property the whole story rests on: the same configuration must
		produce the same string on every iteration of an execution loop."""
		first = build_static_context(INSTRUCTIONS, EXAMPLES, GUARDRAILS)
		for _ in range(25):
			self.assertEqual(build_static_context(INSTRUCTIONS, EXAMPLES, GUARDRAILS), first)

	def test_row_order_is_the_authors_order_not_sorted(self):
		reversed_rules = list(reversed(GUARDRAILS))
		out = build_static_context("", None, reversed_rules)

		self.assertIn("1. Never echo the whole script back.", out)
		self.assertIn("3. Keep every file under 300 lines.", out)


class TestStaticContextOmission(FrappeTestCase):
	def test_no_rows_reproduces_the_bare_prompt_exactly(self):
		self.assertEqual(build_static_context(INSTRUCTIONS, [], []), INSTRUCTIONS)
		self.assertEqual(build_static_context(INSTRUCTIONS, None, None), INSTRUCTIONS)

	def test_empty_sections_emit_no_headers(self):
		out = build_static_context(INSTRUCTIONS, [], [])

		self.assertNotIn(EXAMPLES_HEADER, out)
		self.assertNotIn(GUARDRAILS_HEADER, out)

	def test_disabled_rows_are_not_sent(self):
		rows = [
			{"guardrail": "Visible rule.", "category": "Safety", "enabled": 1},
			{"guardrail": "Retired rule.", "category": "Safety", "enabled": 0},
		]
		out = build_static_context("", None, rows)

		self.assertIn("Visible rule.", out)
		self.assertNotIn("Retired rule.", out)

	def test_rows_without_enabled_field_are_treated_as_enabled(self):
		"""Rows created before the field existed must still render."""
		out = build_static_context("", None, [{"guardrail": "Legacy rule."}])

		self.assertIn("Legacy rule.", out)

	def test_blank_row_text_is_skipped(self):
		out = build_static_context("", [{"input": "   "}], [{"guardrail": ""}])

		self.assertEqual(out, "")


class TestBuildFromConfig(FrappeTestCase):
	def test_reads_examples_and_guardrails_from_the_config_dict(self):
		config = {
			"system_prompt": INSTRUCTIONS,
			"examples": EXAMPLES,
			"guardrails": GUARDRAILS,
		}
		self.assertEqual(
			build_static_context_from_config(config),
			build_static_context(INSTRUCTIONS, EXAMPLES, GUARDRAILS),
		)

	def test_explicit_system_prompt_overrides_the_config(self):
		"""The dispatcher passes the Jinja-rendered shape prompt — that is the
		value that actually runs, so it must win over the stored one."""
		config = {"system_prompt": "stored", "guardrails": GUARDRAILS}
		out = build_static_context_from_config(config, system_prompt="rendered")

		self.assertIn("rendered", out)
		self.assertNotIn("stored", out)

	def test_missing_config_is_not_an_error(self):
		self.assertEqual(build_static_context_from_config({}), "")
		self.assertEqual(build_static_context_from_config(None), "")


class TestDynamicPreamble(FrappeTestCase):
	def test_memory_precedes_the_user_message(self):
		out = build_dynamic_preamble("Relevant memory:\n- likes brevity", "write a script")

		self.assertLess(out.index("Relevant memory:"), out.index("write a script"))

	def test_marker_lets_the_adapter_split_a_cacheable_prefix(self):
		"""The Anthropic adapter splits on a newline-prefixed 'User message:'
		to place its conversation cache breakpoint — the preamble must produce
		a string that regex actually matches."""
		import re

		out = build_dynamic_preamble("Relevant memory:\n- likes brevity", "write a script")
		match = re.search(
			r"(\n+(?:User message|User request|User prompt|Request):\s*)(.*)$",
			out,
			re.IGNORECASE | re.DOTALL,
		)

		self.assertIsNotNone(match)
		self.assertEqual(match.group(2).strip(), "write a script")

	def test_no_memory_returns_the_user_prompt_untouched(self):
		"""Agents without long-term memory must send exactly what they sent
		before this story — no marker, no reformatting."""
		self.assertEqual(build_dynamic_preamble("", "write a script"), "write a script")
		self.assertEqual(build_dynamic_preamble(None, "write a script"), "write a script")

	def test_memory_without_a_user_prompt_is_returned_alone(self):
		self.assertEqual(build_dynamic_preamble("mem", ""), "mem")
