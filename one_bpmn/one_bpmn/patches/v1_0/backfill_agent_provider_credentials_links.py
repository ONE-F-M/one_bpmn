"""
WI-001615: link every enabled AI Agent Configuration to the AI Provider
Credentials record that reproduces its CURRENT effective provider/model,
so removing the per-agent override mechanism changes no agent's live
behavior.

The old override columns survive in the table after the fields left the
schema (Frappe never drops columns), so the patch reads them directly to
compute what each agent effectively resolved to before this change.
"""

import frappe
from frappe.utils.password import get_decrypted_password

_TYPE_BY_PROVIDER = {"gemini": "Google", "anthropic": "Anthropic", "claude": "Anthropic", "openai": "OpenAI"}
_CANONICAL = {"Google": "Gemini", "Anthropic": "Anthropic", "OpenAI": "OpenAI"}


def _old_columns_exist() -> bool:
	cols = {c.get("Field") for c in frappe.db.sql("DESC `tabAI Agent Configuration`", as_dict=True)}
	return "llm_provider_override" in cols


def _record_key(name: str) -> str:
	try:
		return get_decrypted_password("AI Provider Credentials", name, "api_key", raise_exception=False) or ""
	except Exception:
		return ""


def _find_or_create_record(ptype: str, model: str | None) -> str | None:
	"""Enabled record of *ptype* matching *model* (or any keyed record when no
	model preference); create a model-specific variant off the canonical
	record's key when the model differs."""
	records = frappe.get_all(
		"AI Provider Credentials",
		filters={"provider_type": ptype, "enabled": 1},
		fields=["name", "default_model"],
	)
	keyed = [r for r in records if _record_key(r.name)]
	if not keyed:
		return None

	canonical = next((r for r in keyed if r.name == _CANONICAL.get(ptype)), keyed[0])
	if not model or (canonical.default_model or "") == model:
		return canonical.name

	exact = next((r for r in keyed if (r.default_model or "") == model), None)
	if exact:
		return exact.name

	variant_name = f"{canonical.name} - {model}"
	if not frappe.db.exists("AI Provider Credentials", variant_name):
		doc = frappe.new_doc("AI Provider Credentials")
		doc.provider_name = variant_name
		doc.provider_type = ptype
		doc.default_model = model
		doc.api_key = _record_key(canonical.name)
		doc.enabled = 1
		doc.insert(ignore_permissions=True)
	return variant_name


def execute():
	if not frappe.db.exists("DocType", "AI Provider Credentials"):
		return

	has_old_cols = _old_columns_exist()
	settings_provider = ""
	if frappe.db.exists("DocType", "AI Chat Settings"):
		settings_provider = (
			frappe.db.get_single_value("AI Chat Settings", "processa_llm_provider")
			or frappe.db.get_single_value("AI Chat Settings", "llm_provider")
			or "gemini"
		)

	configs = frappe.get_all(
		"AI Agent Configuration",
		filters={"enabled": 1},
		fields=["name", "ai_provider_credentials"],
	)
	for cfg in configs:
		if cfg.ai_provider_credentials:
			continue  # already linked

		provider, model = settings_provider, None
		if has_old_cols:
			row = frappe.db.sql(
				"SELECT llm_provider_override, model_override FROM `tabAI Agent Configuration` WHERE name = %s",
				cfg.name,
				as_dict=True,
			)
			if row:
				override = (row[0].llm_provider_override or "").strip()
				if override and override != "Use Global":
					provider = override
				model = (row[0].model_override or "").strip() or None

		ptype = _TYPE_BY_PROVIDER.get((provider or "").lower())
		if not ptype:
			continue  # unknown provider — leave unlinked, factory falls back

		record = _find_or_create_record(ptype, model)
		if record:
			frappe.db.set_value(
				"AI Agent Configuration", cfg.name, "ai_provider_credentials", record,
				update_modified=False,
			)
			frappe.cache.delete_value(f"agent_config:{frappe.db.get_value('AI Agent Configuration', cfg.name, 'agent_id')}")

	frappe.db.commit()
