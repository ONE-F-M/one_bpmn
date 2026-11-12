# Copyright (c) 2026, one-fm and contributors
# Regression coverage for one_bpmn.ai_agent_memory.text_clean, the shared
# de-escaping used at chat message ingestion (api.a2a.invoke_agent)
# and by the conversation summarizer (ai_agent_conversations.compaction).

from __future__ import annotations

import unittest

from one_bpmn.ai_agent_memory.text_clean import strip_html


class TestStripHtml(unittest.TestCase):
	def test_removes_tags_and_decodes_entities(self):
		self.assertEqual(strip_html("<b>Hi</b> &amp; welcome"), "Hi & welcome")

	def test_collapses_whitespace_left_by_tag_removal(self):
		self.assertEqual(strip_html("a<br/>b  <p>c</p>"), "a b c")

	def test_empty_and_none_safe(self):
		self.assertEqual(strip_html(""), "")
		self.assertEqual(strip_html(None), "")

	def test_decodes_escaped_placeholders(self):
		# The observed live bug: a "<PROJECT>-<YEAR>-<SEQ>" naming convention was
		# stored as "&lt;PROJECT&gt;-&lt;YEAR&gt;-&lt;SEQ&gt;" - decoding must restore it exactly.
		self.assertEqual(
			strip_html("Use &lt;PROJECT&gt;-&lt;YEAR&gt;-&lt;SEQ&gt; for names."),
			"Use <PROJECT>-<YEAR>-<SEQ> for names.",
		)

	def test_decodes_ampersand_angle_brackets_and_nbsp(self):
		self.assertEqual(strip_html("a &amp; b &lt; c&nbsp;d"), "a & b < c d")

	def test_decodes_entities_outside_the_old_six_entry_table(self):
		self.assertEqual(strip_html("&eacute; &#x27;"), "\u00e9 '")
