"""
Tests for cache-aware token pricing (WI-001643).

Before this, every prompt token was billed at the input rate — including tokens
served from the prompt cache, which bill at a fraction of it. These tests pin the
three-way input split (uncached / cache read / cache write) and the derived-rate
fallback.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.pricing import (
	CACHE_READ_MULTIPLIER,
	CACHE_WRITE_MULTIPLIER,
	compute_token_cost,
	get_model_pricing,
)


class TestCacheAwarePricing(FrappeTestCase):

	def _make_pricing(self, *, input_rate=0.01, output_rate=0.03,
	                  cache_read=None, cache_write=None):
		model = f"priced-{frappe.generate_hash(length=8)}"
		provider = f"test-provider-{frappe.generate_hash(length=8)}"
		frappe.get_doc({
			"doctype": "AI Provider Credentials",
			"provider_name": provider,
			"provider_type": "Anthropic",
			"api_key": "test-key-not-used",
			"enabled": 1,
		}).insert(ignore_permissions=True)
		row = {
			"doctype": "AI Model Pricing",
			"model_name": model,
			"provider": provider,
			"input_cost_per_1k": input_rate,
			"output_cost_per_1k": output_rate,
			"effective_from": "2025-01-01",
			"is_active": 1,
		}
		if cache_read is not None:
			row["cache_read_cost_per_1k"] = cache_read
		if cache_write is not None:
			row["cache_write_cost_per_1k"] = cache_write
		frappe.get_doc(row).insert(ignore_permissions=True)
		return model

	# ── derived rates ────────────────────────────────────────────────────

	def test_unset_cache_rates_derive_from_input_rate(self):
		"""A pricing row with no cache rates gets the standard ratios.

		Frappe Currency columns are NOT NULL DEFAULT 0, so "not filled in" reads
		back as 0.0 — which must derive, not bill at zero.
		"""
		model = self._make_pricing(input_rate=0.01)
		pricing = get_model_pricing(model)
		self.assertAlmostEqual(pricing["cache_read_cost_per_1k"], 0.01 * CACHE_READ_MULTIPLIER, places=9)
		self.assertAlmostEqual(pricing["cache_write_cost_per_1k"], 0.01 * CACHE_WRITE_MULTIPLIER, places=9)

	def test_explicit_cache_rates_win_over_derived(self):
		model = self._make_pricing(input_rate=0.01, cache_read=0.005, cache_write=0.02)
		pricing = get_model_pricing(model)
		self.assertAlmostEqual(pricing["cache_read_cost_per_1k"], 0.005, places=9)
		self.assertAlmostEqual(pricing["cache_write_cost_per_1k"], 0.02, places=9)

	# ── the split ────────────────────────────────────────────────────────

	def test_cost_splits_prompt_across_three_rates(self):
		"""prompt_tokens is INCLUSIVE of the cache figures; each part bills at
		its own rate."""
		model = self._make_pricing(input_rate=0.01, output_rate=0.03,
		                           cache_read=0.001, cache_write=0.0125)
		costs = compute_token_cost(
			model,
			prompt_tokens=10_000,      # of which:
			cache_read_tokens=6_000,   #   6k from cache
			cache_write_tokens=1_000,  #   1k written to cache
			completion_tokens=2_000,   # → 3k uncached input
		)
		self.assertAlmostEqual(costs["input_cost"], (3_000 / 1000) * 0.01, places=9)
		self.assertAlmostEqual(costs["cache_read_cost"], (6_000 / 1000) * 0.001, places=9)
		self.assertAlmostEqual(costs["cache_write_cost"], (1_000 / 1000) * 0.0125, places=9)
		self.assertAlmostEqual(costs["output_cost"], (2_000 / 1000) * 0.03, places=9)
		self.assertAlmostEqual(costs["total_cost"], 0.03 + 0.006 + 0.0125 + 0.06, places=9)

	def test_cached_prompt_is_cheaper_than_the_old_flat_calculation(self):
		"""The regression this WI exists to fix: billing the whole prompt at the
		input rate overstates spend whenever caching is active."""
		model = self._make_pricing(input_rate=0.01, output_rate=0.03)
		flat = (10_000 / 1000) * 0.01 + (1_000 / 1000) * 0.03
		actual = compute_token_cost(
			model, prompt_tokens=10_000, cache_read_tokens=9_000, completion_tokens=1_000
		)["total_cost"]
		self.assertLess(actual, flat)

	def test_no_cache_tokens_matches_flat_input_rate(self):
		"""Backward compatibility: with no caching, cost is unchanged."""
		model = self._make_pricing(input_rate=0.01, output_rate=0.03)
		costs = compute_token_cost(model, prompt_tokens=1_000, completion_tokens=2_000)
		self.assertAlmostEqual(costs["input_cost"], 0.01, places=9)
		self.assertAlmostEqual(costs["output_cost"], 0.06, places=9)
		self.assertAlmostEqual(costs["total_cost"], 0.07, places=9)
		self.assertEqual(costs["cache_read_cost"], 0.0)
		self.assertEqual(costs["cache_write_cost"], 0.0)

	# ── defensive behaviour ──────────────────────────────────────────────

	def test_cache_exceeding_prompt_never_yields_a_credit(self):
		"""A provider reporting cache counts NOT included in its prompt total
		must not drive the uncached figure negative."""
		model = self._make_pricing(input_rate=0.01, cache_read=0.001)
		costs = compute_token_cost(
			model, prompt_tokens=100, cache_read_tokens=5_000, completion_tokens=0
		)
		self.assertEqual(costs["input_cost"], 0.0)
		self.assertGreater(costs["total_cost"], 0.0)

	def test_unknown_or_blank_model_costs_zero(self):
		"""Unknown cost is reported as 0, never guessed."""
		for model in (f"missing-{frappe.generate_hash(length=6)}", ""):
			costs = compute_token_cost(model, prompt_tokens=5_000, completion_tokens=5_000)
			self.assertEqual(costs["total_cost"], 0.0)

	def test_caller_supplied_pricing_row_skips_lookup_and_still_derives(self):
		costs = compute_token_cost(
			"anything",
			prompt_tokens=2_000,
			cache_read_tokens=1_000,
			pricing={"input_cost_per_1k": 0.01, "output_cost_per_1k": 0.03},
		)
		# 1k uncached at 0.01 + 1k cache-read at the derived 0.001
		self.assertAlmostEqual(costs["input_cost"], 0.01, places=9)
		self.assertAlmostEqual(costs["cache_read_cost"], 0.001, places=9)
