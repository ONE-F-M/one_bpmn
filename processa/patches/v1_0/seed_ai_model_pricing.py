"""
Seed the AI Model Pricing DocType with default data for common models.
Only runs in developer_mode to avoid overriding production prices.
"""

import frappe


def execute():
	if not frappe.conf.developer_mode:
		return

	pricing_data = [
		{"model_name": "gpt-5-nano",       "provider": "openai", "input_cost_per_1k": 0.00005,  "output_cost_per_1k": 0.0004,  "effective_from": "2025-11-20", "is_active": 1},
		{"model_name": "gpt-4.1-nano",     "provider": "openai", "input_cost_per_1k": 0.0001,   "output_cost_per_1k": 0.0004,  "effective_from": "2025-11-20", "is_active": 1},
		{"model_name": "gpt-4o-mini",      "provider": "openai", "input_cost_per_1k": 0.00015,  "output_cost_per_1k": 0.0006,  "effective_from": "2025-11-20", "is_active": 1},
		{"model_name": "gemini-2.5-flash-lite", "provider": "gemini", "input_cost_per_1k": 0.0001,   "output_cost_per_1k": 0.0004,  "effective_from": "2025-11-20", "is_active": 1},
		{"model_name": "gemini-2.0-flash-lite", "provider": "gemini", "input_cost_per_1k": 0.000075, "output_cost_per_1k": 0.0003,  "effective_from": "2025-11-20", "is_active": 1},
		{"model_name": "gemini-2.0-flash",      "provider": "gemini", "input_cost_per_1k": 0.0001,   "output_cost_per_1k": 0.0004,  "effective_from": "2025-11-20", "is_active": 1},
		# Anthropic (Claude) — per claude.com/pricing, MTok prices ÷ 1000 → per-1k
		{"model_name": "claude-opus-4-8",   "provider": "anthropic", "input_cost_per_1k": 0.005, "output_cost_per_1k": 0.025, "effective_from": "2026-06-28", "is_active": 1},
		{"model_name": "claude-sonnet-4-6", "provider": "anthropic", "input_cost_per_1k": 0.003, "output_cost_per_1k": 0.015, "effective_from": "2026-06-28", "is_active": 1},
		{"model_name": "claude-haiku-4-5",  "provider": "anthropic", "input_cost_per_1k": 0.001, "output_cost_per_1k": 0.005, "effective_from": "2026-06-28", "is_active": 1},
		{"model_name": "claude-fable-5",    "provider": "anthropic", "input_cost_per_1k": 0.010, "output_cost_per_1k": 0.050, "effective_from": "2026-06-28", "is_active": 1},
	]

	for p in pricing_data:
		if not frappe.db.exists("AI Model Pricing", {"model_name": p["model_name"]}):
			try:
				doc = frappe.get_doc({"doctype": "AI Model Pricing", **p})
				doc.insert()
			except Exception as e:
				frappe.log_error(
					message=f"Failed to insert AI Model Pricing for {p['model_name']}: {e}",
					title="AI Model Pricing Seeding"
				)
