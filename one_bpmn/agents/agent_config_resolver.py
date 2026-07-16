# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Resolve an AI Agent Configuration reference on an AI task/selector shape
(WI-001637).

A shape may set ``aiAgentConfig`` (a link to an AI Agent Configuration) as
an alternative to entering a raw provider. Selecting one in the editor
seeds the shape's fields — a one-time hard copy of the configuration's
provider / model / system prompt / params into the shape's own attributes.
Edits afterward stay on the shape; the configuration is never consulted at
run time and never mutated from a diagram (WI-001637). Tools are NOT sourced
from the config — the diagram's ad-hoc shapes remain the toolkit.

This module supplies the seed values to the editor; dispatch reads the
shape's copied attributes exactly as for any other AI task.
"""

import frappe
from frappe import _

# Which config field feeds which shape attribute. Only executable fields
# with a task-shape equivalent are mapped; chat-only metadata (chat mode
# label, icon, roles, lifecycle, eval suite, sample prompts) has no shape
# meaning and is intentionally omitted.
_CONFIG_TO_SHAPE = {
	"system_prompt": "aiSystemPrompt",
	"temperature": "aiTemperature",
	"max_tokens": "aiMaxTokens",
}


def config_field_map(config_name: str) -> dict:
	"""Return the shape-attribute values a configuration would seed, for the
	editor to show as placeholders. Empty dict if the config is missing."""
	if not config_name or not frappe.db.exists("AI Agent Configuration", config_name):
		return {}
	cfg = frappe.get_doc("AI Agent Configuration", config_name)
	out = {}
	for cfield, sattr in _CONFIG_TO_SHAPE.items():
		val = cfg.get(cfield)
		if val not in (None, ""):
			out[sattr] = val
	if cfg.ai_provider_credentials:
		out["aiProvider"] = cfg.ai_provider_credentials
		model = frappe.db.get_value("AI Provider Credentials", cfg.ai_provider_credentials, "default_model")
		if model:
			out["aiModel"] = model
	return out


@frappe.whitelist()
def get_agent_config_for_shape(config_name: str) -> dict:
	"""Whitelisted: the properties panel calls this on selecting a config to
	get the field values to copy into the shape's attributes (one-time seed)."""
	frappe.has_permission("AI Agent Configuration", "read", throw=True)
	return config_field_map(config_name)
