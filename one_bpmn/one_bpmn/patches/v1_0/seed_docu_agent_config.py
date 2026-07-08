"""
Seed the AI Agent Configuration for the Docu agent.

Docu is the AI DocType-builder embedded in Processa (see one_bpmn docu_agent).
This patch upserts the "Docu Agent" AI Agent Configuration (agent_id "docu_agent")
with Docu's system prompt and sub-prompts, mirroring Logix's non-secret settings
(framework / provider override / model / temperature / max_tokens / owner).

It deliberately does NOT seed the per-agent LLM provider/model/API-key row
(AI Chat Settings → Processa Agent LLM Config): that is environment-specific and
carries a secret, so it is configured manually per site (staging set by hand).
With no per-agent row, the LLM factory falls back to the global provider/key.

The AI Agent Configuration DocType lives in onefm_mcp; this patch ships with
one_bpmn (alongside seed_agent_prompts) because Docu is a one_bpmn agent and the
prompt text is imported from its module — keeping the Docu setup self-contained.

Idempotent and safe to re-run.
"""

import frappe

from one_bpmn.agents.google_adk.docu_agent.docu_agent import (
	_SYSTEM_PROMPT,
	_INLINE_SUB_PROMPTS,
)

_AGENT_ID = "docu_agent"
_AGENT_NAME = "Docu Agent"
_LOGIX_AGENT_ID = "logix_agent"
_FALLBACK_OWNER = "a.adekunle@one-fm.com"

# Display name + temperature per sub-prompt (prompt text comes from the module).
_SUB_META = [
	("intent_classifier", "Intent Classifier", 0.1),
	("clarifier",         "Clarifier",         0.4),
	("schema_writer",     "Schema Writer",     0.3),
	("schema_reviewer",   "Schema Reviewer",   0.1),
]


def execute():
	# AI Agent Configuration / AI Chat Settings are onefm_mcp DocTypes — skip
	# cleanly if that app isn't installed on this site.
	if not frappe.db.exists("DocType", "AI Agent Configuration"):
		return
	logix_cfg = _get_logix_agent_config()
	_seed_agent_config(logix_cfg)
	frappe.db.commit()


# ── 1. AI Agent Configuration ────────────────────────────────────────────────

def _get_logix_agent_config():
	"""Return the Logix AI Agent Configuration doc, or None if it doesn't exist."""
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": _LOGIX_AGENT_ID}, "name")
	return frappe.get_doc("AI Agent Configuration", name) if name else None


def _seed_agent_config(logix_cfg):
	# Mirror Logix's LLM settings where available; fall back to global defaults.
	framework = getattr(logix_cfg, "agent_framework", None) or "Google ADK"
	provider_override = getattr(logix_cfg, "llm_provider_override", None) or "Use Global"
	model_override = getattr(logix_cfg, "model_override", None) or None
	temperature = getattr(logix_cfg, "temperature", None)
	max_tokens = getattr(logix_cfg, "max_tokens", None)
	owner = getattr(logix_cfg, "process_owner", None) or _FALLBACK_OWNER

	config = {
		"agent_name": _AGENT_NAME,
		"agent_id": _AGENT_ID,
		"agent_framework": framework,
		"enabled": 1,
		"description": "Builds and modifies Frappe DocTypes from natural language, "
			"attached to doctype fields on Processa BPMN shapes.",
		"process_owner": owner,
		"llm_provider_override": provider_override,
		"system_prompt": _SYSTEM_PROMPT,
	}
	if model_override:
		config["model_override"] = model_override
	if temperature is not None:
		config["temperature"] = temperature
	if max_tokens is not None:
		config["max_tokens"] = max_tokens

	sub_prompts = [
		{
			"sub_agent_id": key,
			"sub_agent_name": name,
			"temperature": temp,
			"prompt_text": _INLINE_SUB_PROMPTS[key],
		}
		for key, name, temp in _SUB_META
	]

	if frappe.db.exists("AI Agent Configuration", _AGENT_NAME):
		doc = frappe.get_doc("AI Agent Configuration", _AGENT_NAME)
		doc.update(config)
		doc.set("sub_prompts", sub_prompts)
		doc.set("constants", [])
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({
			"doctype": "AI Agent Configuration",
			**config,
			"sub_prompts": sub_prompts,
			"constants": [],
		})
		doc.insert(ignore_permissions=True, ignore_if_duplicate=False)

	# Process-owner User Permission (same pattern as the other agent seeds).
	if owner and not frappe.db.exists(
		"User Permission",
		{"user": owner, "allow": "User", "for_value": owner, "applicable_for": "AI Agent Configuration"},
	):
		frappe.get_doc({
			"doctype": "User Permission",
			"user": owner,
			"allow": "User",
			"for_value": owner,
			"applicable_for": "AI Agent Configuration",
			"apply_to_all_doctypes": 0,
			"hide_descendants": 0,
		}).insert(ignore_permissions=True, ignore_if_duplicate=False)
