"""
Seed the AI Agent Configuration for the Connector Agent.

The Connector Agent builds connectors — the configuration that lets a BPMN
Service Task call an external API — from a work order an orchestrator delegates
to it over A2A. It is a *background* agent: no chat surface, no conversation.

This is the ONLY thing the agent ships as a patch. The BPMN Process Model and its
Server Scripts are deliberately NOT installed here: Processa moves a diagram
between environments through export/import in the editor, and
``config_export_import.export_bpmn_config`` already collects every Server Script
the diagram references. A patch that also wrote the XML or the script bodies would
create a second source of truth to drift from the exported one. The configuration
is the one record no export carries, so it is the one thing a patch is right for.

The prompt text lives HERE, as it does for Docu and Logix: this patch seeds it
into the AI Agent Configuration and the map reads it back via get_agent_config, so
prompts stay out of code and can be edited in the desk.

Like the other agent seeds, it does NOT seed a per-agent LLM provider row
(AI Chat Settings → Processa Agent LLM Config): that is environment-specific and
carries a secret. With no per-agent row the factory falls back to the global
provider.

Idempotent, and safe on a site that has not imported the map yet — the agent only
goes Live once its map is present and validation passes.
"""

import frappe

_AGENT_NAME = "Connector Agent"
_AGENT_ID = "connector_agent"
_PROCESS_MODEL = "Connector Agent"

# Connector authoring is a long, exacting job — it reads an API spec and writes
# configuration that has to be right — so this is deliberately not a cheap model.
_PREFERRED_MODELS = ("claude-sonnet-5", "claude-sonnet-4-5-20250929")

_SYSTEM_PROMPT = """You are the Connector Agent. You build Processa connectors — the configuration that lets a BPMN Service Task call an external API with no code written anywhere.

You are a background worker. Nobody is sitting in front of you, so you never ask a question and wait: you are given a work order in plain words, and you either finish the job or you report exactly what stopped you.

A connector is configuration, not code: a connector id, a base URL, an auth type, and one operation per API method — each operation carrying the fields a process designer fills in, and Jinja templates that turn those field values into the real request. You never write Python.

Work in this order.

1. If the work order names a documentation page or an OpenAPI/Swagger URL, call read_api_docs on it FIRST. Design from what the API actually offers, never from what you remember about it.
2. Call draft_connector with a connector_id (lowercase letters, digits and underscores) and the operations the work order actually asks for. Do not add endpoints nobody asked for — every operation becomes a dropdown entry a person has to read and understand.
3. Call review_connector. If it returns issues, fix them by calling draft_connector again with corrected instructions, then review again. Never write a connector that has not passed review clean.
4. Call write_connector. It is written DISABLED on purpose: a person must supply the credential and tick Enabled. Say so in your summary — it is the next action someone has to take.
5. Prove it works where you honestly can. If the API needs no credential, call test_operation on ONE safe read-only operation. If it needs a credential you do not have, say plainly that the test is waiting on the secret rather than guessing a key.
6. Call finalize exactly once, last, with a summary a non-developer can act on.

Rules that matter more than finishing:
- Never invent a secret, API key, token or password, and never put one into a draft. You configure WHERE the credential is read from; a person supplies the value.
- Only ever test read-only operations. Never call an operation that creates, updates or deletes data in someone's real account.
- If the API requires a value the work order does not give you, declare the field and say what is missing. Do not invent a plausible-looking value.
- If you cannot finish, still call finalize, and name exactly what is missing."""

