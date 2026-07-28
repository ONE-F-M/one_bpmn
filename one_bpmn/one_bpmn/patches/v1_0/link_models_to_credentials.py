"""
WI-001655: Credentials = connection, Model = catalog entry pointing at its
credentials, Agent = picks a model.

Migration follows the approved "Leave Blank" ruling — nothing is invented:

1. AI Model.ai_provider_credentials is backfilled from the legacy lowercase
   ``provider`` Select ONLY where exactly one enabled credentials record of
   the matching provider_type exists; ambiguous/absent cases stay blank for
   manual linking.
2. Each agent's ``ai_model`` is backfilled from its credentials' old
   ``default_model`` value ONLY when that value exists in the catalog AND the
   catalog record's credentials link agrees (or is blank, in which case the
   link is completed). Everything else stays blank — those agents park in
   Needs Attention with an actionable reason on their next validation.

Idempotent. Reads the legacy columns straight from the DB since their fields
are gone from the meta.
"""

import frappe

# legacy AI Model.provider values -> AI Provider Credentials.provider_type
_LEGACY_PROVIDER_TYPE = {"openai": "OpenAI", "anthropic": "Anthropic", "gemini": "Google"}


def execute():
	if not frappe.db.exists("DocType", "AI Model"):
		return

	# ── 1. AI Model -> credentials link (unambiguous only) ────────────────
	if frappe.db.has_column("AI Model", "provider"):
		for row in frappe.db.sql(
			"""select name, provider from `tabAI Model`
			   where ifnull(ai_provider_credentials, '') = ''""",
			as_dict=True,
		):
			ptype = _LEGACY_PROVIDER_TYPE.get((row.provider or "").strip().lower())
			if not ptype:
				continue
			creds = frappe.get_all(
				"AI Provider Credentials", filters={"provider_type": ptype, "enabled": 1}, pluck="name"
			)
			if len(creds) == 1:
				frappe.db.set_value("AI Model", row.name, "ai_provider_credentials", creds[0], update_modified=False)

	# ── 2. Agent.ai_model from the credentials' old default_model ─────────
	if frappe.db.has_column("AI Provider Credentials", "default_model"):
		defaults = {
			r.name: (r.default_model or "").strip()
			for r in frappe.db.sql(
				"select name, default_model from `tabAI Provider Credentials`", as_dict=True
			)
		}
		agents = frappe.get_all(
			"AI Agent Configuration",
			filters={"ai_model": ("in", ["", None]), "ai_provider_credentials": ("is", "set")},
			fields=["name", "ai_provider_credentials"],
		)
		for agent in agents:
			old_default = defaults.get(agent.ai_provider_credentials)
			if not old_default or not frappe.db.exists("AI Model", old_default):
				continue  # Leave Blank — parks with a reason on next validation
			model_creds = frappe.db.get_value("AI Model", old_default, "ai_provider_credentials")
			if not model_creds:
				# Complete the catalog record's link from the agent's own creds
				frappe.db.set_value(
					"AI Model", old_default, "ai_provider_credentials",
					agent.ai_provider_credentials, update_modified=False,
				)
			elif model_creds != agent.ai_provider_credentials:
				continue  # disagreement — leave blank rather than guess
			frappe.db.set_value(
				"AI Agent Configuration", agent.name, "ai_model", old_default, update_modified=False
			)

	frappe.db.commit()
