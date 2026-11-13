# Copyright (c) 2026, one-fm and contributors
"""The memory budget lives in the AI Agent Memory module, not the Service Task dispatcher."""

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_conversations.conversation_store import DEFAULT_CHARS_PER_TOKEN, estimate_tokens
from processa.ai_agent_memory import budget as B
from processa.processa_engine.dispatch import ai_agent as D


class TestBudget(FrappeTestCase):
	def test_budget_covering_one_memory_keeps_the_first_and_drops_the_second(self):
		memories = [{"content": "first " * 40}, {"content": "second " * 40}]
		two = estimate_tokens({"content": B.format_memory_block(memories)}, DEFAULT_CHARS_PER_TOKEN)
		kept = B.bound_memories_to_budget(memories, two - 1)
		self.assertEqual(kept, memories[:1])

	def test_default_budget_is_800(self):
		self.assertEqual(B.DEFAULT_MEMORY_TOKEN_BUDGET, 800)

	def test_dispatch_module_no_longer_defines_the_format_helper(self):
		self.assertFalse(hasattr(D, "_format_memory_block"))
