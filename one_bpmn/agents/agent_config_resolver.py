# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Resolve an AI Agent Configuration reference on an AI task/selector shape
(WI-001637, live-link amendment 2026-07-17).

A shape may set ``aiAgentConfig`` (a link to an AI Agent Configuration) as
an alternative to entering a raw provider. The link is LIVE:

* **At dispatch, the configuration is authoritative** for agent-level
  fields (system prompt, provider, model, temperature, max tokens, and —
  since WI-001793 — every memory setting) — ``resolve_dispatch_overrides``
  supplies them and the dispatchers overlay them onto the shape's
  attributes. The shape's copies are an editing view and the fallback when
  the configuration has been deleted. Remaining shape-only fields (output
  variable, response format/schema, retries, tool wiring) describe the
  task, not the agent, and stay shape-owned.
* **Selecting a configuration in the editor** copies its current values
  into the shape's fields (``get_agent_config_for_shape``) so the designer
  sees and can edit what will run.
* **Saving the editor modal writes agent-level edits back** to the
  configuration (``update_agent_config_from_shape``). Writing back to a
  Live agent re-runs the AI Agent Creation Process so its provisioned chat
  map picks up the change; agents waiting in Needs Attention are resumed
  by the ordinary Edit_Action message their save emits.

Tools are NOT sourced from the config — the diagram's ad-hoc shapes remain
the toolkit.
"""

import frappe
from frappe import _
from frappe.utils import cint

from one_bpmn.agents.agent_provisioning import is_chat_startable_map

# Which config field feeds which shape attribute. Only executable fields
# with a task-shape equivalent are mapped; chat-only metadata (chat mode
# label, icon, roles, lifecycle, eval suite, sample prompts) has no shape
# meaning and is intentionally omitted.
_CONFIG_TO_SHAPE = {
	"system_prompt": "aiSystemPrompt",
	"temperature": "aiTemperature",
	"max_tokens": "aiMaxTokens",
	# WI-001793: memory settings live on the agent, not the diagram. Every value
	# here is blank-by-default so an unset field falls through to the shape's
	# older XML copy rather than silently overriding it with a default.
	# ``long_term_memory`` needs no translation — the dispatcher's _cfg_truthy
	# already reads "Enabled" as true and "Disabled" as false.
	"conversation_store": "aiConversationStore",
	"long_term_memory": "aiLongTermMemory",
	"memory_scope": "aiMemoryScope",
	"memory_write_mode": "aiMemoryWriteMode",
	"memory_distill_model": "aiMemoryDistillModel",
	"memory_reconcile_model": "aiMemoryReconcileModel",
}

# Shape attributes the modal may write back, and the config fields they land
# in. WI-001655 inverted the old rule: the MODEL is now the agent's editable
# pick (a Link into the AI Model catalog), while aiProvider is deliberately
# absent — the provider is derived from the model's credentials link, so "to
# change the provider, change the model".
_SHAPE_TO_CONFIG = {
	"aiSystemPrompt": "system_prompt",
	"aiTemperature": "temperature",
	"aiMaxTokens": "max_tokens",
	"aiModel": "ai_model",
	# WI-001793: the modal's Memory section now persists here instead of onto
	# the BPMN XML, so the agent is the single place memory is configured.
	"aiConversationStore": "conversation_store",
	"aiContextMaxMessages": "context_max_messages",
	"aiLongTermMemory": "long_term_memory",
	"aiMemoryScope": "memory_scope",
	"aiMemoryWriteMode": "memory_write_mode",
	"aiMemoryDistillModel": "memory_distill_model",
	"aiMemoryReconcileModel": "memory_reconcile_model",
}

# Guard rail categories, mirroring the AI Agent Guard Rail Select options
# (WI-001639). Kept here so the create endpoint can reject a bogus category
# before doc validation turns it into a hard failure.
_GUARDRAIL_CATEGORIES = (
	"Code Quality",
	"Performance",
	"Cost & Tokens",
	"Safety",
	"Output Format",
	"Other",
)

# The platform process that carries an agent Draft -> Live is no longer assumed
# by name. It is whatever the single grant-holding AI Agent Configuration
# (can_create_agents = 1) links in agent_creation_process, so a site is free to
# name and rebuild that map without touching code. The doctype's
# validate_agent_creation_grant keeps the grant unique, so this lookup returns
# one answer or none.


def get_creation_process_model() -> str | None:
	"""Return the active agent-creation process map, or None when no agent
	holds the creation grant (or its linked map is missing/inactive).

	None is a first-class answer, not an error: a site with no grant simply
	cannot create agents yet, and every caller degrades rather than blocks.
	"""
	model = frappe.db.get_value(
		"AI Agent Configuration",
		{"can_create_agents": 1, "enabled": 1},
		"agent_creation_process",
	)
	if not model:
		return None
	return model if frappe.db.get_value("BPMN Process Model", model, "is_active") else None


def get_creation_grant_holder() -> str | None:
	"""Name of the configuration holding the agent-creation grant, or None.

	Distinct from get_creation_process_model: a grant can be held while its
	map is inactive, and the two failures need different messages.
	"""
	return frappe.db.get_value(
		"AI Agent Configuration", {"can_create_agents": 1, "enabled": 1}, "name"
	)


def config_field_map(config_name: str) -> dict:
	"""Return the shape-attribute values for a configuration (provider, model,
	prompt, params). Empty dict if the config is missing."""
	if not config_name or not frappe.db.exists("AI Agent Configuration", config_name):
		return {}
	cfg = frappe.get_doc("AI Agent Configuration", config_name)
	out = {}
	for cfield, sattr in _CONFIG_TO_SHAPE.items():
		val = cfg.get(cfield)
		if val not in (None, ""):
			out[sattr] = val

	# Int fields have no blank state — 0 means "not configured here", so it must
	# not override the shape's value the way a real setting would (WI-001793).
	if cint(cfg.get("context_max_messages")):
		out["aiContextMaxMessages"] = cfg.context_max_messages
	if cfg.ai_provider_credentials:
		out["aiProvider"] = cfg.ai_provider_credentials
	# WI-001655: the model is the agent's own pick from the AI Model catalog
	# (the record name IS the model id); the provider above is derived from
	# that model's credentials link at save time.
	if cfg.get("ai_model"):
		out["aiModel"] = cfg.ai_model
	return out


def resolve_dispatch_overrides(config_name: str) -> dict:
	"""Live values a linked configuration contributes at dispatch time.

	Called by the AI Agent Task and AI Task Selector dispatchers when the
	shape carries ``aiAgentConfig``. Never raises — a deleted/broken config
	logs once and returns {} so the shape's own copies act as the fallback
	and the task still runs.
	"""
	if not config_name:
		return {}
	try:
		overrides = config_field_map(config_name)
		if not overrides:
			frappe.log_error(
				title=f"AI task links missing AI Agent Configuration: {config_name}",
				message="Falling back to the shape's own field copies.",
			)
		return overrides
	except Exception:
		frappe.log_error(
			title=f"AI Agent Configuration resolution failed: {config_name}",
			message=frappe.get_traceback(),
		)
		return {}


@frappe.whitelist()
def get_agent_config_for_shape(config_name: str) -> dict:
	"""Whitelisted: the editor calls this on selecting a config to copy its
	current values into the shape's fields (the designer's editing view)."""
	frappe.has_permission("AI Agent Configuration", "read", throw=True)
	return config_field_map(config_name)


@frappe.whitelist()
def update_agent_config_from_shape(config_name: str, fields: str | dict) -> dict:
	"""Whitelisted: write agent-level edits from the editor modal back to the
	linked AI Agent Configuration (WI-001637 live-link).

	``fields`` maps shape attributes (aiSystemPrompt, aiTemperature,
	aiMaxTokens, aiProvider) to their new values; anything outside
	``_SHAPE_TO_CONFIG`` is ignored. Saving goes through doc.save() so
	validation runs, the config cache clears, and the Edit_Action message
	fires (resuming any Needs-Attention creation instance).

	If the agent was Live and something changed, a fresh AI Agent Creation
	Process instance is started so the provisioned chat map is rebuilt with
	the new values — unless one is already running for this agent.
	"""
	if not config_name:
		frappe.throw(_("config_name is required"))
	if isinstance(fields, str):
		fields = frappe.parse_json(fields) or {}

	doc = frappe.get_doc("AI Agent Configuration", config_name)
	doc.check_permission("write")

	changed = []
	for sattr, cfield in _SHAPE_TO_CONFIG.items():
		if sattr not in fields:
			continue
		value = fields[sattr]
		if cfield == "temperature" and value not in (None, ""):
			value = frappe.utils.flt(value)
		if cfield == "max_tokens" and value not in (None, ""):
			value = frappe.utils.cint(value)
		# WI-001793: the modal's number input hands back a string; 0/blank means
		# "not set here" and must stay 0 so dispatch falls through to the shape.
		if cfield == "context_max_messages":
			value = frappe.utils.cint(value)
		# Old diagrams carry model ids baked into the shape before the AI Model
		# catalog existed (WI-001655). Letting doc.save() hit the Link
		# validation surfaces a raw LinkValidationError — say what is actually
		# wrong instead.
		if (
			cfield in ("ai_model", "memory_distill_model", "memory_reconcile_model")
			and value
			and not frappe.db.exists("AI Model", value)
		):
			frappe.throw(
				_(
					"'{0}' is not in the AI Model catalog — the task shape carries an "
					"outdated model id. Pick a model from the dropdown and save again."
				).format(value)
			)
		if doc.get(cfield) != value:
			doc.set(cfield, value)
			changed.append(cfield)

	if not changed:
		return {"ok": True, "updated": [], "reprovisioned": False}

	# Re-provisioning is a chat-map concern: it re-runs the creation process
	# so a Live CHAT agent picks up the change. Background agents (Live via
	# auto-go-live, WI-001652) have no map to rebuild — never re-provision them.
	was_live = doc.lifecycle_status == "Live" and doc.agent_type == "Chat"
	doc.save()

	reprovisioned = False
	if was_live:
		reprovisioned = _start_reprovision(doc.name)

	return {"ok": True, "updated": changed, "reprovisioned": reprovisioned}


# The create endpoint's payload contract as DATA (WI-001649): the AI Assistant
# is told about these fields at call time instead of having them written into
# its prompt as prose. Keys match create_agent_configuration's payload exactly.
CREATE_PAYLOAD_CONTRACT = {
	"agent_name": "Human-readable agent name (required).",
	"agent_id": "Machine id; auto-derived from the name when omitted.",
	"chat_mode_label": (
		"Label shown in chat mode pickers (must be unique). Required, EXCEPT when "
		"process_model names a non-chat map — a process-embedded agent never appears in chat."
	),
	"process_model": (
		"Name of the BPMN Process Model this agent is mapped to (WI-001997). When the agent "
		"is being created from a task dialog, propose the process currently open in the "
		"editor; ask the designer rather than guessing. Omit for a mapless Direct-API chat agent."
	),
	"ai_model": "Name of an AI Model catalog record — the agent's provider follows from this model's credentials link (WI-001655).",
	"system_prompt": "The agent's system prompt; leave empty to have the creation process generate one from the description.",
	"description": "What the agent does — feeds prompt auto-generation.",
	"sample_prompts": 'Optional list of {"prompt", "expected_behaviour"} rows; becomes the baseline eval suite.',
	"examples": (
		'Optional list of {"input", "expected_output", "note"} rows — worked few-shot '
		"examples that DEMONSTRATE the behaviour. Rendered into the agent's frozen static "
		"context after the system prompt. Use these to show a format or a judgement call "
		"that is hard to state as a rule."
	),
	"guardrails": (
		'Optional list of {"guardrail", "category"} rows — rules the agent must obey on '
		"every turn, each stated imperatively. category is one of: Code Quality, "
		"Performance, Cost & Tokens, Safety, Output Format, Other. Rendered LAST in the "
		"frozen static context. Use these for constraints (limits, checks, prohibitions); "
		"use examples for demonstrations."
	),
}


@frappe.whitelist()
def create_agent_configuration(payload: str | dict) -> dict:
	"""Create a new AI Agent Configuration from the Processa editor (WI-001648).

	Inserted as **Chat + Draft with the caller's permissions**, so the
	AI Agent Creation Process start trigger fires on insert exactly as it
	does for a config created from the doctype form — the agent walks
	validate → provision → evaluate → Live on its own. Sample prompts (with
	optional expected behaviour) become the baseline eval suite during the
	process's Evaluate step.

	Returns the new record's name plus the creation-process instance the
	insert started (None when the creation model is inactive on this site).
	"""
	if isinstance(payload, str):
		payload = frappe.parse_json(payload) or {}
	frappe.has_permission("AI Agent Configuration", "create", throw=True)

	# Without a creation process there is no path from Draft to Live for a Chat
	# agent (apply_background_lifecycle only auto-lives Background agents), so
	# creating one would strand it as a permanent Draft. Refuse up front and say
	# why, rather than leave a record nobody can finish.
	creation_model = get_creation_process_model()
	if not creation_model:
		holder = get_creation_grant_holder()
		frappe.throw(
			_(
				"The agent-creation process has not been linked, so new agents cannot be "
				"created yet. '{0}' holds the creation grant but its Agent Creation Process "
				"is missing or not deployed."
			).format(holder)
			if holder
			else _(
				"The agent-creation process has not been linked, so new agents cannot be "
				"created yet. Tick 'Can Create Agents' on one AI Agent Configuration and "
				"link the process map that takes an agent from Draft to Live."
			),
			title=_("Agent creation unavailable"),
		)

	agent_name = (payload.get("agent_name") or "").strip()
	if not agent_name:
		frappe.throw(_("Agent name is required."))
	chat_mode_label = (payload.get("chat_mode_label") or "").strip()
	process_model = (payload.get("process_model") or "").strip()
	if process_model and not frappe.db.exists("BPMN Process Model", process_model):
		frappe.throw(
			_(
				"BPMN Process Model '{0}' does not exist — pass the exact name of the "
				"process this agent is mapped to, or omit it."
			).format(process_model)
		)
	if not chat_mode_label and is_chat_startable_map(process_model) is not False:
		# WI-001997: only an agent mapped to a NON-chat process map may skip the
		# label — it never appears in the chat picker. Everything else (chat map,
		# or no map at all → Direct-API chat) fails fast here, because the
		# creation process's Validate step rejects label-less chat agents and
		# failing later guarantees a Needs Attention.
		frappe.throw(_("A chat mode label is required for a chat agent."))

	# Friendly duplicate guard — a raw DuplicateEntryError helps nobody.
	agent_id = (payload.get("agent_id") or "").strip() or frappe.scrub(agent_name)
	clash = frappe.db.exists("AI Agent Configuration", {"agent_name": agent_name}) or frappe.db.exists(
		"AI Agent Configuration", {"agent_id": agent_id}
	)
	if clash:
		frappe.throw(
			_(
				"An AI Agent Configuration named '{0}' already exists. "
				"Link it instead of creating it again, or ask for a change to it."
			).format(clash)
		)

	doc = frappe.new_doc("AI Agent Configuration")
	doc.agent_name = agent_name
	doc.agent_id = agent_id
	doc.agent_framework = payload.get("agent_framework") or "Direct API"
	doc.agent_type = "Chat"
	doc.lifecycle_status = "Draft"
	doc.enabled = 1
	doc.chat_mode_label = chat_mode_label
	# WI-001997: the map is a designer-chosen link at creation — usually the
	# process the agent is being created inside. Nothing clones or overwrites
	# it; the map stays the designer's own.
	doc.process_model = process_model or None
	# WI-001655: the model is the pick; the provider derives from its
	# credentials link on save. A directly-passed credentials value is kept
	# only as legacy fallback for model-less payloads.
	doc.ai_model = payload.get("ai_model") or None
	doc.ai_provider_credentials = payload.get("ai_provider_credentials") or None
	doc.system_prompt = payload.get("system_prompt") or ""
	doc.description = payload.get("description") or ""
	for row in payload.get("sample_prompts") or []:
		if (row.get("prompt") or "").strip():
			doc.append("sample_prompts", {
				"prompt": row["prompt"],
				"expected_behaviour": row.get("expected_behaviour") or "",
			})
	# WI-001639: the agent's frozen static context. Row order is the order the
	# proposer gave them — it is the order they reach the model.
	for row in payload.get("examples") or []:
		if (row.get("input") or "").strip():
			doc.append("examples", {
				"input": row["input"],
				"expected_output": row.get("expected_output") or "",
				"note": row.get("note") or "",
				"enabled": 1,
			})
	for row in payload.get("guardrails") or []:
		if (row.get("guardrail") or "").strip():
			doc.append("guardrails", {
				"guardrail": row["guardrail"],
				# An unrecognised category would fail Select validation and lose
				# the whole agent; fall back rather than reject the rule.
				"category": row.get("category") if row.get("category") in _GUARDRAIL_CATEGORIES else "Other",
				"enabled": 1,
			})
	doc.insert()  # caller's permissions; the After-Insert trigger starts the process

	creation_instance = None
	if creation_model:
		creation_instance = frappe.db.get_value(
			"BPMN Process Instance",
			{
				"process_model": creation_model,
				"context_doctype": "AI Agent Configuration",
				"context_docname": doc.name,
			},
			"name",
		)
	return {"name": doc.name, "agent_id": doc.agent_id, "creation_instance": creation_instance}


def _start_reprovision(config_name: str) -> bool:
	"""Send a Live agent back through the creation process after a write-back.

	The process's start event is After-Insert only, so an existing record
	needs an explicit instance start. Skipped (with a log) when no agent holds
	the creation grant, its linked map is missing/inactive, or an instance is
	already running for this agent — the running one will pick up the saved
	values itself.
	"""
	creation_model = get_creation_process_model()
	if not creation_model:
		holder = get_creation_grant_holder()
		frappe.log_error(
			title=f"Re-provision skipped for {config_name}",
			message=(
				f"'{holder}' holds the agent-creation grant but its linked "
				"Agent Creation Process is missing or inactive."
				if holder
				else "No AI Agent Configuration holds the agent-creation grant "
				"(can_create_agents), so there is no creation process to run."
			),
		)
		return False

	already_running = frappe.db.exists(
		"BPMN Process Instance",
		{
			"process_model": creation_model,
			"context_doctype": "AI Agent Configuration",
			"context_docname": config_name,
			"status": ("in", ["Active", "Errored"]),
		},
	)
	if already_running:
		return False

	try:
		from one_bpmn.api.instance_api import start_process

		start_process(
			creation_model,
			context_doctype="AI Agent Configuration",
			context_docname=config_name,
		)
		return True
	except Exception:
		frappe.log_error(
			title=f"Re-provision failed for {config_name}",
			message=frappe.get_traceback(),
		)
		return False
