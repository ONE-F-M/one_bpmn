"""
Tests for cache-token extraction from provider usage payloads (WI-001643).

The two provider shapes differ in a way that is easy to get backwards:

  Anthropic — ``input_tokens`` EXCLUDES cached portions, so they must be ADDED
              to reach the full consumed context.
  OpenAI    — ``prompt_tokens`` already INCLUDES the cached portion, which is
              only broken out under ``prompt_tokens_details``; adding it would
              double-count.

Either way the invariant downstream cost depends on is the same:
``prompt_tokens >= cache_read + cache_write``.
"""

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import TokenUsage
from one_bpmn.agents.executor.direct_api import DirectApiExecutor


class TestParseTokenUsage(FrappeTestCase):

	def _parse(self, raw):
		return DirectApiExecutor._parse_token_usage(raw)

	def test_anthropic_shape_adds_cache_to_prompt(self):
		usage = self._parse({
			"input_tokens": 100,
			"cache_read_input_tokens": 900,
			"cache_creation_input_tokens": 50,
			"output_tokens": 20,
		})
		self.assertEqual(usage.prompt_tokens, 1050)
		self.assertEqual(usage.cache_read_tokens, 900)
		self.assertEqual(usage.cache_write_tokens, 50)
		self.assertEqual(usage.uncached_prompt_tokens, 100)
		self.assertEqual(usage.completion_tokens, 20)

	def test_openai_shape_does_not_double_count_cache(self):
		usage = self._parse({
			"prompt_tokens": 1000,
			"prompt_tokens_details": {"cached_tokens": 800},
			"completion_tokens": 20,
			"total_tokens": 1020,
		})
		self.assertEqual(usage.prompt_tokens, 1000)
		self.assertEqual(usage.cache_read_tokens, 800)
		self.assertEqual(usage.cache_write_tokens, 0)
		self.assertEqual(usage.uncached_prompt_tokens, 200)

	def test_payload_without_cache_info_is_unchanged(self):
		usage = self._parse({"prompt_tokens": 500, "completion_tokens": 10})
		self.assertEqual(usage.prompt_tokens, 500)
		self.assertEqual(usage.cache_read_tokens, 0)
		self.assertEqual(usage.cache_write_tokens, 0)
		self.assertEqual(usage.uncached_prompt_tokens, 500)

	def test_empty_payload_is_all_zeros(self):
		usage = self._parse({})
		self.assertEqual(
			(usage.prompt_tokens, usage.completion_tokens,
			 usage.cache_read_tokens, usage.cache_write_tokens),
			(0, 0, 0, 0),
		)

	def test_uncached_never_negative(self):
		"""Defensive: cache counts larger than the prompt total are clamped, so
		cost can never come out as a credit."""
		usage = TokenUsage(prompt_tokens=100, cache_read_tokens=500)
		self.assertEqual(usage.uncached_prompt_tokens, 0)


class TestAdapterUsageHelpers(FrappeTestCase):
	"""Each adapter's _usage_tokens returns a 4-tuple in the same order."""

	class _Obj:
		def __init__(self, **kw):
			for k, v in kw.items():
				setattr(self, k, v)

	def test_anthropic_usage_tokens(self):
		from one_bpmn.agents.llm_provider.anthropic_adapter import _usage_tokens

		resp = self._Obj(usage=self._Obj(
			input_tokens=10, cache_read_input_tokens=90,
			cache_creation_input_tokens=5, output_tokens=3,
		))
		self.assertEqual(_usage_tokens(resp), (105, 3, 90, 5))

	def test_openai_usage_tokens(self):
		from one_bpmn.agents.llm_provider.openai_adapter import _usage_tokens

		resp = self._Obj(usage=self._Obj(
			prompt_tokens=100, completion_tokens=4,
			prompt_tokens_details=self._Obj(cached_tokens=64),
		))
		self.assertEqual(_usage_tokens(resp), (100, 4, 64, 0))

	def test_openai_usage_tokens_without_details(self):
		from one_bpmn.agents.llm_provider.openai_adapter import _usage_tokens

		resp = self._Obj(usage=self._Obj(prompt_tokens=100, completion_tokens=4))
		self.assertEqual(_usage_tokens(resp), (100, 4, 0, 0))

	def test_gemini_usage_tokens(self):
		from one_bpmn.agents.llm_provider.gemini import _usage_tokens

		resp = self._Obj(usage_metadata=self._Obj(
			prompt_token_count=200, candidates_token_count=8,
			cached_content_token_count=150,
		))
		self.assertEqual(_usage_tokens(resp), (200, 8, 150, 0))
