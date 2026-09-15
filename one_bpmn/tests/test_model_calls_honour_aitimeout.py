# Copyright (c) 2026, one-fm and contributors
"""A model call waits as long as the platform says, not as long as the SDK does.

Every provider SDK here ships a 600-second read timeout and two retries of its
own. The adapters built their clients with neither setting, so aiTimeout — read
into the executor and applied around the tool loop — never reached the socket,
and one stalled response held the only eval worker for thirty minutes on
2026-09-15. These pin the two facts that stop that: the factory's default is
the platform's, and what the caller asks for is what the SDK client holds.

Clients are built with a dummy key; nothing here reaches a network.
"""

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import DEFAULT_TIMEOUT_SECONDS
from one_bpmn.agents.llm_provider.factory import get_llm_adapter


class TestModelCallsHonourAiTimeout(FrappeTestCase):
	def test_the_anthropic_client_carries_the_timeout_and_retries_it_was_given(self):
		client = get_llm_adapter("anthropic", "claude-x", "key", timeout_seconds=7, max_retries=0)._client
		self.assertEqual((client.timeout, client.max_retries), (7, 0))

	def test_the_openai_client_carries_the_timeout_and_retries_it_was_given(self):
		client = get_llm_adapter("openai", "gpt-x", "key", timeout_seconds=7, max_retries=0)._client
		self.assertEqual((client.timeout, client.max_retries), (7, 0))

	def test_the_gemini_client_gets_the_timeout_in_milliseconds(self):
		options = get_llm_adapter("gemini", "gemini-x", "key", timeout_seconds=7, max_retries=0)._client._api_client._http_options
		self.assertEqual(options.timeout, 7000)
		self.assertEqual(options.retry_options.attempts, 1)

	def test_unset_means_the_platform_default_not_the_sdks_ten_minutes(self):
		for provider in ("anthropic", "openai"):
			client = get_llm_adapter(provider, "m", "key")._client
			self.assertEqual(client.timeout, DEFAULT_TIMEOUT_SECONDS, provider)
			# Callers with no retry loop of their own keep the SDK's retries.
			self.assertGreater(client.max_retries, 0, provider)
		gemini = get_llm_adapter("gemini", "m", "key")._client._api_client._http_options
		self.assertEqual(gemini.timeout, DEFAULT_TIMEOUT_SECONDS * 1000)
		self.assertIsNone(gemini.retry_options)
