"""
WI-002204: setup for the Error Log Ticket Triage process map, migrated off
onefm_mcp's ErrorLogTicketAgent (Google ADK).

Three things this map needs that don't come from importing the .bpmn export
alone, because they are DB records rather than diagram content:

1. Error Log.hd_ticket — the agent has always written this field, but no
   fixture/patch for it exists anywhere in either app's history; it only
   exists today as an ad hoc Custom Field on one site's DB. Captured here so
   the migration is reproducible on a fresh site.

2. The two Server Scripts the diagram's Script Tasks call by name
   (spiffworkflow:serverScript). Diagrams are data, never code — the scripts
   are the code, and belong in a patch like every other BPMN-invoked Server
   Script in this app (see Drive — * for the pattern).

3. AI Agent Configuration "Error Log Ticket Agent" (already seeded by
   onefm_mcp's old patch) is repointed to a real AI Model — it shipped with
   ai_provider=Anthropic but ai_model empty, which the AI Agent Task's dispatch
   needs a real model for — and its system_prompt is replaced with the merged
   match/no_match instructions the old code split across a top-level prompt
   and a Google-ADK sub-agent prompt (sub_prompts are not read by this
   engine's AI Agent Task dispatch at all — only the top-level system_prompt
   is, per agent_config_resolver._CONFIG_TO_SHAPE). The new prompt also fixes
   the old code's worst bug: it must now return WHICH ticket matched
   (ticket_name), not just match/no_match — the old code always linked
   existing_tickets[0] regardless of what the model actually meant.

Idempotent throughout; safe to re-run.
"""

import frappe

AGENT_CONFIG_NAME = "Error Log Ticket Agent"
AGENT_ID = "error_log_ticket_agent"
AI_MODEL = "claude-haiku-4-5-20251001"

TRIAGE_SCRIPT_NAME = "Error Log Agent - Triage"
APPLY_AI_RESULT_SCRIPT_NAME = "Error Log Agent - Apply AI Result"

TRIAGE_SCRIPT = '''# Script Task: Triage: Kill Switch + Exact Dedup (error_log_ticket_triage_process)
#
# doc is the Error Log that started this instance. Writes:
#   outcome = "disabled" | "linked_duplicate" | "needs_ai"
#   on needs_ai: error_title, error_details, existing_tickets_json — the
#   fields the AI Agent Task's prompt renders.
import json

enabled = frappe.db.get_value("AI Agent Configuration", {"agent_id": "error_log_ticket_agent"}, "enabled")

if not enabled:
    result["outcome"] = "disabled"
else:
    title = (doc.method or "").strip()
    match_name = frappe.db.get_value(
        "HD Ticket",
        {"subject": title, "status": ["not in", ["Resolved", "Closed"]]},
        "name",
    )

    if match_name:
        frappe.db.set_value("Error Log", doc.name, "hd_ticket", match_name)
        result["outcome"] = "linked_duplicate"
        result["ticket_name"] = match_name
    else:
        # Cap what reaches the LLM. Confirmed live: this site has 424 open HD
        # Tickets, and serializing all of them blew the prompt to ~628k tokens
        # (Claude's limit is 200k) - the AI Agent Task failed on every single
        # run with FAILED_MODEL_CALL, and Apply AI Result's fail-open default
        # (no_match) silently created a fresh ticket every time instead of
        # ever actually finding a similarity match. Recent tickets are the
        # most likely duplicates anyway; descriptions are truncated too, since
        # a handful carry full stack traces.
        open_tickets = frappe.get_all(
            "HD Ticket",
            filters={"status": ["not in", ["Resolved", "Closed"]]},
            fields=["name", "subject", "description"],
            order_by="creation desc",
            limit_page_length=50,
        )
        result["outcome"] = "needs_ai"
        result["error_title"] = title
        result["error_details"] = (doc.error or "")[:2000]
        result["existing_tickets_json"] = json.dumps([
            {"name": t.name, "subject": t.subject, "description": (t.description or "")[:500]}
            for t in open_tickets
        ])
'''

APPLY_AI_RESULT_SCRIPT = '''# Script Task: Apply AI Result (error_log_ticket_triage_process)
#
# Reads similarity_result (the AI Agent Task's structured {decision,
# ticket_name} output) and either links the matched ticket or creates a new
# one. custom_ticket_category is mandatory on the current HD Ticket schema;
# custom_is_doctype_related no longer exists on it (both confirmed live,
# 2026-09-09) — the old onefm_mcp code set the retired field and never set
# the mandatory one.
import json

ai_result = task_data.get("similarity_result") or {}
if isinstance(ai_result, str):
    try:
        ai_result = json.loads(ai_result)
    except Exception:
        ai_result = {}

decision = (ai_result.get("decision") or "no_match").strip().lower()
ticket_name = ai_result.get("ticket_name")

if decision == "match" and ticket_name and frappe.db.exists("HD Ticket", ticket_name):
    frappe.db.set_value("Error Log", doc.name, "hd_ticket", ticket_name)
    result["outcome"] = "linked_ai"
    result["ticket_name"] = ticket_name
else:
    admin_email = frappe.db.get_value("User", "Administrator", "email")
    ticket = frappe.new_doc("HD Ticket")
    ticket.subject = task_data.get("error_title") or "Error Log"
    ticket.description = (
        "Source -> Link of Error Log: " + frappe.utils.get_url() + "/app/error-log/" + doc.name
        + "\\n\\n" + (task_data.get("error_details") or "")
    )
    ticket.status = "Draft"
    ticket.custom_reference_doctype = "Error Log"
    ticket.custom_ticket_category = "Process Issue"
    ticket.raised_by = admin_email
    # No ignore_permissions: the platform's script-security gate always blocks
    # it. Unnecessary anyway - HD Ticket grants create to role "All", so any
    # authenticated user's session (virtually every real error) can create
    # this ticket; a Guest-triggered error instead hits the engine's own
    # caught-exception path (BPMN queued start failed: ...), which the start
    # condition's recursion guard already excludes.
    ticket.insert()
    frappe.db.set_value("Error Log", doc.name, "hd_ticket", ticket.name)
    result["outcome"] = "created"
    result["ticket_name"] = ticket.name
'''

