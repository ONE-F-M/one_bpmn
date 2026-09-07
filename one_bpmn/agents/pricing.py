"""
Pricing utility for AI Agent observability.

Provides:
  - get_model_pricing()  — the rate card for a model (with cache rates resolved)
  - compute_token_cost() — cost of one interaction, split by billing rate

Looks up pricing from the AI Model catalog, whose record name IS the model
name. Handles version-suffixed model names (e.g. "claude-haiku-4-5-20251001")
by falling back to the base name ("claude-haiku-4-5") when an exact match is not
found, and to model_api_name for a model the provider calls something else.

Rates are stored on the model per MILLION tokens, which is how providers publish
them. This module works in per-1k throughout — every caller and every test does
— so the conversion happens once, here at the lookup, rather than at each of the
four places a rate is multiplied out.

Prompt caching (WI-001643): cached input tokens are not billed at the input
rate, so cost cannot be derived from a single input figure. Every provider we
support reports its cached portions separately; those counts now reach here and
are billed at their own rates. Where a model has no explicit cache rates
configured, they are derived from the input rate using the standard Anthropic
ratios below.
"""

from __future__ import annotations

import re
from typing import Dict, Optional

import frappe


# Matches a trailing date-like segment: -YYYYMMDD or -YYYY-MM-DD
_DATE_SUFFIX_RE = re.compile(r"-\d{4}-?\d{2}-?\d{2}$")

# Per 1M (how the catalog stores it) → per 1k (how this module reasons).
_PER_1M_TO_PER_1K = 1000.0

# Cache rates are always derived rather than configured: nothing ever set them,
# and every provider we bill either follows these ratios or reports no cache
# tokens at all. Anthropic bills cache reads at 0.1x and 5-minute cache writes
# at 1.25x the base input rate.
CACHE_READ_MULTIPLIER = 0.10
CACHE_WRITE_MULTIPLIER = 1.25


def get_model_pricing(model: str) -> Optional[Dict]:
	"""
	Return the active pricing record for *model*, or None.

	Tries an exact model_name match first, then strips a trailing
	date/version suffix (e.g. "-20251001") and retries.

	Returns:
	    {"input_cost_per_1k", "output_cost_per_1k", "cache_read_cost_per_1k",
	     "cache_write_cost_per_1k"} or None. The two cache rates are always
	    populated — derived from the input rate when not configured.
	"""
	try:
		result = _lookup(model)
		if result:
			return result

		# What the provider's API calls it, when that differs from the catalog
		# name. Runs report the name they sent, which may be either.
		by_api_name = frappe.db.get_value("AI Model", {"model_api_name": model}, "name")
		if by_api_name:
			result = _lookup(by_api_name)
			if result:
				return result

		# Strip trailing date suffix and retry
		base = _DATE_SUFFIX_RE.sub("", model)
		if base != model:
			return _lookup(base)

		return None
	except Exception:
		frappe.log_error(
			message=f"Failed to fetch pricing for model {model}\n{frappe.get_traceback()}",
			title="Model Pricing Error",
		)
		return None


def _lookup(model_name: str) -> Optional[Dict]:
	"""Exact lookup against the AI Model catalog.

	A model with no rate returns None rather than a row of zeros, so an
	unpriced model reports unknown cost instead of free — the same distinction
	the old rate card made by simply having no row.

	Cache rates are resolved here rather than by callers so every consumer of
	get_model_pricing() gets the same derived defaults.
	"""
	rates = frappe.db.get_value(
		"AI Model", model_name, ["input_cost", "output_cost"], as_dict=True
	)
	if not rates:
		return None
	if not (_flt(rates.get("input_cost")) or _flt(rates.get("output_cost"))):
		return None

	row = {
		"input_cost_per_1k": _flt(rates.get("input_cost")) / _PER_1M_TO_PER_1K,
		"output_cost_per_1k": _flt(rates.get("output_cost")) / _PER_1M_TO_PER_1K,
		"cache_read_cost_per_1k": 0.0,
		"cache_write_cost_per_1k": 0.0,
	}
	_apply_cache_rate_defaults(row)
	return row


