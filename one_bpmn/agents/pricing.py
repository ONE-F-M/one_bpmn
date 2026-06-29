"""
Pricing utility for AI Agent observability.

Provides get_model_pricing() used by the instrumentation layer to
compute estimated costs from token usage.

Looks up pricing from the AI Model Pricing DocType by model_name.
"""

from __future__ import annotations

from typing import Dict, Optional

import frappe


def get_model_pricing(model: str) -> Optional[Dict]:
	"""
	Return the active pricing record for *model*, or None.

	Returns:
	    {"input_cost_per_1k": float, "output_cost_per_1k": float} or None
	"""
	try:
		return frappe.db.get_value(
			"AI Model Pricing",
			filters={"model_name": model, "is_active": 1},
			fieldname=["input_cost_per_1k", "output_cost_per_1k"],
			order_by="effective_from desc",
			as_dict=True,
		)
	except Exception:
		frappe.log_error(
			message=f"Failed to fetch pricing for model {model}\n{frappe.get_traceback()}",
			title="Model Pricing Error",
		)
		return None