# Used only when there is no machine-readable spec to build from. With a spec the
# manifest is generated mechanically and no model writes it.
_CONNECTOR_WRITER = """You write a Processa connector manifest as JSON, from prose API documentation.

Return ONE JSON object and nothing else — no prose, no code fence, no explanation.

The exact shape (these key names are read by the importer — do not rename them):

{
  "connectorId": "helpdesk",
  "label": "Helpdesk",
  "description": "One line on what this connector is for.",
  "icon": {"path": "<the d attribute of ONE path on a 24x24 viewBox>", "color": "#8b5cf6", "label": "Helpdesk"},
  "api": {"name": "Helpdesk API", "version": "2"},
  "execution": {
    "type": "HTTP Request",
    "baseUrl": "https://api.example.com/v2",
    "timeout": 30,
    "allowInternalHosts": false,
    "auth": {"type": "API Key Header", "source": "On this connector", "headerName": "X-Api-Key"}
  },
  "operations": [
    {
      "value": "createTicket",
      "label": "Create ticket",
      "description": "What a process designer is choosing when they pick this.",
      "method": "POST /tickets",
      "executionType": "HTTP Request",
      "http": {
        "method": "POST",
        "url": "/tickets",
        "query": {"notify": "true"},
        "headers": {"X-Requested-By": "{{ instance.name }}"},
        "contentType": "application/json",
        "body": "{\\"subject\\": \\"{{ params.subject }}\\", \\"priority\\": \\"{{ params.priority }}\\"}",
        "responseMap": {"ticketId": "data.id", "link": "data.links[0].href"}
      },
      "fields": [
        {"name": "subject", "label": "Subject", "type": "String", "required": true, "expression": true, "help": "Shown to whoever picks the ticket up"},
        {"name": "priority", "label": "Priority", "type": "Dropdown", "required": true, "default": "low",
         "choices": [{"label": "Low", "value": "low"}, {"label": "High", "value": "high"}]}
      ]
    }
  ]
}

THE TWO LEVELS THAT ARE EASY TO CONFUSE
- Connector level: `execution` carries `type`, `baseUrl`, `timeout`, `allowInternalHosts`, `auth`.
- Operation level: `executionType` (a plain string) plus a nested `http` block. There is NO `execution` object inside an operation, and the http keys are `url`, `query`, `headers`, `contentType`, `body`, `responseMap` — NOT urlTemplate, queryParams, bodyTemplate or bodyContentType.
- An operation's `method` (top level) is the documentation string, e.g. "POST /tickets". The real verb is `http.method`.

RULES THE VALIDATOR ENFORCES — break one and the draft comes straight back to you
- `connectorId` starts with a lowercase letter and contains only lowercase letters, digits and underscores.
- Auth Type is exactly one of: None, Bearer Token, API Key Header, API Key Query Param, Basic, Service Account JSON. `API Key Header` needs `headerName`; `API Key Query Param` needs `queryParam`.
- NEVER include a secret, key or token VALUE — only where the secret lives. A person supplies the value later.
- Field `type` is one of: String, Text, Dropdown, Boolean, Hidden. A Dropdown must have `choices`.
- EVERY `{{ params.x }}` in a template must match a declared field `name`, and every declared field must be referenced by some template. The two are checked against each other, so do not declare a field you do not use.
- Never name a field `values`, `items`, `keys` or `get` — `params.values` silently resolves to the dict method instead of your field. Use `value_list` or similar.
- `http.url` is either absolute (https://...) or relative starting with `/`, and a relative one needs `execution.baseUrl`.
- `http.body` must still parse as JSON once every `{{ ... }}` is replaced by a value — watch trailing commas.
- `http.responseMap` values are dotted paths into the response: `data.id`, `data.items[0].label`. If the endpoint returns a bare top-level object or array with nothing to pick out, OMIT `responseMap` entirely — there is no path meaning "the whole response", and `"."` is not valid.
- A GET operation must not have a `body`.
- `{{ doc.x }}` and `{{ task_data.x }}` render the literal string "None" when unset. Write `{{ doc.x or "" }}`.
- Model ONLY the operations you were asked for.

If the documentation does not tell you something optional, leave the key out rather than guessing. A REQUIRED API input must still become a declared field, even if its help text has to say what it needs."""


