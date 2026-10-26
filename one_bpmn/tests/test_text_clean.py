# Copyright (c) 2026, one-fm and contributors
# Regression coverage for one_bpmn.agents.memory.text_clean, the shared
# de-escaping used at chat message ingestion (api.agent_invocation.invoke_agent)
# and by the conversation summarizer (agents.memory.compaction).

from __future__ import annotations

import unittest

from one_bpmn.agents.memory.text_clean import strip_html, unescape_entities


class TestUnescapeEntities(unittest.TestCase):
	def test_decodes_named_entities(self):
		# The observed live bug: a "<PROJECT>-<YEAR>-<SEQ>" naming convention was
		# stored as "&lt;PROJECT&gt;-&lt;YEAR&gt;-&lt;SEQ&gt;" (AI Memory row
		# 36jr4rba7k) — decoding must restore it exactly.
		self.assertEqual(
			unescape_entities("Use &lt;PROJECT&gt;-&lt;YEAR&gt;-&lt;SEQ&gt; for names."),
			"Use <PROJECT>-<YEAR>-<SEQ> for names.",
		)

	def test_leaves_literal_angle_brackets_untouched(self):
		# Unlike strip_html, this must never remove a literal "<...>"-shaped
		# placeholder that was never escaped in the first place.
		self.assertEqual(unescape_entities("keep <PROJECT> as-is"), "keep <PROJECT> as-is")

	def test_empty_and_none_safe(self):
		self.assertEqual(unescape_entities(""), "")
		self.assertEqual(unescape_entities(None), "")


class TestStripHtml(unittest.TestCase):
	def test_removes_tags_and_decodes_entities(self):
		self.assertEqual(strip_html("<b>Hi</b> &amp; welcome"), "Hi & welcome")

	def test_collapses_whitespace_left_by_tag_removal(self):
		self.assertEqual(strip_html("a<br/>b  <p>c</p>"), "a b c")

	def test_empty_and_none_safe(self):
		self.assertEqual(strip_html(""), "")
		self.assertEqual(strip_html(None), "")
