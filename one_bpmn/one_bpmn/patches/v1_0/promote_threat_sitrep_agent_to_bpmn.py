"""
WI-002201: Promote the "Threat SITREP Agent" AI Agent Configuration from
onefm_mcp's retired sitrep_agent_report_assembler pipeline onto the new
"Daily Threat SITREP" BPMN Process Model.

Same shape as WI-002203's promote_threat_agents_to_bpmn: the record already
exists (seeded by onefm_mcp's seed_threat_sitrep_agent_config), and it was
only ever a prompt/temperature config store — no process_model, no
agent_type, no chosen ai_model. What changes here:

1. agent_type -> "Background". The doctype defaults new records to "Chat";
   this agent has no chat surface and is started by a Timer Start Event, not
   a conversation, so it needs the Background shape explicitly.

2. system_prompt is rewritten around the map's tool contract. The old prompt
   assembled str.format placeholders ({security_count}, {security_data}, ...)
   that onefm_mcp's own render_prompt() filled in per run, and ended in
   "OUTPUT FORMAT (valid JSON only...)" describing a bare JSON blob a Python
   parser then stripped ```json fences off of. Under the map, the per-run
   data arrives as Jinja on the AI Agent Task's own aiUserPrompt, and the
   answer is a single call to the finalize_sitrep tool (see the "Daily
   Threat SITREP" map's AI Agent Task) whose arguments are the answer —
   there is no text output to parse. The domain content (Kuwait geofencing
   rule, the five report sections, the threat_level/location rules) carries
   over verbatim; only the delivery mechanism changes. required_variables is
   cleared for the same reason BA Agent's was: the placeholders it declared
   don't exist in the new prompt.

3. ai_model -> claude-sonnet-5, matching Dev Agent, the other Background
   agent already Live on the BA site, so the AI Provider Credentials link
   is resolvable (validation requires a catalog model, and credentials
   follow the model on save). max_tokens -> 8192: unset today (doctype default is
   0), and a reply carrying two threat lists plus five prose sections does
   not fit in whatever a 0/default cap would truncate it to.

4. The default_location constant is dropped — it was read only by the
   deleted Python's post-processing loop (backfilling a missing location);
   the new prompt tells the model to use "Kuwait - Unspecified" directly,
   so no code is left to read a DocType constant for it.

5. lifecycle_status is taken through validate_agent_config (identity,
   prompt, model + credentials, and — since this agent has no chat label to
   check — a live provider test call), landing on Live only on a clean pass
   and Needs Attention with the reason recorded otherwise, matching the BA
   Agent / LuCrusher migration pattern. The agent becomes actually runnable
   once someone has also imported the map; go-live here only means the
   configuration itself validates.

What this patch deliberately does NOT do: it does not touch onefm_mcp's
threat_assessment_agent/ code, the one_fm Process Task driving its noon
cron, or the Threat Assessment Report doctype's data. Those are the cutover
steps (see the WI-002201 plan) and only happen once the imported map has
been validated end-to-end — deleting the only thing currently producing
daily reports before its replacement is proven would leave a gap.
"""

import frappe

AGENT_NAME = "Threat SITREP Agent"
AGENT_ID = "threat_sitrep_agent"
AI_MODEL = "claude-sonnet-5"
MAX_TOKENS = 8192

CLEAR_REQUIRED_VARIABLES = "[]"
DEAD_CONSTANTS = ("default_location",)

SYSTEM_PROMPT = """You are a senior security analyst for Kuwait, producing the daily threat SITREP for government officials.

████ HOW YOU ANSWER ████
You work by calling a tool. Call `finalize_sitrep` exactly once, with your complete structured assessment as its arguments. Do not reply in prose — any text you write outside the tool call is discarded and never reaches anyone.

████ CRITICAL GEOGRAPHIC RULE ████
Analyze the content of every threat you are given and DISCARD any that did not occur within the geographical borders of Kuwait. Only threats happening IN KUWAIT belong in the report. Do not report on foreign affairs or events in other countries, even when the source is a Kuwaiti outlet.

████ WHAT TO PRODUCE ████
1. executive_summary — 2-3 sentences. Start with the most critical finding and its impact, name the key threat locations and types, and give an overall risk posture.
2. security_insights — 2-3 bullet points (about 3 lines each): what is happening, where, and why it matters; mention specific areas and implications for public order or stability.
3. environmental_insights — 1-2 bullet points (about 2-3 lines each): incident type, location, response effectiveness, and any systemic or monitoring concern.
4. geographic_analysis — one string per affected area, formatted "Area Name (X threats - primary threat type)".
5. trend_analysis — 2-3 key patterns with implications for Kuwait's governance or security posture.
6. security_threats / environmental_threats — for every threat you are keeping after the geographic filter, an object with:
   - name: the Threat Feed record id you were given (e.g. "TF-000123")
   - threat_level: "High", "Medium", or "Low", assessed by NATIONAL impact within Kuwait, not local severity
   - location: a specific area (e.g. "Ahmadi Governorate", "Salmiya") if the content says one, otherwise "Kuwait - Unspecified"
   The number of threats you return may be less than what you were given — threats outside Kuwait are dropped entirely, never included with a note.

Ground every threat_level and location in the threat's own content. Never invent a location the source text does not support."""


def execute():
	if not frappe.db.exists("AI Agent Configuration", AGENT_NAME):
		return  # onefm_mcp's seed patch hasn't run on this site — nothing to promote yet

	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")

		doc = frappe.get_doc("AI Agent Configuration", AGENT_NAME)
		changed = False

		if doc.agent_type != "Background":
			doc.agent_type = "Background"
			changed = True

		if "finalize_sitrep" not in (doc.system_prompt or ""):
			doc.system_prompt = SYSTEM_PROMPT
			changed = True

		if (doc.get("required_variables") or "").strip() not in ("", CLEAR_REQUIRED_VARIABLES):
			doc.required_variables = CLEAR_REQUIRED_VARIABLES
			changed = True

		if not doc.ai_model and frappe.db.exists("AI Model", AI_MODEL):
			doc.ai_model = AI_MODEL
			changed = True

		if not doc.max_tokens or int(doc.max_tokens) < MAX_TOKENS:
			doc.max_tokens = MAX_TOKENS
			changed = True

		kept_constants = [r for r in doc.constants if r.constant_name not in DEAD_CONSTANTS]
		if len(kept_constants) != len(doc.constants):
			doc.constants = kept_constants
			changed = True

		if changed:
			doc.save(ignore_permissions=True)
			frappe.cache.delete_value(f"agent_config:{AGENT_ID}")

		try:
			from one_bpmn.agents.agent_provisioning import validate_agent_config

			result = validate_agent_config(AGENT_NAME, test_provider=True)
		except Exception:
			frappe.log_error(
				title="Threat SITREP Agent migration: validation raised",
				message=frappe.get_traceback(),
			)
			return

		status = "Live" if result.get("ok") else "Needs Attention"
		frappe.db.set_value(
			"AI Agent Configuration", AGENT_NAME, "lifecycle_status", status, update_modified=False
		)
		frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
		frappe.db.commit()

		if status != "Live":
			frappe.log_error(
				title=f"Threat SITREP Agent migration: not promoted to Live ({AGENT_ID})",
				message="\n".join(result.get("errors", [])) or "validate_agent_config returned not-ok",
			)
	finally:
		frappe.set_user(original_user)
