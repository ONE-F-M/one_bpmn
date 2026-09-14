# Copyright (c) 2026, one-fm and contributors
"""Deriving a model's readable name from its API identifier.

The derivation is what every model picker in Processa now reads, and it runs
once per row in a patch that cannot be re-run to correct itself — so the shapes
that appear in the real catalogue are pinned here rather than left to a glance
at the output.
"""

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0.readable_ai_model_names import (
	_still_an_identifier,
	readable_name,
)


class TestReadableAIModelNames(FrappeTestCase):
	def test_the_identifiers_actually_in_the_catalogue(self):
		for identifier, expected in (
			("claude-opus-5", "Claude Opus 5"),
			("claude-haiku-4-5", "Claude Haiku 4.5"),
			("claude-sonnet-4-5-20250929", "Claude Sonnet 4.5 (2025-09-29)"),
			("gemini-2.0-flash-lite", "Gemini 2.0 Flash Lite"),
			("gpt-4.1-mini", "GPT 4.1 Mini"),
			("gpt-4o", "GPT 4o"),
			("o4-mini", "O4 Mini"),
		):
			with self.subTest(identifier=identifier):
				self.assertEqual(readable_name(identifier), expected)

	def test_consecutive_numbers_join_as_a_version(self):
		"""Vendors write 4.5, not "4 5" — the segments are one version number."""
		self.assertEqual(readable_name("claude-sonnet-4-5"), "Claude Sonnet 4.5")

	def test_a_trailing_date_becomes_a_date(self):
		self.assertEqual(readable_name("model-20251001"), "Model (2025-10-01)")

	def test_eight_digits_that_are_not_trailing_stay_a_number(self):
		self.assertEqual(readable_name("20250929-model"), "20250929 Model")

	def test_nothing_in_nothing_out(self):
		self.assertEqual(readable_name(""), "")
		self.assertEqual(readable_name(None), "")

	def test_a_name_someone_wrote_is_not_an_identifier(self):
		"""The patch only rewrites rows nobody has named yet, so this guard is
		what stops it overwriting a hand-picked label on a re-run."""
		self.assertTrue(_still_an_identifier("claude-opus-5"))
		self.assertTrue(_still_an_identifier("o4-mini"))
		self.assertFalse(_still_an_identifier("Claude Opus 5"))
		self.assertFalse(_still_an_identifier("GPT 4o"))
		self.assertFalse(_still_an_identifier(""))

	def test_deriving_twice_changes_nothing(self):
		"""readable_name is not idempotent by construction, so the guard above
		is what makes the patch safe to re-run — assert the pair together."""
		once = readable_name("claude-opus-5")
		self.assertFalse(_still_an_identifier(once))
