"""
WI-002203: Promote the two Threat Intelligence AI Agent Configurations
("Threat Source Expander", "Threat Keyword Generator") from onefm_mcp's
retired LangGraph pipeline onto the new "Threat Source Discovery" BPMN
Process Model.

Three things need fixing, all safe to run regardless of whether the map
has been imported yet:

0. agent_type. Neither onefm_mcp seed patch (seed_threat_source_expander_config,
   seed_threat_keyword_generator_config) ever set it, so both configs sat on the
   doctype's default, "Chat" — despite neither having a chat surface; this
   pipeline calls them purely as LLM steps inside a batch process. Left on
   "Chat" they never reach lifecycle_status=Live (BackgroundLifecycle's
   auto-promotion in apply_background_lifecycle only runs for agent_type=
   "Background"), and compile_process_model refuses to deploy any AI Agent
   Task whose linked configuration isn't Live. Confirmed live: this migrate
   run hit exactly that ("AI Agent Configuration 'Threat Source Expander' is
   Draft") before agent_type was corrected here.

1. Their system_prompt still carries the old pipeline's str.format-style
   placeholders ({source_list}, {existing_keywords}, {max_keywords}) — that
   was rendered by onefm_mcp's own render_prompt() and means nothing to the
   BPMN engine's Jinja renderer, so it would now leak into the LLM call as
   literal text. The per-run data has moved to the "Threat Source Discovery"
   map's aiUserPrompt (Jinja) on the two AI Agent Task shapes, so the
   configuration's system_prompt only needs the static analyst framing —
   and required_variables (which validate_required_variables() checks
   against system_prompt on every save) has to be cleared alongside it, or
   save() throws "required variables are missing" the moment the
   placeholder it's expecting is gone. Confirmed live: this migrate run
   hit exactly that on Threat Source Expander before required_variables
   was cleared here too.

2. ai_model was never set by either onefm_mcp seed patch either — the old
   pipeline called its own get_llm() rather than the AI Model catalog, so
   there was nothing to migrate. validate_agent_config() (the check this
   platform's go-live flow runs, WI-001621) hard-fails on a blank ai_model
   ("No AI Model is linked"), so without this these configs can never pass
   validation at all, let alone reach Live. Points at claude-haiku-4-5-20251001
   to match the model the Logix pipeline runs on; if that catalog entry has
   no working credentials on a given site, that's a site config gap for
   whoever administers it, not something this patch should route around
   by silently picking a different model.

This patch deliberately does not touch process_model — the map is moved
between environments by hand through the app's own Import/Export feature,
not tracked in this repo, so there is nothing here for this patch to link
the configuration to. Set that link manually after importing, if needed.
"""

import frappe

_CONFIGS = {
	"Threat Source Expander": (
		"You are a security intelligence analyst researching credible threat "
		"monitoring sources in Kuwait.\n\n"
		"Requirements:\n"
		"1. Each source must be an existing, publicly accessible website or social media account.\n"
		"2. Prefer well-known or recently active sources.\n"
		"3. Do not invent or guess URLs.\n"
		"4. Avoid duplicates of sources you are shown.\n\n"
		"Valid types: News Website, Forum, Blog, Reddit, Twitter, Telegram, Facebook, Medium, Quora, Other.\n\n"
		"Always return valid JSON only, in the exact shape the task asks for — no text before or after."
	),
	"Threat Keyword Generator": (
		"You are a security intelligence analyst tracking security threats in Kuwait.\n\n"
		"Focus on:\n"
		"- Crime-related terms\n"
		"- Security incidents\n"
		"- Public safety\n"
		"- Emergency situations\n"
		"- Both English and Arabic contexts\n\n"
		"Always return valid JSON only, in the exact shape the task asks for — no text before or after."
	),
}


def execute():
	for name, static_prompt in _CONFIGS.items():
		if not frappe.db.exists("AI Agent Configuration", name):
			continue  # onefm_mcp's seed patch hasn't run on this site — nothing to promote yet

		doc = frappe.get_doc("AI Agent Configuration", name)
		changed = False

		if doc.agent_type != "Background":
			doc.agent_type = "Background"
			changed = True

		if doc.system_prompt != static_prompt:
			doc.system_prompt = static_prompt
			changed = True

		if (doc.get("required_variables") or "[]") != "[]":
			doc.required_variables = "[]"
			changed = True

		if not doc.get("ai_model") and frappe.db.exists("AI Model", "claude-haiku-4-5-20251001"):
			doc.ai_model = "claude-haiku-4-5-20251001"
			changed = True

		if changed:
			doc.save(ignore_permissions=True)

	frappe.db.commit()