NEW_SYSTEM_PROMPT = """You are an error-log deduplication agent for ONE-FM's Helpdesk. You compare a newly logged error against a list of currently open HD Tickets and decide whether it is the same underlying issue as one of them.

Process:
1. For each existing ticket, compare the new error's title against the ticket's subject. If the new error's title is an exact substring (or full match) of a ticket's subject, that ticket is a candidate — go to step 2 for it. If none qualify, decide no_match.
2. Compare the new error's details against that candidate ticket's description. If the details are an exact substring (or full match) of the description, decide match on that ticket. Otherwise decide no_match.
3. Do not match on a generic title alone (e.g. "ValidationError", "TypeError") unless the details are also a close match — the match must be specific enough to be a real duplicate, not just the same exception class.

Respond with ONLY a JSON object matching the schema you were given: {"decision": "match" or "no_match", "ticket_name": the matched ticket's "name" field when decision is "match", otherwise null}. Never invent a ticket_name that was not in the list you were given. No markdown, no code fences, no other text."""


def _ensure_hd_ticket_field() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	if frappe.db.exists("Custom Field", {"dt": "Error Log", "fieldname": "hd_ticket"}):
		return
	create_custom_field(
		"Error Log",
		{
			"fieldname": "hd_ticket",
			"label": "HD Ticket",
			"fieldtype": "Link",
			"options": "HD Ticket",
			"insert_after": "trace_id",
		},
	)


def _ensure_script(name: str, script: str) -> None:
	if frappe.db.exists("Server Script", name):
		doc = frappe.get_doc("Server Script", name)
		if (doc.script or "").strip() != script.strip():
			doc.script = script
			doc.save(ignore_permissions=True)
		return
	frappe.get_doc({
		"doctype": "Server Script",
		"name": name,
		"script_type": "API",
		"script": script,
		"disabled": 0,
	}).insert(ignore_permissions=True)


def _repoint_agent_config() -> None:
	"""Same shape as promote_threat_agents_to_bpmn.py (WI-002203): this config
	was seeded directly by onefm_mcp's old patch and never walked the platform's
	Agent Creation Process (that map isn't tracked in this repo at all — moved
	between environments by hand — and no site here holds the creation grant).
	compile_process_model requires enabled=1 and lifecycle_status=Live on any
	linked AI Agent Configuration, so this runs the SAME validation the
	creation process would (validate_agent_config — identity, prompt, model +
	credentials, a live provider test call) and stamps the real result,
	rather than inventing a bypass. agent_type=Background also matters here:
	this agent has no chat surface (it's one step inside the triage map), and
	Background is what exempts it from the Chat-only adversarial gate even
	within the real creation process (agent_provisioning.provision_agent).
	"""
	if not frappe.db.exists("AI Agent Configuration", AGENT_CONFIG_NAME):
		frappe.log_error(
			title="wi_002204_error_log_ticket_triage_setup: agent config missing",
			message=f"No AI Agent Configuration '{AGENT_CONFIG_NAME}' on this site — "
			"onefm_mcp's seed patch should have created it. Run that first.",
		)
		return

	doc = frappe.get_doc("AI Agent Configuration", AGENT_CONFIG_NAME)
	changed = False
	if doc.agent_type != "Background":
		doc.agent_type = "Background"
		changed = True
	if doc.ai_model != AI_MODEL:
		doc.ai_model = AI_MODEL
		changed = True
	if (doc.system_prompt or "").strip() != NEW_SYSTEM_PROMPT.strip():
		doc.system_prompt = NEW_SYSTEM_PROMPT
		changed = True
	if (doc.get("required_variables") or "[]") != "[]":
		doc.required_variables = "[]"
		changed = True
	if not doc.enabled:
		doc.enabled = 1
		changed = True
	if changed:
		doc.save(ignore_permissions=True)
		frappe.cache.delete_value(f"agent_config:{AGENT_ID}")

	from one_bpmn.agents.agent_provisioning import validate_agent_config

	try:
		result = validate_agent_config(AGENT_CONFIG_NAME, test_provider=True)
	except Exception:
		frappe.log_error(
			title=f"{AGENT_CONFIG_NAME} migration: validation raised",
			message=frappe.get_traceback(),
		)
		return

	status = "Live" if result.get("ok") else "Needs Attention"
	frappe.db.set_value(
		"AI Agent Configuration", AGENT_CONFIG_NAME, "lifecycle_status", status, update_modified=False
	)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
	if status != "Live":
		frappe.log_error(
			title=f"{AGENT_CONFIG_NAME} migration: not promoted to Live ({AGENT_ID})",
			message="\n".join(result.get("errors", [])) or "validate_agent_config returned not-ok",
		)


def execute():
	_ensure_hd_ticket_field()
	_ensure_script(TRIAGE_SCRIPT_NAME, TRIAGE_SCRIPT)
	_ensure_script(APPLY_AI_RESULT_SCRIPT_NAME, APPLY_AI_RESULT_SCRIPT)
	_repoint_agent_config()
	frappe.db.commit()