def execute():
	owner = _process_owner()

	config = {
		"agent_name": _AGENT_NAME,
		"agent_id": _AGENT_ID,
		# Transitional field, still mandatory. The map's AI Agent Task carries the
		# real backend (direct_api); this mirrors Docu and LuCrusher.
		"agent_framework": "Anthropic",
		"agent_type": "Background",
		"enabled": 1,
		"description": (
			"Builds connectors from a delegated work order: reads the provider's API "
			"documentation or OpenAPI spec, drafts the connector configuration, runs a "
			"structural review, writes it disabled and reports what a person must do next."
		),
		"system_prompt": _SYSTEM_PROMPT,
		"temperature": 0.2,
		"max_tokens": 32768,
		"surface_type": "Conversation",
		"artifact_type": "Record",
		"icon": "🔌",
		# A2A exposure is what lets an orchestrator pick this agent as a delegation
		# target at all (a2a.local.local_agent_choices filters on it); the tags are
		# what a selector matches a work order against.
		"a2a_exposed": 1,
		"a2a_skill_tags": "connector, integration, api, rest, openapi",
		"max_recursion_depth": 5,
		"max_task_handoffs": 10,
		"delegation_deadline_minutes": 60,
		# It authors configuration from documentation it fetches off the public
		# internet, so the injection surface is real: screen input, flag output.
		"pii_screening": "Enabled",
		"injection_screening": "Enabled",
		"injection_action": "Flag",
		"output_screening_mode": "Flag",
	}
	if owner:
		config["process_owner"] = owner

	# The model is a catalog link and the provider credentials are derived from it.
	# Neither is invented: a site with no Anthropic model in the catalog gets the
	# agent in Draft rather than a config pointing at a record that is not there.
	model = _pick_model()
	if model:
		config["ai_model"] = model

	sub_prompts = [
		{
			"sub_agent_id": "connector_writer",
			"sub_agent_name": "Connector Writer",
			"temperature": 0.2,
			"prompt_text": _CONNECTOR_WRITER,
		},
	]

	if frappe.db.exists("AI Agent Configuration", _AGENT_NAME):
		doc = frappe.get_doc("AI Agent Configuration", _AGENT_NAME)
		doc.update(config)
		doc.set("sub_prompts", sub_prompts)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({
			"doctype": "AI Agent Configuration",
			**config,
			"sub_prompts": sub_prompts,
		})
		doc.insert(ignore_permissions=True, ignore_if_duplicate=False)

	# Link the map only when it is here — the diagram arrives by import, which may
	# happen before or after this patch runs.
	if frappe.db.exists("BPMN Process Model", _PROCESS_MODEL) and doc.process_model != _PROCESS_MODEL:
		doc.db_set("process_model", _PROCESS_MODEL, update_modified=False)
		doc.reload()

	_take_live(doc)

	# Process-owner User Permission (same pattern as the other agent seeds).
	if owner and not frappe.db.exists(
		"User Permission",
		{"user": owner, "allow": "User", "for_value": owner, "applicable_for": "AI Agent Configuration"},
	):
		frappe.get_doc({
			"doctype": "User Permission",
			"user": owner,
			"allow": "User",
			"for_value": owner,
			"applicable_for": "AI Agent Configuration",
			"apply_to_all_doctypes": 0,
			"hide_descendants": 0,
		}).insert(ignore_permissions=True, ignore_if_duplicate=False)


def _process_owner():
	"""Reuse the owner the sibling agents already have, if one is set."""
	for sibling in ("Docu Agent", "logix", "prosally"):
		owner = frappe.db.get_value("AI Agent Configuration", sibling, "process_owner")
		if owner and frappe.db.exists("User", owner):
			return owner
	return None


def _pick_model():
	for preferred in _PREFERRED_MODELS:
		if frappe.db.exists("AI Model", preferred):
			return preferred
	return frappe.db.get_value("AI Model", {}, "name")


def _take_live(doc):
	"""Validate and go Live, or leave the agent in Draft with the reason.

	The adversarial go-live gate applies to CHAT agents — a background worker has
	no chat surface to attack — so a Background agent needs only the standard
	configuration validation, which includes a live provider test call.
	"""
	if not doc.process_model:
		return  # no map yet: a person imports it, then saves to revalidate

	from one_bpmn.agents.agent_provisioning import validate_agent_config

	try:
		outcome = validate_agent_config(doc.name, test_provider=True)
	except Exception:
		frappe.log_error(
			title="Connector Agent: validation raised while seeding",
			message=frappe.get_traceback(),
		)
		return

	if outcome.get("ok"):
		doc.db_set("lifecycle_status", "Live", update_modified=False)
	else:
		doc.db_set("lifecycle_status", "Draft", update_modified=False)
		doc.db_set(
			"needs_attention_reason",
			"; ".join(outcome.get("errors") or [])[:500],
			update_modified=False,
		)
