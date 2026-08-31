"""
Tests for cache-aware token pricing (WI-001643).

Before this, every prompt token was billed at the input rate — including tokens
served from the prompt cache, which bill at a fraction of it. These tests pin the
three-way input split (uncached / cache read / cache write) and the derived-rate
fallback.

WI-002134 moved the rate card onto the AI Model catalog, per MILLION tokens, and
dropped the configurable cache rates — nothing ever set them, so they are always
derived now. The fixture below therefore writes per-1M rates onto a model, while
every assertion stays in per-1k, which is what compute_token_cost() works in.
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

	def _make_pricing(self, *, input_rate=0.01, output_rate=0.03):
		"""A priced model. Rates are given per 1k, as every assertion here reads
		them, and stored per 1M, as the catalog holds them."""
		model = f"priced-{frappe.generate_hash(length=8)}"
		provider = f"test-provider-{frappe.generate_hash(length=8)}"
		frappe.get_doc({
			"doctype": "AI Provider",
			"provider": provider,
			"provider_type": "Anthropic",
			"api_key": "test-key-not-used",
			"enabled": 1,
		}).insert(ignore_permissions=True)
		frappe.get_doc({
			"doctype": "AI Model",
			"model_name": model,
			"provider": provider,
			"enable_model": 1,
			"model_api_name": model,
			"input_cost": input_rate * 1000,
			"output_cost": output_rate * 1000,
		}).insert(ignore_permissions=True)
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

	def test_cache_rates_are_always_derived_now(self):
		"""They used to be configurable and never were configured. Deriving them
		from the input rate is the only behaviour, so a model cannot express a
		non-standard cache rate — acceptable because the providers that charge
		nothing for cache writes report no cache-write tokens at all."""
		model = self._make_pricing(input_rate=0.02)
		pricing = get_model_pricing(model)
		self.assertAlmostEqual(pricing["cache_read_cost_per_1k"], 0.02 * CACHE_READ_MULTIPLIER, places=9)
		self.assertAlmostEqual(pricing["cache_write_cost_per_1k"], 0.02 * CACHE_WRITE_MULTIPLIER, places=9)

	# ── the split ────────────────────────────────────────────────────────

	def test_cost_splits_prompt_across_three_rates(self):
		"""prompt_tokens is INCLUSIVE of the cache figures; each part bills at
		its own rate."""
		# 0.001 and 0.0125 are the derived rates for a 0.01 input rate.
		model = self._make_pricing(input_rate=0.01, output_rate=0.03)
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
		model = self._make_pricing(input_rate=0.01)
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

	# ── the unit boundary (WI-002134) ────────────────────────────────────

	def test_rates_stored_per_million_are_read_as_per_thousand(self):
		"""The catalog holds per-1M because providers publish per-1M; this module
		and its callers reason in per-1k. A factor-of-1000 slip here would
		misreport every cost on the site by 1000x, in silence."""
		model = self._make_pricing(input_rate=0.002, output_rate=0.01)
		stored = frappe.db.get_value("AI Model", model, ["input_cost", "output_cost"], as_dict=True)
		self.assertAlmostEqual(stored.input_cost, 2.0, places=9)
		self.assertAlmostEqual(stored.output_cost, 10.0, places=9)

		pricing = get_model_pricing(model)
		self.assertAlmostEqual(pricing["input_cost_per_1k"], 0.002, places=9)
		self.assertAlmostEqual(pricing["output_cost_per_1k"], 0.01, places=9)

	def test_a_model_with_no_rate_is_unknown_not_free(self):
		"""An unpriced model has to report unknown, the way a missing rate-card
		row used to. Currency columns read back as 0, so a row of zeros is
		indistinguishable from free — and calling it free understates spend."""
		model = f"unpriced-{frappe.generate_hash(length=8)}"
		frappe.get_doc({
			"doctype": "AI Model", "model_name": model, "enable_model": 0,
		}).insert(ignore_permissions=True)
		self.assertIsNone(get_model_pricing(model))

	def test_the_providers_own_name_for_a_model_also_resolves(self):
		"""Runs report whatever name was sent to the API, which may be the
		model_api_name rather than the catalog name."""
		model = self._make_pricing(input_rate=0.01)
		frappe.db.set_value("AI Model", model, "model_api_name", f"{model}-api")
		pricing = get_model_pricing(f"{model}-api")
		self.assertIsNotNone(pricing)
		self.assertAlmostEqual(pricing["input_cost_per_1k"], 0.01, places=9)
