# Copyright (c) 2026, one-fm and contributors
# Anthropic's 5-series models reject sampling parameters outright:
#   400 "`temperature` is deprecated for this model."
#
# The Anthropic payload builder sent temperature unconditionally, so every call
# to claude-sonnet-5 / opus-5 / haiku-5 through direct_api failed. It surfaced
# as an empty AI task output, or — how it was actually found — an eval assertion
# whose judge never scored and reported Error instead of pass or fail.
#
# The predicate must NOT catch claude-sonnet-4-5 or claude-haiku-4-5, which do
# accept the parameters; that was verified against the live API.

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor.direct_api import _rejects_sampling_params


class TestAnthropicSamplingParams(FrappeTestCase):
	def test_five_series_models_reject_sampling_params(self):
		for model in ("claude-sonnet-5", "claude-opus-5", "claude-haiku-5",
		              "claude-sonnet-5-20260101", "CLAUDE-OPUS-5"):
			self.assertTrue(_rejects_sampling_params(model), f"{model} should be excluded")

	def test_four_series_models_still_accept_them(self):
		"""The trap: 'claude-haiku-4-5' contains a 5 but is not 5-series."""
		for model in ("claude-sonnet-4-5-20250929", "claude-haiku-4-5", "claude-opus-4-8",
		              "claude-3-5-sonnet-20241022"):
			self.assertFalse(_rejects_sampling_params(model), f"{model} should keep its params")

	def test_non_anthropic_models_are_unaffected(self):
		for model in ("gpt-4o", "gpt-5-nano", "gemini-2.0-flash", "o4-mini", ""):
			self.assertFalse(_rejects_sampling_params(model))

	def test_a_missing_model_does_not_crash_the_check(self):
		self.assertFalse(_rejects_sampling_params(None))

	def test_the_payload_omits_temperature_for_five_series(self):
		from one_bpmn.agents.executor import ExecutorConfig
		from one_bpmn.agents.executor.direct_api import DirectApiExecutor

		def payload_for(model):
			cfg = ExecutorConfig(backend="direct_api", provider_name="Anthropic", model=model,
			                     system_prompt="s", user_prompt="u", max_tokens=16)
			_url, payload, _headers = DirectApiExecutor()._build_anthropic_request(
				"https://api.anthropic.com", "k", model, cfg
			)
			return payload

		self.assertNotIn("temperature", payload_for("claude-sonnet-5"))
		self.assertNotIn("top_p", payload_for("claude-sonnet-5"))
		self.assertIn("temperature", payload_for("claude-sonnet-4-5-20250929"))
