"""Tick Support Temperature on the AI Models whose API accepts temperature and top_p.

Rows are matched on model_api_name, so a per-agent row gets the same value as its
catalogue row. Every other model stays unticked and is sent neither value.
"""

import frappe

ACCEPTS_TEMPERATURE = {
	"claude-haiku-4-5",
	"claude-haiku-4-5-20251001",
	"claude-sonnet-4-5",
	"claude-sonnet-4-5-20250929",
	"claude-sonnet-4-6",
	"gpt-4.1",
	"gpt-4.1-mini",
	"gpt-4.1-nano",
	"gpt-4o",
	"gpt-4o-mini",
}


def execute():
	for model in frappe.get_all("AI Model", fields=["name", "model_api_name", "support_temperature"]):
		if accepts_temperature(model.model_api_name or model.name) and not model.support_temperature:
			frappe.db.set_value("AI Model", model.name, "support_temperature", 1, update_modified=False)
			print(f"{model.name}: Support Temperature ticked")


def accepts_temperature(api_name: str) -> bool:
	return api_name in ACCEPTS_TEMPERATURE or api_name.startswith("gemini-2")
