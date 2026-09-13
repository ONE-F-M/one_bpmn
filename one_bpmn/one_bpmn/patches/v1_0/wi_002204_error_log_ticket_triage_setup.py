"""
WI-002204: setup for the Error Log Ticket Triage process map, migrated off
onefm_mcp's ErrorLogTicketAgent (Google ADK).

Two things this map needs that don't come from importing the diagram alone,
because they are DB records rather than diagram content:

1. Error Log.hd_ticket — the agent has always written this field, but no
   fixture/patch for it exists anywhere in either app's history; it only
   exists today as an ad hoc Custom Field on one site's DB. Captured here so
   the migration is reproducible on a fresh site.

2. AI Agent Configuration "Error Log Ticket Agent" (already seeded by
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

The map's two Script Tasks (Triage, Apply AI Result) are NOT created here —
they travel with the diagram itself, through the platform's own
export_bpmn_config/import_bpmn_config (a companion _config.json alongside the
.bpmn export, same as document_request_config.json). Duplicating them as
string literals in this patch would drift the moment either is edited through
that path instead.

The AI Model isn't hardcoded either, for the same portability reason: which
model is actually enabled with working credentials differs by site (this
repo's own local dev site and the BA site do not necessarily agree on one).
Instead this borrows whatever model an already-Live Logix Background agent is
using on THIS site at patch-run time, since Logix is a proven-working
reference wherever this patch actually runs.

Idempotent throughout; safe to re-run.
"""

import frappe

AGENT_CONFIG_NAME = "Error Log Ticket Agent"
AGENT_ID = "error_log_ticket_agent"

# A known-Live Background Logix agent to borrow a working ai_model from,
# rather than hardcoding a model name that may not exist/be enabled on every
# site this patch runs on (confirmed: local and BA do not necessarily agree).
_REFERENCE_AGENT_ID = "logix_script_writer"

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


def _working_ai_model() -> str | None:
	"""Whatever ai_model a known-Live Logix Background agent is actually using
	on this site right now - portable across sites instead of a name that may
	not exist/be enabled everywhere. None if Logix isn't Live here either (an
	unlikely but real "nothing to borrow from" case, left for the caller to
	log rather than silently guessing)."""
	return frappe.db.get_value(
		"AI Agent Configuration",
		{"agent_id": _REFERENCE_AGENT_ID, "lifecycle_status": "Live"},
		"ai_model",
	)


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
	working_model = _working_ai_model()
	if not working_model:
		frappe.log_error(
			title=f"{AGENT_CONFIG_NAME} migration: no reference model found",
			message=f"'{_REFERENCE_AGENT_ID}' isn't Live on this site, so there's no "
			"known-working ai_model to borrow. Set AI Agent Configuration "
			f"'{AGENT_CONFIG_NAME}'.ai_model by hand, or get a Logix agent Live first.",
		)
	elif doc.ai_model != working_model:
		doc.ai_model = working_model
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
	_repoint_agent_config()
	frappe.db.commit()
