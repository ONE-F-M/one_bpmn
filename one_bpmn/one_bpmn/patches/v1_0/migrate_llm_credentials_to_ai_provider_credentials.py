"""
WI-001614: Migrate per-provider LLM credentials and model links out of
AI Chat Settings (onefm_mcp) into AI Provider Credentials records.

For each provider with a key stored on AI Chat Settings, upsert a
canonical AI Provider Credentials record carrying the key and the
configured default model. Existing enabled records of the same
provider_type that already hold a key are left alone (no duplicates).

The source __Auth rows are intentionally NOT deleted: legacy readers
(Lumina direct-API path, llm_factory fallback) keep working until each
agent's migration story retires them. Field removal from the AI Chat
Settings form ships in the companion onefm_mcp commit.

Because that companion commit drops the model fields from the doctype, this
patch cannot read them through the normal accessors — see
``_removed_single_value`` below.
"""

import frappe
from frappe.utils.password import get_decrypted_password

# (canonical record name, provider_type, AI Chat Settings key field, model field)
PROVIDERS = [
	("OpenAI", "OpenAI", "openai_api_key", "openai_model"),
	("Gemini", "Google", "gemini_api_key", "gemini_model"),
	("Anthropic", "Anthropic", "anthropic_api_key", "anthropic_model"),
	("xAI", "OpenAI-compatible", "xai_api_key", None),
]


def _removed_single_value(doctype: str, fieldname: str) -> str:
	"""Read a Single's stored value straight out of ``tabSingles``.

	The companion onefm_mcp commit deletes these model fields from AI Chat
	Settings, and this patch runs post-model-sync — so on any site that syncs
	the new schema before running the patch, the field is already gone from the
	doctype. ``frappe.db.get_single_value`` validates against the doctype meta
	and throws for an undeclared field, even though the row itself survives in
	``tabSingles`` (Frappe does not delete stored values when a field is
	dropped). Reading the row directly is what makes this patch replayable on a
	site of any vintage.
	"""
	row = frappe.qb.get_query(
		table="Singles",
		filters={"doctype": doctype, "field": fieldname},
		fields="value",
	).run()
	return (row[0][0] if row else "") or ""


def execute():
	if not frappe.db.exists("DocType", "AI Chat Settings"):
		return  # onefm_mcp not installed — nothing to migrate

	for name, ptype, key_field, model_field in PROVIDERS:
		try:
			api_key = get_decrypted_password(
				"AI Chat Settings", "AI Chat Settings", key_field, raise_exception=False
			)
		except Exception:
			api_key = None  # undecryptable (e.g. restored site) — skip, never guess
		if not api_key:
			continue

		default_model = ""
		if model_field:
			default_model = _removed_single_value("AI Chat Settings", model_field)

		# An enabled record of this provider_type that already has a key wins.
		existing = frappe.get_all(
			"AI Provider Credentials",
			filters={"provider_type": ptype, "enabled": 1},
			pluck="name",
		)
		claimed = False
		for rec in existing:
			try:
				if get_decrypted_password("AI Provider Credentials", rec, "api_key", raise_exception=False):
					claimed = True
					break
			except Exception:
				continue
		if claimed:
			continue

		if frappe.db.exists("AI Provider Credentials", name):
			doc = frappe.get_doc("AI Provider Credentials", name)
		else:
			doc = frappe.new_doc("AI Provider Credentials")
			doc.provider_name = name
			doc.provider_type = ptype
		doc.api_key = api_key
		# WI-001655 dropped default_model from AI Provider Credentials (the model
		# is now the agent's own AI Model pick). Only carry the legacy value over
		# on sites whose schema still has the field: on a new_doc, an attribute
		# for a field that is not in the meta raises AttributeError rather than
		# returning None.
		if default_model and doc.meta.has_field("default_model") and not doc.get("default_model"):
			doc.default_model = default_model
		doc.enabled = 1
		doc.save(ignore_permissions=True)

	frappe.db.commit()
