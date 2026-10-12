"""The Error Log Ticket Agent's open tickets before today move into its cached system prompt.

The Triage script splits the open tickets into those created before today (the newest 40, oldest
first, so the list stays the same all day) and today's. The older list goes into the agent's system
prompt, which carries the cache marker; today's list stays in the Similarity Check user message with
the new error. Idempotent.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.chat_agents_post_failed_turn_error import apply_edit

TRIAGE = "Error Log Agent - Triage"
AGENT = "Error Log Ticket Agent"
AGENT_ID = "error_log_ticket_agent"
MAP = "Error Log Ticket Triage"
SHAPE = "ai_similarity_check"

# The BA script's own comment line uses an em dash, so the anchor has to as well.
EM_DASH = chr(0x2014)
TRIAGE_FIELDS = f"#   on needs_ai: error_title, error_details, existing_tickets_json {EM_DASH} the\n"
TRIAGE_FIELDS_SPLIT = (
	"#   on needs_ai: error_title, error_details, older_tickets_json, todays_tickets_json - the\n"
)

TRIAGE_TICKETS = """        open_tickets = frappe.get_all(
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
"""
TRIAGE_TICKETS_SPLIT = """        # Tickets before today go to the system prompt, which is cached, so they keep one order all day.
        today = frappe.utils.today()
        older_tickets = frappe.get_all(
            "HD Ticket",
            filters={"status": ["not in", ["Resolved", "Closed"]], "creation": ["<", today]},
            fields=["name", "subject", "description"],
            order_by="creation desc",
            limit_page_length=40,
        )
        older_tickets.reverse()
        todays_tickets = frappe.get_all(
            "HD Ticket",
            filters={"status": ["not in", ["Resolved", "Closed"]], "creation": [">=", today]},
            fields=["name", "subject", "description"],
            order_by="creation desc",
            limit_page_length=10,
        )
        result["outcome"] = "needs_ai"
        result["error_title"] = title
        result["error_details"] = (doc.error or "")[:2000]
        result["older_tickets_json"] = json.dumps([
            {"name": t.name, "subject": t.subject, "description": (t.description or "")[:500]}
            for t in older_tickets
        ])
        result["todays_tickets_json"] = json.dumps([
            {"name": t.name, "subject": t.subject, "description": (t.description or "")[:500]}
            for t in todays_tickets
        ])
"""

PROMPT_LAST_LINE = "No markdown, no code fences, no other text."
PROMPT_OLDER_TICKETS = (
	PROMPT_LAST_LINE
	+ "\n\nOpen HD Tickets created before today (JSON array of {name, subject, description}, oldest first)."
	" Today's open tickets are in the user message; treat the two lists as one:\n{{ older_tickets_json }}"
)

USER_PROMPT = (
	"New error:&#10;  title: {{ error_title }}&#10;  details: {{ error_details }}&#10;&#10;"
	"Existing open HD Tickets (JSON array of {name, subject, description}):&#10;{{ existing_tickets_json }}&#10;&#10;"
	"Respond with the JSON object your instructions specify."
)
USER_PROMPT_TODAY = (
	"New error:&#10;  title: {{ error_title }}&#10;  details: {{ error_details }}&#10;&#10;"
	"Open HD Tickets created today (JSON array of {name, subject, description}):&#10;{{ todays_tickets_json }}&#10;&#10;"
	"Respond with the JSON object your instructions specify."
)


def execute():
	targets = (
		(
			"Server Script",
			TRIAGE,
			"script",
			[(TRIAGE_FIELDS, TRIAGE_FIELDS_SPLIT), (TRIAGE_TICKETS, TRIAGE_TICKETS_SPLIT)],
		),
		("AI Agent Configuration", AGENT, "system_prompt", [(PROMPT_LAST_LINE, PROMPT_OLDER_TICKETS)]),
		("BPMN Process Model", MAP, "bpmn_xml", [(USER_PROMPT, USER_PROMPT_TODAY)]),
	)
	if not all(frappe.db.exists(doctype, name) for doctype, name, _field, _edits in targets):
		return
	edited = {}
	for doctype, name, field, edits in targets:
		text = _edited(frappe.db.get_value(doctype, name, field) or "", edits)
		if text is None:
			frappe.log_error(
				title="error_log_ticket_agent_caches_older_tickets: anchor not found",
				message=f"{doctype} {name} no longer matches in {field}; nothing was changed on this site.",
			)
			return
		edited[doctype] = text

	triage = frappe.get_doc("Server Script", TRIAGE)
	if triage.script != edited["Server Script"]:
		triage.script = edited["Server Script"]
		triage.save(ignore_permissions=True)
	frappe.db.set_value("AI Agent Configuration", AGENT, "system_prompt", edited["AI Agent Configuration"])
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
	model = frappe.get_doc("BPMN Process Model", MAP)
	if model.bpmn_xml != edited["BPMN Process Model"]:
		from one_bpmn.api.compilation import compile_process_model

		model.bpmn_xml = edited["BPMN Process Model"]
		model.save(ignore_permissions=True)
		compile_process_model(MAP)


def _edited(text: str, edits: list) -> str | None:
	"""Each (anchor, replacement) applied in turn; None when any anchor is missing."""
	for anchor, replacement in edits:
		text = apply_edit(text, anchor, replacement)
		if text is None:
			return None
	return text