def _apply_cache_rate_defaults(row: Dict) -> None:
	"""Fill unset cache rates from the input rate, in place.

	"Unset" means falsy (None or 0), NOT just None. Frappe Currency columns are
	``NOT NULL DEFAULT 0``, so a rate nobody has filled in reads back as 0.0 and
	is indistinguishable from a deliberately-entered 0 — the form shows an empty
	box for both. Testing only for None would therefore bill every cached token
	at zero on every existing pricing row, understating cost as badly as the
	pre-WI-001643 behaviour overstated it.

	Deriving instead fails safe: an unconfigured model gets the standard ratio
	rather than a free ride. The cost of this choice is that a genuinely-zero
	cache rate cannot be expressed — acceptable because the providers that
	charge nothing for cache writes (OpenAI, Gemini) report no cache-write
	tokens in the first place, so the write rate is never applied to them.
	"""
	input_rate = _flt(row.get("input_cost_per_1k"))
	if not _flt(row.get("cache_read_cost_per_1k")):
		row["cache_read_cost_per_1k"] = input_rate * CACHE_READ_MULTIPLIER
	if not _flt(row.get("cache_write_cost_per_1k")):
		row["cache_write_cost_per_1k"] = input_rate * CACHE_WRITE_MULTIPLIER


def _flt(value) -> float:
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def compute_token_cost(
	model: str,
	*,
	prompt_tokens: int = 0,
	completion_tokens: int = 0,
	cache_read_tokens: int = 0,
	cache_write_tokens: int = 0,
	pricing: Optional[Dict] = None,
) -> Dict[str, float]:
	"""Cost of one LLM interaction, split by billing rate (WI-001643).

	``prompt_tokens`` is the FULL consumed input context and is INCLUSIVE of the
	two cache figures; the portion billed at the standard input rate is
	therefore ``prompt_tokens - cache_read - cache_write``. Charging the whole
	prompt at the input rate — what happened before this function existed —
	overstates spend on any cached workload, because cache reads bill at a
	fraction of the input rate.

	Pass *pricing* to reuse an already-fetched row and skip the lookup.

	Returns ``{"input_cost", "output_cost", "cache_read_cost",
	"cache_write_cost", "total_cost"}``; all zeros when the model has no
	pricing row (unknown cost is reported as 0, never guessed).
	"""
	zero = {
		"input_cost": 0.0,
		"output_cost": 0.0,
		"cache_read_cost": 0.0,
		"cache_write_cost": 0.0,
		"total_cost": 0.0,
	}
	if not model:
		return zero
	if pricing is None:
		pricing = get_model_pricing(model)
	if not pricing:
		return zero

	# Defensive: a caller-supplied row may not have been through _lookup.
	if not (pricing.get("cache_read_cost_per_1k") and pricing.get("cache_write_cost_per_1k")):
		pricing = dict(pricing)
		_apply_cache_rate_defaults(pricing)

	cache_read = max(0, int(cache_read_tokens or 0))
	cache_write = max(0, int(cache_write_tokens or 0))
	# Clamp: a provider that reported cache counts NOT included in its prompt
	# total must not produce a negative uncached figure (and thus a credit).
	uncached = max(0, int(prompt_tokens or 0) - cache_read - cache_write)

	input_cost = (uncached / 1000.0) * _flt(pricing.get("input_cost_per_1k"))
	output_cost = (int(completion_tokens or 0) / 1000.0) * _flt(pricing.get("output_cost_per_1k"))
	cache_read_cost = (cache_read / 1000.0) * _flt(pricing.get("cache_read_cost_per_1k"))
	cache_write_cost = (cache_write / 1000.0) * _flt(pricing.get("cache_write_cost_per_1k"))

	return {
		"input_cost": input_cost,
		"output_cost": output_cost,
		"cache_read_cost": cache_read_cost,
		"cache_write_cost": cache_write_cost,
		"total_cost": input_cost + output_cost + cache_read_cost + cache_write_cost,
	}

