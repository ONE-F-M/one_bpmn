"""
Pricing utility for AI Agent observability.

Provides get_model_pricing() used by the instrumentation layer to
compute estimated costs from token usage.

Continues to work for onefm_mcp's existing _get_model_pricing() call
since it references "AI Model Pricing" by doctype name.

Handles version-suffixed model names (e.g. "claude-haiku-4-5-20251001")
by falling back to the base name ("claude-haiku-4-5") when an exact
match is not found.
"""

from __future__ import annotations

import re
from typing import Dict, Optional

import frappe


# Matches a trailing date-like segment: -YYYYMMDD or -YYYY-MM-DD
_DATE_SUFFIX_RE = re.compile(r"-\d{4}-?\d{2}-?\d{2}$")


def get_model_pricing(model: str) -> Optional[Dict]:
	"""
	Return the active pricing record for *model*, or None.

	Tries an exact model_name match first, then strips a trailing
	date/version suffix (e.g. "-20251001") and retries.

	Returns:
	    {"input_cost_per_1k": float, "output_cost_per_1k": float} or None
	"""
	try:
		result = _lookup(model)
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
	"""Exact model_name lookup against AI Model Pricing."""
	return frappe.db.get_value(
		"AI Model Pricing",
		filters={"model_name": model_name, "is_active": 1},
		fieldname=["input_cost_per_1k", "output_cost_per_1k"],
		order_by="effective_from desc",
		as_dict=True,
	)
