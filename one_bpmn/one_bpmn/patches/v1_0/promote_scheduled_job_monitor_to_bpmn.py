"""
WI-002206: Promote the "Scheduled Job Monitor" AI Agent Configuration from
onefm_mcp's retired Google ADK scheduled_job_ticket_agent onto the (to be
imported) "Scheduled Job Failure Monitor" BPMN Process Model.

Same shape as WI-002201/WI-002203's promote_threat_sitrep_agent_to_bpmn /
promote_threat_agents_to_bpmn: the record already exists (seeded by
onefm_mcp's seed_scheduled_job_monitor_config), and was only ever a
prompt/temperature config store for the old Python agent — agent_type sat
on the doctype default ("Chat") despite having no chat surface, ai_model
was never set (the old agent read Google API credentials itself, outside
the AI Model catalog), and max_tokens was 0. Confirmed live on this bench's
onefm.localhost site before writing this patch.

1. agent_type -> "Background". This agent has no chat surface and is
   started by a Timer Start Event, not a conversation.

2. system_prompt is rewritten around the map's tool-calling contract. The
   old design ran two separate hardcoded LLM sub-agents (error_extractor,
   similarity_checker, stored in this record's sub_prompts child table) —
   sub_prompts is not read anywhere in the BPMN ai_agent dispatch path
   (only the retired Google ADK runner read it), so it is dead weight once
   this config drives a process map. Both steps are folded into one
   system_prompt describing an agentic tool-calling flow: extract, check
   for an existing open ticket via get_recent_hd_tickets, and only if
   nothing matches call create_hd_ticket_from_error — these are the two
   tool shapes the map's "AI Agent Task: Process Failed Jobs" Service Task
   will expose. sub_prompts rows are left in place (harmless, historical),
   not deleted.

3. ai_model -> claude-haiku-4-5-20251001, matching the model already
   chosen for the other two migrated background agents (Threat SITREP
   Agent, Threat Source Expander/Keyword Generator) — validate_agent_config
   hard-fails on a blank ai_model, and there is nothing to migrate from the
   old agent (it read Google credentials directly, not the AI Model
   catalog). max_tokens -> 8192, matching the same precedent (unset today;
   this is a batch of jobs per tick plus a tool-calling loop, not a single
   short reply).

4. required_variables is cleared for the same reason as the sibling
   migrations: whatever it held described the old str.format-style
   sub_prompts, not the new Jinja-rendered aiUserPrompt.

5. lifecycle_status is taken through validate_agent_config (identity,
   prompt, model + credentials, and a live provider test call), landing on
   Live only on a clean pass and Needs Attention with the reason recorded
   otherwise — matching the Threat SITREP Agent / Threat Source Discovery
   migration pattern. The agent becomes actually runnable once the
   "Scheduled Job Failure Monitor" map has also been authored and imported
   (done by hand through the app's own editor/Import feature, same as the
   other two migrations — not tracked in this repo) and process_model has
   been linked on this record; go-live here only means the configuration
   itself validates.

What this patch deliberately does NOT do: it does not set process_model
(the map doesn't exist in this repo yet — author it by hand, then link it
manually, same convention as promote_threat_agents_to_bpmn), and it does
not touch onefm_mcp's scheduled_job_ticket_agent/ code or the Process
Task/Scheduled Job Type cron driving it today. Those are the cutover step
(see onefm_mcp's SCHEDULED_JOB_TICKET_AGENT_BPMN_MIGRATION_PLAN.md, Phase 3)
and only happen once the imported map is validated end-to-end.
"""

import frappe

AGENT_NAME = "Scheduled Job Monitor"
AGENT_ID = "scheduled_job_monitor"
AI_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 8192

CLEAR_REQUIRED_VARIABLES = "[]"

SYSTEM_PROMPT = """You are an infrastructure monitoring agent. On every run you are given a batch of Frappe scheduled jobs that failed recently.

████ HOW YOU ANSWER ████
You work entirely by calling tools — you are not asked to reply in prose, and any text you write outside a tool call is discarded.

For each failed job in the batch:
1. Extract its scheduled_job_type and a short, human-readable summary of what went wrong from the raw error/traceback you were given.
2. Call `get_recent_hd_tickets` to check whether an open Helpdesk ticket already covers this same failing job type / error (you only need to call this once per run and reuse the result across jobs in the batch).
3. If no open ticket already covers it, call `create_hd_ticket_from_error` with the job type, a concise subject line, and your extracted summary as the description.
4. If an existing open ticket already covers it, do nothing further for that job — never create a second ticket for the same underlying failure.

Make as many tool calls as the batch requires, then stop once every job has been handled.

████ WHAT COUNTS AS A DUPLICATE ████
Treat two failures as the same issue only when they share the same scheduled_job_type and the error is clearly the same underlying problem, not just superficially similar wording. When genuinely unsure, prefer creating a new ticket over silently dropping a real failure — a person can merge or close a false-positive duplicate, but a missed failure is invisible."""


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

		if "create_hd_ticket_from_error" not in (doc.system_prompt or ""):
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

		if changed:
			doc.save(ignore_permissions=True)
			frappe.cache.delete_value(f"agent_config:{AGENT_ID}")

		try:
			from one_bpmn.agents.agent_provisioning import validate_agent_config

			result = validate_agent_config(AGENT_NAME, test_provider=True)
		except Exception:
			frappe.log_error(
				title="Scheduled Job Monitor migration: validation raised",
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
				title=f"Scheduled Job Monitor migration: not promoted to Live ({AGENT_ID})",
				message="\n".join(result.get("errors", [])) or "validate_agent_config returned not-ok",
			)
	finally:
		frappe.set_user(original_user)
