"""
WI-002203: Promote the two Threat Intelligence AI Agent Configurations
("Threat Source Expander", "Threat Keyword Generator") from onefm_mcp's
retired LangGraph pipeline onto the new "Threat Source Discovery" BPMN
Process Model.

Two things need fixing, both safe to run before the map is imported:

1. Their system_prompt still carries the old pipeline's str.format-style
   placeholders ({source_list}, {existing_keywords}, {max_keywords}) — that
   was rendered by onefm_mcp's own render_prompt() and means nothing to the
   BPMN engine's Jinja renderer, so it would now leak into the LLM call as
   literal text. The per-run data has moved to the "Threat Source Discovery"
   map's aiUserPrompt (Jinja) on the two AI Agent Task shapes, so the
   configuration's system_prompt only needs the static analyst framing.

2. process_model links the configuration to the map so agent_framework
   (LangGraph, a legacy-runner label) stops mattering — "ignored the moment
   a Process Model is linked" per the doctype's own field description.

The map itself ships as exports/threat_source_discovery.bpmn +
_config.json, imported by hand through the /spiff editor per environment
(same convention as every other process map export in this app — see
seed_frontend_agent_config for why a patch does not also import the XML).
So step 2 only takes effect once someone has done that import; until then
it's a no-op, matching the safety property seed_frontend_agent_config
documents for the same situation.
"""

import frappe

_PROCESS_MODEL = "Threat Source Discovery"

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
	model_exists = frappe.db.exists("BPMN Process Model", _PROCESS_MODEL)

	for name, static_prompt in _CONFIGS.items():
		if not frappe.db.exists("AI Agent Configuration", name):
			continue  # onefm_mcp's seed patch hasn't run on this site — nothing to promote yet

		doc = frappe.get_doc("AI Agent Configuration", name)
		changed = False

		if doc.system_prompt != static_prompt:
			doc.system_prompt = static_prompt
			changed = True

		if model_exists and doc.get("process_model") != _PROCESS_MODEL:
			doc.process_model = _PROCESS_MODEL
			changed = True

		if changed:
			doc.save(ignore_permissions=True)

	frappe.db.commit()
