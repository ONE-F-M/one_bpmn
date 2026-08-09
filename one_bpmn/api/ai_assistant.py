# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
AI Agent Task configuration assistant.

Powers the in-modal chat panel on the AI Agent Task config page. The assistant
uses the SAME AI Provider Credentials the designer has selected for the task to recommend
values for the task's fields (prompts, model, output variable, response format,
advanced limits) based on a plain-language requirement.

It can optionally look at a context DocType's schema and one sample record so
its prompt suggestions reference real field names. Schema and record reads go
through Frappe's permission system (frappe.get_meta / frappe.get_doc), so a
designer only ever sees data they are already allowed to read.

No LLM SDK lives here — the call is made through the shared executor backends
(direct_api / antigravity), exactly like a real AI Agent Task dispatch.
"""
from __future__ import annotations

import json

import frappe
from frappe import _


# Catalogue of the task-config fields the assistant is allowed to recommend.
# Keys match the spiffworkflow:ai* attribute names (without the prefix) and the
# AIAgentConfigModal form keys exactly, so the frontend can apply them 1:1.
FIELD_CATALOG = {
	"aiBackend":        'Executor backend — "direct_api" or "antigravity".',
	"aiModel":          "Model name override (blank = provider default).",
	"aiOutputVariable": "Process variable name to store the result, e.g. ai_result.",
	"aiSystemPrompt":   "System prompt. Jinja2 — {{ doc }}, {{ instance }} available.",
	"aiUserPrompt":     "User prompt / task instruction. Jinja2 supported.",
	"aiResponseFormat": '"text" or "json".',
	"aiResponseSchema": "JSON Schema string (only meaningful when format is json).",
	"aiTemperature":    "Float 0.0–2.0.",
	"aiTopP":           "Float 0.0–1.0.",
	"aiMaxTokens":      "Integer — max output tokens.",
	"aiTimeout":        "Integer — request timeout in seconds.",
	"aiMaxRetries":     "Integer — number of retries on transient failure.",
}

# Fields the assistant may recommend in SELECTOR mode (AI Task Selector on an
# ad-hoc subprocess). Mirrors what the selector dispatch reads at runtime and
# the modal's selector-mode form. aiProvider is deliberately absent — the
# designer picks it, and it powers the assistant itself.
SELECTOR_FIELD_CATALOG = {
	"aiModel":        "Model name override (blank = provider default).",
	"aiSystemPrompt": "The selection procedure: rules for which task to activate at each decision point, referencing tasks by their BPMN id.",
	"aiUserPrompt":   "The evidence template. Jinja2 — {{ doc.<field> }} for the live context document, process variables like {{ my_var }}, and {% if my_var is defined %} guards for variables that appear mid-process.",
	"aiMaxTokens":    "Integer — max output tokens per decision.",
	"aiTimeout":      "Integer — request timeout in seconds per decision.",
}

# Layout-only / non-data field types skipped when summarising a DocType schema.
_SKIP_FIELDTYPES = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"}

_MAX_SCHEMA_FIELDS = 120
_MAX_SAMPLE_CHARS = 4000

_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
_SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

# Mirrors tool_pool eligibility (2026-07-02 decision): only leaf task
# activities with no incoming sequence flow are selector candidates.
_LEAF_TASK_TAGS = {
	f"{{{_BPMN_NS}}}task": "Task",
	f"{{{_BPMN_NS}}}userTask": "User Task",
	f"{{{_BPMN_NS}}}manualTask": "Manual Task",
	f"{{{_BPMN_NS}}}scriptTask": "Script Task",
	f"{{{_BPMN_NS}}}serviceTask": "Service Task",
	f"{{{_BPMN_NS}}}sendTask": "Send Task",
	f"{{{_BPMN_NS}}}receiveTask": "Receive Task",
	f"{{{_BPMN_NS}}}businessRuleTask": "Business Rule Task",
}
_GATEWAY_TAGS = {
	f"{{{_BPMN_NS}}}exclusiveGateway": "Exclusive Gateway",
	f"{{{_BPMN_NS}}}parallelGateway": "Parallel Gateway",
	f"{{{_BPMN_NS}}}inclusiveGateway": "Inclusive Gateway",
}


@frappe.whitelist()
def recommend_ai_task_config(
	provider: str,
	backend: str = "direct_api",
	requirement: str = "",
	context_doctype: str = "",
	context_docname: str = "",
	history: str = "[]",
	mode: str = "agent",
	bpmn_xml: str = "",
	element_id: str = "",
	current_config: str = "{}",
	process_model: str = "",
	linked_config: str = "",
	conversation: str = "",
) -> dict:
	"""Return assistant recommendations for an AI Agent Task's configuration.

	Args:
		provider: AI Provider Credentials name powering the assistant (the task's own provider).
		backend: Executor backend ("direct_api" | "antigravity").
		requirement: The designer's latest chat message.
		context_doctype: Optional DocType whose schema/sample to show the model.
		context_docname: Optional specific record; if blank, the latest readable
			record of context_doctype is used as the sample.
		history: JSON array of prior turns [{"role": "...", "content": "..."}].
		mode: "agent" (AI Agent Task) or "selector" (AI Task Selector on an
			ad-hoc subprocess). Selector mode teaches the model the selector
			runtime semantics and shows it the diagram digest.
		bpmn_xml: The LIVE diagram XML from the editor canvas (selector mode) —
			the saved model may be stale while the designer edits.
		element_id: BPMN id of the ad-hoc subprocess being configured.
		current_config: JSON of the form's current values so the assistant can
			refine drafts instead of starting over.

	Returns:
		{"ok": True, "message": str, "recommendations": {field: value, ...}}
		or {"ok": False, "error_code": str, "message": str} on failure.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("You must be logged in to use the assistant."))

	# WI-001623: the assistant runs on ITS OWN configuration's credentials,
	# not the task's. The task's provider is only the fallback for sites
	# without an ai_agent_assistant record. (Previously the task's provider
	# won — so a task linked to broken credentials broke the very assistant
	# meant to help fix them.)
	provider = _assistant_default_provider() or provider
	if not provider:
		frappe.throw(_("Select an AI Provider Credentials before using the assistant."))

	if not frappe.db.exists("AI Provider Credentials", provider):
		frappe.throw(_("AI Provider Credentials '{0}' not found.").format(provider))

	if not (requirement or "").strip():
		frappe.throw(_("Describe what you want the AI Agent Task to do."))

	mode = mode if mode in ("agent", "selector") else "agent"
	catalog = _catalog_for_mode(mode)

	turns = _parse_history(history)
	context_block = _build_context_block(context_doctype, context_docname)

	digest = None
	diagram_block = ""
	if mode == "selector":
		digest = _build_diagram_digest(bpmn_xml, element_id, process_model=process_model)
		diagram_block = digest["block"] if digest else ""
		system_prompt = _build_selector_system_prompt()
	else:
		# WI-001623 full parity: an agent-mode turn IS a chat-platform turn.
		# It runs through the generic invocation on the assistant's own chat
		# map — so it persists as a Chat Conversation + Chat Messages, its
		# LLM call is an AI Agent Run attributed to the assistant, and the
		# map instance is inspectable on Processa like any other process.
		# The dialog's grounding rides as per-turn context (the map's user
		# prompt renders {{ dialog_context }}); the persona comes from the
		# assistant's configuration as always.
		if not _assistant_system_prompt():
			return {
				"ok": False,
				"error_code": "ASSISTANT_NOT_CONFIGURED",
				"message": _(
					"The AI Assistant's agent configuration (agent_id "
					"'ai_agent_assistant') is missing or has an empty system "
					"prompt. Create or repair that AI Agent Configuration to "
					"enable the assistant."
				),
			}
		dialog_context_parts = [
			_creation_capability_block(),
			_linked_config_block(linked_config),
			_build_full_diagram_block(bpmn_xml, element_id, process_model=process_model),
			context_block,
			_build_current_config_block(current_config, catalog),
		]
		dialog_context = "\n\n".join(p for p in dialog_context_parts if p)

		from one_bpmn.api.agent_invocation import invoke_agent

		try:
			turn = invoke_agent(
				agent_id="ai_agent_assistant",
				message=requirement.strip(),
				conversation=conversation or None,
				context={"dialog_context": dialog_context, "source": "task_dialog"},
			)
		except frappe.ValidationError as exc:
			return {
				"ok": False,
				"error_code": "ASSISTANT_PROCESS_NOT_RUNNING",
				"message": str(exc),
			}

		raw = (turn or {}).get("response") or ""
		parsed = _extract_json(raw if isinstance(raw, str) else json.dumps(raw))
		if not isinstance(parsed, dict):
			return {
				"ok": True,
				"message": raw or _("No recommendation returned."),
				"recommendations": {},
				"conversation": (turn or {}).get("conversation"),
			}
		message = str(parsed.get("message", "")).strip() or (
			raw if not parsed.get("recommendations") else ""
		)
		recommendations = {
			key: value
			for key, value in (parsed.get("recommendations") or {}).items()
			if key in catalog and value not in (None, "")
		}
		return {
			"ok": True,
			"message": message,
			"recommendations": recommendations,
			"proposed_config": _sanitize_proposed_config(parsed.get("proposed_config")),
			"proposed_update": _sanitize_proposed_update(parsed.get("proposed_update")),
			"conversation": (turn or {}).get("conversation"),
		}

	user_prompt = _build_user_prompt(
		requirement,
		turns,
		context_block,
		diagram_block=diagram_block,
		current_config_block=_build_current_config_block(current_config, catalog),
	)

	from one_bpmn.agents.executor import (
		ExecutorConfig,
		ExecutorContext,
		ErrorCode,
		get_executor,
	)
	# Importing the backend modules registers them in the executor registry.
	from one_bpmn.agents.executor import direct_api, antigravity  # noqa: F401

	backend = backend or "direct_api"
	try:
		executor_cls = get_executor(backend)
	except ValueError:
		frappe.throw(_("Unknown executor backend '{0}'.").format(backend))

	config = ExecutorConfig(
		backend=backend,
		provider_name=provider,
		model=_assistant_default_model(),  # the assistant's own catalog pick (WI-001655)
		system_prompt=system_prompt,
		user_prompt=user_prompt,
		temperature=0.3,
		top_p=1.0,
		# Generous: reasoning models (gpt-5 family) spend completion budget
		# on hidden reasoning first — 1800 yielded empty visible output.
		max_tokens=6000,
		timeout_seconds=60,
		response_format="text",  # parsed tolerantly below
		max_retries=1,
	)

	result = executor_cls().run(config, ExecutorContext(jinja_context={}))

	if result.error_code != ErrorCode.SUCCESS:
		return {
			"ok": False,
			"error_code": result.error_code.value,
			"message": result.error_message or _("The assistant request failed."),
		}

	if not (result.output or "").strip() if isinstance(result.output, str) else not result.output:
		# Reasoning models can exhaust the completion budget on hidden
		# reasoning and return nothing visible — surface it instead of a
		# silent empty recommendation set.
		return {
			"ok": False,
			"error_code": "EMPTY_OUTPUT",
			"message": _(
				"The model returned no visible text — its token budget was "
				"likely consumed by internal reasoning. Try again, or use a "
				"different model for the assistant."
			),
		}

	parsed = _extract_json(result.output if isinstance(result.output, str) else json.dumps(result.output))
	if not isinstance(parsed, dict):
		# Model answered but not as JSON — surface the text, no field changes.
		text = result.output if isinstance(result.output, str) else _("No recommendation returned.")
		return {"ok": True, "message": text, "recommendations": {}}

	message = str(parsed.get("message", "")).strip()
	raw_recs = parsed.get("recommendations") or {}
	recommendations = {}
	if isinstance(raw_recs, dict):
		for key, value in raw_recs.items():
			if key in catalog and value not in (None, ""):
				recommendations[key] = value

	# Post-check (selector mode): every task id a recommended prompt mentions
	# must exist on the diagram, and every candidate should be covered.
	if digest:
		warnings = _lint_recommended_prompts(recommendations, digest)
		if warnings:
			message = (message + "\n\n" if message else "") + "\n".join(f"⚠️ {w}" for w in warnings)

	# WI-001649 (agent mode only): proposed new-agent creation and proposed
	# updates to an existing agent. The model PROPOSES; the user confirms in
	# the UI; only then does the frontend call the (permission-checked)
	# endpoint — the model never writes documents.
	proposed_config = proposed_update = None
	if mode == "agent":
		proposed_config = _sanitize_proposed_config(parsed.get("proposed_config"))
		proposed_update = _sanitize_proposed_update(parsed.get("proposed_update"))

	return {
		"ok": True,
		"message": message,
		"recommendations": recommendations,
		"proposed_config": proposed_config,
		"proposed_update": proposed_update,
	}


def _catalog_for_mode(mode: str) -> dict:
	return SELECTOR_FIELD_CATALOG if mode == "selector" else FIELD_CATALOG


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _assistant_system_prompt() -> str:
	"""Agent-mode system prompt from the AI Assistant's configuration
	(WI-001623). Returns "" when the config is absent so the caller falls
	back to the in-code builder."""
	try:
		from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

		cfg = get_agent_config("ai_agent_assistant")
		return (cfg or {}).get("system_prompt") or ""
	except Exception:
		return ""


def _assistant_default_model() -> str:
	"""The AI Model the assistant's own configuration picks (WI-001655)."""
	try:
		from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

		return (get_agent_config("ai_agent_assistant") or {}).get("ai_model") or ""
	except Exception:
		return ""


def _assistant_default_provider() -> str:
	"""The credentials record the AI Assistant configuration links, if any."""
	try:
		from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

		return (get_agent_config("ai_agent_assistant") or {}).get("ai_provider_credentials") or ""
	except Exception:
		return ""


def _build_system_prompt() -> str:
	field_lines = "\n".join(f'  - "{name}": {desc}' for name, desc in FIELD_CATALOG.items())
	return (
		"You are a configuration assistant embedded in a BPMN editor. You help a "
		"process designer configure an 'AI Agent Task' — a workflow step that makes "
		"a single LLM call at runtime.\n\n"
		"At runtime the task renders its prompts with Jinja2 against a context "
		"document, exposing {{ doc }} (the context record), {{ instance }} (the BPMN "
		"process instance) and {{ frappe }}. The task stores the model's reply in a "
		"process variable named by aiOutputVariable, which downstream gateways and "
		"script tasks can read.\n\n"
		"YOUR TOOLBOX:\n"
		"You have callable tools (platform lookups: records, counts, schemas, "
		"reports, wiki — and 'add_agent_evals' to attach evaluation cases to an "
		"AI Agent Configuration and refresh its baseline suite). USE a tool for "
		"any platform fact you cannot know from the conversation alone — never "
		"invent record names, counts or field values. When the designer asks to "
		"add tests/evals to an agent, call add_agent_evals with the agent's "
		"exact record name and the cases. After a new agent is created, offer "
		"to add evals for it.\n\n"
		"Based on the designer's requirement (and any DocType schema / sample record "
		"provided), recommend values for these fields:\n"
		f"{field_lines}\n\n"
		"Guidance:\n"
		"  - Write clear, specific prompts. Use Jinja {{ doc.<fieldname> }} placeholders "
		"that match the provided schema field names.\n"
		"  - Suggest a concise snake_case aiOutputVariable.\n"
		"  - Use aiResponseFormat 'json' (with an aiResponseSchema) only when the task "
		"should return structured data; otherwise 'text'.\n"
		"  - Only include a field in 'recommendations' when you have a concrete value "
		"for it. Omit fields you are unsure about.\n\n"
		"CLARIFY WHEN UNSURE:\n"
		"  - If the requirement is ambiguous or missing something you need to "
		"recommend good values (e.g. which field to summarise, the desired output "
		"shape, or the target DocType), ASK a specific clarifying question instead "
		"of guessing. Return your question as 'message' with an EMPTY "
		"'recommendations' object, and wait for the designer's reply — the "
		"conversation is multi-turn and prior turns are provided.\n"
		"  - Only propose recommendations once the requirement is clear enough to "
		"stand behind them.\n\n"
		"CREATING NEW AGENTS:\n"
		"  - You can also help the designer create a whole new AI Agent "
		"Configuration — a reusable agent the task links to. The prerequisites "
		"(required fields, validation rules, enabled providers, taken labels) are "
		"supplied to you as live platform data, not from memory.\n"
		"  - Gather every required detail conversationally — ask focused "
		"questions for what is missing rather than guessing — and only propose "
		"the agent once the details are complete, following the create-agent "
		"response contract. The designer always confirms before anything is "
		"created.\n\n"
		"UPDATING EXISTING AGENTS:\n"
		"  - You can also propose changes to an existing AI Agent Configuration "
		"(provider, prompt, sampling params) following the update-agent response "
		"contract. When the task already links a configuration, treat it as the "
		"target unless told otherwise — do not interrogate the designer about "
		"which record they mean. The designer always confirms before anything "
		"is applied; never claim a change was made.\n\n"
		"REPLY FORMAT (WI-001623 — you serve two surfaces):\n"
		"  - When the request carries PLATFORM CONTEXT blocks (task-dialog "
		"turns), the CONTENT of your reply must be exactly one JSON object, no "
		"prose outside it:\n"
		'    { "message": "<summary, or clarifying question when unsure>",\n'
		'      "recommendations": { "aiUserPrompt": "...", ... } }\n'
		"    plus \"proposed_config\" / \"proposed_update\" when their contracts "
		"apply.\n"
		"  - In ordinary chat (no platform context), reply as plain, helpful "
		"conversational text — never raw JSON.\n"
		"  - Either way, if the message specifies an OUTPUT PROTOCOL wrapper, "
		"obey it exactly and place the reply above inside it."
	)


def _creation_prerequisites_block() -> str:
	"""WI-001649: the prerequisites for creating an AI Agent Configuration,
	assembled from LIVE sources at call time — required fields from the
	doctype meta, the creation endpoint's payload contract, the validation
	rules kept next to validate_agent_config, the enabled provider records,
	and the chat-mode labels already taken. Adding a required field to the
	doctype (or a rule to the validator) updates what the assistant knows
	with zero edits here.
	"""
	from one_bpmn.agents.agent_config_resolver import CREATE_PAYLOAD_CONTRACT
	from one_bpmn.agents.agent_provisioning import VALIDATION_RULES

	lines = ["PREREQUISITES FOR CREATING AN AI AGENT CONFIGURATION (live platform data):"]

	try:
		meta = frappe.get_meta("AI Agent Configuration")
		reqd = [f"{f.fieldname} ({f.label})" for f in meta.fields if f.reqd]
		if reqd:
			lines.append("Required doctype fields: " + ", ".join(reqd))
	except Exception:
		pass

	lines.append("Creation payload fields:")
	lines.extend(f'  - "{field}": {desc}' for field, desc in CREATE_PAYLOAD_CONTRACT.items())

	lines.append("Validation rules (checked by the creation process before go-live):")
	lines.extend(f"  - {rule['field']}: {rule['rule']}" for rule in VALIDATION_RULES)

	try:
		# WI-001655: the agent's LLM choice is a MODEL pick from the catalog;
		# the provider follows from the model's credentials link.
		models = frappe.get_list(
			"AI Model",
			fields=["name", "ai_provider_credentials"],
			limit_page_length=100,
			order_by="name asc",
		)
		enabled = set(frappe.get_list(
			"AI Provider Credentials", filters={"enabled": 1}, pluck="name", limit_page_length=50,
		))
		usable = [m for m in models if m.ai_provider_credentials in enabled]
		if usable:
			lines.append(
				"AI Model catalog (use these EXACT names for ai_model / aiModel; "
				"the provider follows from the model): "
				+ ", ".join(f"{m.name} (via {m.ai_provider_credentials})" for m in usable)
			)
		else:
			lines.append("No usable AI Model catalog records (none link enabled credentials).")
	except Exception:
		pass

	try:
		rows = frappe.get_list(
			"AI Agent Configuration",
			fields=["name", "agent_id", "chat_mode_label"],
			limit_page_length=200,
		)
		labels = sorted({r.chat_mode_label for r in rows if r.chat_mode_label})
		if labels:
			lines.append("Chat mode labels already taken (a new one must differ): " + ", ".join(labels))
		existing = sorted({f"{r.name} (agent_id: {r.agent_id})" for r in rows})
		if existing:
			lines.append(
				"Agents that ALREADY EXIST — never propose creating one of these; "
				"propose an update to it instead: " + "; ".join(existing)
			)
	except Exception:
		pass

	return "\n".join(lines)


def _update_contract_block() -> str:
	"""The proposed_update contract. Shared by both capability blocks: changing
	an existing agent needs no creation process, so it stays available on a site
	that cannot create agents at all."""
	return (
		"UPDATE-AGENT RESPONSE CONTRACT:\n"
		"When the designer asks to CHANGE an existing AI Agent Configuration, "
		"add a \"proposed_update\" object to your JSON reply (alongside "
		"\"message\"): {\"config_name\": \"<exact record name>\", \"fields\": "
		"{...}} where fields may only contain \"aiModel\" (an EXACT AI Model "
		"catalog name — the agent's provider follows from the model "
		"automatically), \"aiSystemPrompt\", \"aiTemperature\" and/or "
		"\"aiMaxTokens\". There is no direct provider change: to change the "
		"provider, change the model. Include ONLY the fields being changed. "
		"When the conversation refers to \"this agent\" or \"the "
		"configuration\", it means the LINKED AGENT CONFIGURATION context below "
		"when present; ask only if genuinely ambiguous. The designer confirms "
		"the proposal in the UI before anything is applied."
	)


def _creation_unavailable_block() -> str:
	"""Told to the assistant when no agent holds the creation grant.

	Creating an agent without a creation process would strand it as a permanent
	Draft, so the endpoint refuses. The assistant has to know that BEFORE it
	starts interviewing the designer, or it gathers a full specification and
	then fails at the last step.
	"""
	from one_bpmn.agents.agent_config_resolver import get_creation_grant_holder

	holder = get_creation_grant_holder()
	detail = (
		f"'{holder}' holds the creation grant, but its Agent Creation Process is "
		"missing or not deployed."
		if holder
		else "No AI Agent Configuration has 'Can Create Agents' ticked with a process linked."
	)
	return (
		"CREATING AGENTS IS UNAVAILABLE ON THIS SITE:\n"
		f"{detail}\n"
		"If the designer asks you to create an agent, tell them plainly that the "
		"process for creating agents has not been linked, so you cannot create "
		"one yet, and that an administrator needs to tick 'Can Create Agents' on "
		"an AI Agent Configuration and link the agent-creation process map. Do "
		"NOT interview them for agent details, do NOT emit \"proposed_config\", "
		"and do not imply the agent will be created later. You can still help "
		"with this task's own fields and with changes to existing agents."
	)


def _creation_capability_block() -> str:
	"""WI-001649: the response contract for proposing a new agent, plus the
	live prerequisites data. This is interface plumbing (like the JSON shape
	the recommendations contract defines) — the assistant's persona and
	behavior live in its AI Agent Configuration record, not here.

	When no agent holds the creation grant the create half is replaced by a
	plain statement that creation is unavailable; the update half still
	applies, since changing an existing agent needs no creation process.
	"""
	from one_bpmn.agents.agent_config_resolver import get_creation_process_model

	if not get_creation_process_model():
		return _creation_unavailable_block() + "\n\n" + _update_contract_block()

	return (
		_creation_prerequisites_block()
		+ "\n\nCREATE-AGENT RESPONSE CONTRACT:\n"
		"When the designer asks to create a NEW agent and every required detail "
		"above has been gathered from the conversation, add a \"proposed_config\" "
		"object to your JSON reply (alongside \"message\") using exactly the "
		"creation payload fields. While anything required is still missing, ask "
		"for it via \"message\" instead — do not guess values, do not invent "
		"provider names, and never include \"proposed_config\" until the "
		"proposal is complete. The designer confirms the proposal in the UI "
		"before anything is created.\n\n"
		+ _update_contract_block()
		+ "\n\nCAPABILITY LIMITS (hard, non-negotiable):\n"
		"You cannot write to ANY record yourself. Your only side-effect paths "
		"are \"proposed_config\" and \"proposed_update\", both of which take "
		"effect only after the designer confirms them in the UI. Changes outside "
		"the updatable fields above (agent id, chat mode label, enabled, "
		"lifecycle, roles…) must be made on the record in the desk — say so. "
		"NEVER state or imply that you performed an action — reporting an "
		"update you did not make is the worst possible answer.\n\n"
		"ROUTING RULES:\n"
		"- The USER PROMPT is a property of the TASK SHAPE, not of an agent "
		"configuration (agents have no user prompt). A request to write or "
		"change the User Prompt is answered with an ordinary field "
		"recommendation (\"recommendations\": {\"aiUserPrompt\": ...}) — never "
		"with proposed_config or proposed_update.\n"
		"- Once an agent has been created in this conversation, follow-up "
		"requests refine THAT agent (proposed_update) or the task's own fields "
		"(recommendations) — do not propose creating it again. Creating an "
		"agent whose name or agent_id already exists always fails."
	)


def _linked_config_block(linked_config: str) -> str:
	"""Live context about the task's linked AI Agent Configuration, so a
	request like 'change this agent's provider' needs no interrogation."""
	if not linked_config or not frappe.db.exists("AI Agent Configuration", linked_config):
		return ""
	if not frappe.has_permission("AI Agent Configuration", "read"):
		return ""
	cfg = frappe.db.get_value(
		"AI Agent Configuration", linked_config,
		["name", "agent_id", "agent_type", "lifecycle_status", "ai_model", "ai_provider_credentials", "chat_mode_label"],
		as_dict=True,
	)
	return (
		"LINKED AGENT CONFIGURATION (this task's — the default target for "
		"update requests):\n"
		f"  name: {cfg.name}\n"
		f"  agent_id: {cfg.agent_id}\n"
		f"  type: {cfg.agent_type} | lifecycle: {cfg.lifecycle_status}\n"
		f"  model: {cfg.ai_model or '(none)'} | provider (derived): {cfg.ai_provider_credentials or '(none)'}\n"
		f"  chat mode label: {cfg.chat_mode_label or '(none)'}"
	)


# Shape-attribute fields the assistant may propose changing on an existing
# configuration — exactly what update_agent_config_from_shape accepts.
# WI-001655: the MODEL is the updatable pick (validated against the AI Model
# catalog); aiProvider is gone — the provider follows the model.
_UPDATABLE_FIELDS = {"aiModel", "aiSystemPrompt", "aiTemperature", "aiMaxTokens"}


def _sanitize_proposed_update(proposed) -> dict | None:
	"""Keep only a valid update proposal: an existing config plus allowlisted
	fields. None when there is nothing usable."""
	if not isinstance(proposed, dict):
		return None
	config_name = str(proposed.get("config_name") or "").strip()
	if not config_name or not frappe.db.exists("AI Agent Configuration", config_name):
		return None
	fields = proposed.get("fields")
	if not isinstance(fields, dict):
		return None
	clean = {
		key: value
		for key, value in fields.items()
		if key in _UPDATABLE_FIELDS and isinstance(value, (str, int, float)) and str(value).strip()
	}
	# WI-001655: a model must be a real catalog record — drop hallucinated ones
	# so the Apply card can never be doomed to a link-validation error.
	if "aiModel" in clean and not frappe.db.exists("AI Model", str(clean["aiModel"])):
		clean.pop("aiModel")
	if not clean:
		return None
	return {"config_name": config_name, "fields": clean}


_PROPOSAL_FIELDS = {
	"agent_name", "agent_id", "chat_mode_label",
	"ai_model", "system_prompt", "description",
}


def _sanitize_proposed_config(proposed) -> dict | None:
	"""Keep only the create-payload fields from a model proposal; normalize the
	row lists — sample prompts, and (WI-001639) examples and guard rails — to
	their child-table shapes. None when there is no usable proposal — including
	a proposal to create an agent that already exists (Create & link would only
	ever fail with a duplicate error), or any proposal at all on a site with no
	agent-creation process linked — the confirm button would only hit the
	endpoint's refusal, so the card must never render."""
	if not isinstance(proposed, dict):
		return None

	from one_bpmn.agents.agent_config_resolver import get_creation_process_model

	if not get_creation_process_model():
		return None

	agent_name = str(proposed.get("agent_name") or "").strip()
	agent_id = str(proposed.get("agent_id") or "").strip() or (frappe.scrub(agent_name) if agent_name else "")
	if agent_name and frappe.db.exists("AI Agent Configuration", {"agent_name": agent_name}):
		return None
	if agent_id and frappe.db.exists("AI Agent Configuration", {"agent_id": agent_id}):
		return None
	clean = {
		key: str(value)
		for key, value in proposed.items()
		if key in _PROPOSAL_FIELDS and isinstance(value, (str, int, float)) and str(value).strip()
	}
	samples = []
	for row in proposed.get("sample_prompts") or []:
		if isinstance(row, dict) and str(row.get("prompt") or "").strip():
			samples.append({
				"prompt": str(row["prompt"]),
				"expected_behaviour": str(row.get("expected_behaviour") or ""),
			})
	if samples:
		clean["sample_prompts"] = samples

	# WI-001639: the agent's frozen static context. Both are row lists, so they
	# skip the scalar filter above and are normalized here — dropping rows whose
	# mandatory field is empty rather than letting them fail at insert.
	examples = []
	for row in proposed.get("examples") or []:
		if isinstance(row, dict) and str(row.get("input") or "").strip():
			examples.append({
				"input": str(row["input"]),
				"expected_output": str(row.get("expected_output") or ""),
				"note": str(row.get("note") or ""),
			})
	if examples:
		clean["examples"] = examples

	guardrails = []
	for row in proposed.get("guardrails") or []:
		if isinstance(row, dict) and str(row.get("guardrail") or "").strip():
			guardrails.append({
				"guardrail": str(row["guardrail"]),
				"category": str(row.get("category") or "Other"),
			})
	if guardrails:
		clean["guardrails"] = guardrails

	return clean or None


def _build_selector_system_prompt() -> str:
	field_lines = "\n".join(f'  - "{name}": {desc}' for name, desc in SELECTOR_FIELD_CATALOG.items())
	return (
		"You are a configuration assistant embedded in a BPMN editor. You help a "
		"process designer write the prompts for an 'AI Task Selector' — an ad-hoc "
		"subprocess where an LLM decides, one decision at a time, which inner task "
		"to activate next.\n\n"
		"HOW THE SELECTOR RUNS (these facts are non-negotiable — your prompts must "
		"work within them):\n"
		"  1. Every decision is a FRESH, stateless LLM call. The only memory between "
		"decisions is process data, surfaced through Jinja placeholders in the user "
		"prompt, plus the live context document ({{ doc.<field> }} is re-read every "
		"decision).\n"
		"  2. The model is offered the candidate tasks as tools NAMED BY THEIR BPMN "
		"ID (the documentation text is the tool description). Prompts must reference "
		"tasks by those exact ids.\n"
		"  3. Exactly one task may be activated per decision. The very FIRST decision "
		"happens at subprocess entry, before anything has run.\n"
		"  4. Completed tasks are NOT offered as tools; the user prompt is "
		"automatically appended an authoritative progress line naming tasks that "
		"already ran, plus a standing guard: if the prescribed task is not "
		"offered, activate nothing. Selection procedures should still lean on "
		"observable EVIDENCE (document field values, process variables) to "
		"decide the next step — never on the model remembering.\n"
		"  5. Tasks connected by sequence flows to a candidate run AUTOMATICALLY "
		"after it — never instruct the model to activate those; instead use their "
		"effects (e.g. a status value they set) as evidence.\n"
		"  5b. REGISTRY TOOLS listed in the digest are callable functions, not "
		"tasks: the model may call them freely within a decision (they answer "
		"immediately) and still activate one task. Their latest result persists "
		"in a <selector id>_toolCallResult process variable as a JSON string.\n"
		"  6. The subprocess ends when its completion condition becomes true "
		"(usually a variable set by a wrap-up script task).\n\n"
		"A DIAGRAM DIGEST of the subprocess follows in the user message: the "
		"selectable tasks with their ids and behaviors, the automatic chains, the "
		"observable state changes, and the completion condition. Build the "
		"selection procedure (aiSystemPrompt) as explicit if/then rules over that "
		"evidence, referencing only ids from the digest, and build the evidence "
		"template (aiUserPrompt) so every rule's condition is actually visible in "
		"it — use {% if var is defined %} guards for variables that only appear "
		"after some task runs.\n\n"
		"Recommend values for these fields:\n"
		f"{field_lines}\n\n"
		"Respond with ONLY a single JSON object, no prose outside it, in this exact shape:\n"
		'{\n'
		'  "message": "<a short, friendly explanation of what you suggested>",\n'
		'  "recommendations": { "aiSystemPrompt": "...", "aiUserPrompt": "...", ... }\n'
		'}'
	)


def _build_user_prompt(
	requirement: str,
	turns: list,
	context_block: str,
	diagram_block: str = "",
	current_config_block: str = "",
) -> str:
	parts = []
	if diagram_block:
		parts.append(diagram_block)
	if context_block:
		parts.append(context_block)
	if current_config_block:
		parts.append(current_config_block)
	if turns:
		convo = "\n".join(
			f"{str(t.get('role', 'user')).upper()}: {t.get('content', '')}"
			for t in turns
			if isinstance(t, dict)
		)
		if convo:
			parts.append("CONVERSATION SO FAR:\n" + convo)
	parts.append("DESIGNER REQUIREMENT:\n" + requirement.strip())
	parts.append(
		"Return the JSON object with your recommended field values now."
	)
	return "\n\n".join(parts)


def _build_current_config_block(current_config: str, catalog: dict) -> str:
	try:
		cfg = json.loads(current_config or "{}")
	except Exception:
		return ""
	if not isinstance(cfg, dict):
		return ""
	lines = [
		f"  {key}: {value}"
		for key, value in cfg.items()
		if key in catalog and str(value or "").strip()
	]
	if not lines:
		return ""
	return "CURRENT CONFIGURATION (refine these rather than starting over when the designer asks for changes):\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Diagram digest (selector mode)
# ---------------------------------------------------------------------------

_MAX_DIAGRAM_CHARS = 24000


def _build_full_diagram_block(bpmn_xml: str, element_id: str = "", process_model: str = "") -> str:
	"""Read-only full-diagram grounding for agent mode (WI-001625).

	Passes the complete BPMN XML so the assistant's recommendations can
	reference the real shapes, flows and variables around the AI task —
	rather than the shape in isolation. Read-only: the assistant proposes
	field values; it never edits the diagram. Oversized diagrams are
	truncated with an explicit marker so the prompt stays bounded.

	``process_model`` names the BPMN Process Model open in the editor —
	WI-001997: agent creation asks which process the agent is mapped to, and
	this name is the default the assistant should propose.
	"""
	xml = (bpmn_xml or "").strip()
	model_line = (
		f"CURRENT PROCESS MODEL: '{process_model}' — the process open in the editor, "
		"and the default process_model when creating an agent from this dialog.\n"
		if (process_model or "").strip()
		else ""
	)
	if not xml:
		return model_line.strip()
	truncated = ""
	if len(xml) > _MAX_DIAGRAM_CHARS:
		xml = xml[:_MAX_DIAGRAM_CHARS]
		truncated = "\n<!-- … diagram truncated for length … -->"
	focus = f" The AI task being configured is element id '{element_id}'." if element_id else ""
	return (
		model_line
		+ "FULL PROCESS DIAGRAM (read-only context)."
		+ focus
		+ " Use it to ground your recommendations in the surrounding shapes, "
		"sequence flows and process variables; do not propose edits to the "
		"diagram itself:\n```xml\n"
		+ xml
		+ truncated
		+ "\n```"
	)


def _build_diagram_digest(bpmn_xml: str, element_id: str, process_model: str = "") -> dict | None:
	"""Parse the ad-hoc subprocess out of the live diagram XML and produce a
	model-readable digest: selectable candidates, automatic chains, observable
	state changes, evidence variables and the completion condition.

	Returns {"block": str, "candidate_ids": [..], "element_ids": {..}} or None
	when no ad-hoc subprocess is found (the assistant then works blind, as
	before).
	"""
	import xml.etree.ElementTree as _ET

	if not (bpmn_xml or "").strip():
		return None
	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8"))
	except Exception:
		return None

	adhoc = None
	for candidate in root.iter(f"{{{_BPMN_NS}}}adHocSubProcess"):
		if not element_id or candidate.get("id") == element_id:
			adhoc = candidate
			break
	if adhoc is None:
		return None

	# ── flow graph within the subprocess ──
	flows = {}       # source id -> [target ids]
	has_incoming = set()
	for flow in adhoc.findall(f"{{{_BPMN_NS}}}sequenceFlow"):
		src, tgt = flow.get("sourceRef"), flow.get("targetRef")
		if src and tgt:
			flows.setdefault(src, []).append(tgt)
			has_incoming.add(tgt)

	nodes = {}       # id -> element (tasks + gateways)
	for child in adhoc:
		if child.tag in _LEAF_TASK_TAGS or child.tag in _GATEWAY_TAGS:
			node_id = child.get("id")
			if node_id:
				nodes[node_id] = child

	def spiff(el, attr):
		return el.get(f"{{{_SPIFF_NS}}}{attr}") or ""

	def documentation(el):
		doc_el = el.find(f"{{{_BPMN_NS}}}documentation")
		return (doc_el.text or "").strip() if doc_el is not None else ""

	def describe_effects(el):
		"""One-line behavior summary: what observably happens when this runs."""
		effects = []
		if spiff(el, "serviceType") == "update_field":
			try:
				rows = json.loads(spiff(el, "updateFieldRows") or "[]")
				target = spiff(el, "updateFieldDoctype") or "context document"
				for row in rows:
					effects.append(f"sets {target}.{row.get('field')} = \"{row.get('value')}\"")
			except Exception:
				pass
		script_name = spiff(el, "serverScript")
		if script_name:
			keys = _server_script_result_keys(script_name)
			if keys:
				effects.append(
					"runs Server Script \"%s\" which sets process variable(s): %s"
					% (script_name, ", ".join(keys))
				)
			else:
				effects.append(f'runs Server Script "{script_name}"')
		else:
			script_el = el.find(f"{{{_BPMN_NS}}}script")
			if script_el is not None and (script_el.text or "").strip():
				effects.append(f"runs inline script: {script_el.text.strip()[:120]}")
		if spiff(el, "notificationName"):
			effects.append(f'sends notification "{spiff(el, "notificationName")}"')
		if el.tag == f"{{{_BPMN_NS}}}userTask":
			assignee = spiff(el, "assigneeDocfield") or spiff(el, "assigneeMode")
			effects.append(
				"waits for a human"
				+ (f" (assigned from docfield '{assignee}')" if assignee else "")
			)
		return "; ".join(effects)

	def walk_chain(start_id, seen=None):
		"""Follow sequence flows from a candidate, describing the automatic
		continuation (through gateways) until the chain ends."""
		seen = seen or set()
		steps = []
		queue = list(flows.get(start_id, []))
		while queue:
			node_id = queue.pop(0)
			if node_id in seen:
				continue
			seen.add(node_id)
			el = nodes.get(node_id)
			if el is None:
				continue
			if el.tag in _GATEWAY_TAGS:
				queue.extend(flows.get(node_id, []))
				continue
			effect = describe_effects(el)
			label = el.get("name") or node_id
			steps.append(f"{label}" + (f" — {effect}" if effect else ""))
			queue.extend(flows.get(node_id, []))
		return steps

	candidate_lines = []
	candidate_ids = []
	for node_id, el in nodes.items():
		if el.tag not in _LEAF_TASK_TAGS or node_id in has_incoming:
			continue
		candidate_ids.append(node_id)
		line = f'- id: {node_id} | "{el.get("name") or node_id}" | {_LEAF_TASK_TAGS[el.tag]}'
		doc_text = documentation(el)
		if doc_text:
			line += f"\n    description: {doc_text}"
		effects = describe_effects(el)
		if effects:
			line += f"\n    when activated: {effects}"
		chain = walk_chain(node_id)
		if chain:
			line += "\n    then AUTOMATICALLY (do not activate these): " + " → ".join(chain)
		candidate_lines.append(line)

	condition_el = adhoc.find(f"{{{_BPMN_NS}}}completionCondition")
	condition = (condition_el.text or "").strip() if condition_el is not None else ""

	block_parts = [
		f'AD-HOC SUBPROCESS DIGEST ("{adhoc.get("name") or adhoc.get("id")}"):',
		"SELECTABLE TASKS (the model's tools, named by id):",
		"\n".join(candidate_lines) or "  (none)",
	]

	# The AI Agent Tool registry was removed (WI-001423) — a selector's tools
	# are the ad-hoc sub-process's own shapes, already listed above.
	if condition:
		block_parts.append(
			f"COMPLETION CONDITION (Python expression over process variables): {condition}\n"
			"The subprocess ends when this becomes true."
		)

	return {
		"block": "\n\n".join(block_parts),
		"candidate_ids": candidate_ids,
		"element_ids": set(nodes.keys()),
	}


def _server_script_result_keys(script_name: str) -> list:
	"""Sniff which process variables a BPMN Server Script sets: the engine
	merges the injected ``result`` dict into task data, so result["key"]
	assignments become Jinja-visible variables."""
	import re as _re

	if not frappe.db.exists("Server Script", script_name):
		return []
	if not frappe.has_permission("Server Script", "read"):
		return []
	script = frappe.db.get_value("Server Script", script_name, "script") or ""
	keys = _re.findall(r"result\[\s*['\"](\w+)['\"]\s*\]", script)
	seen, ordered = set(), []
	for key in keys:
		if key not in seen:
			seen.add(key)
			ordered.append(key)
	return ordered


def _lint_recommended_prompts(recommendations: dict, digest: dict) -> list:
	"""Cross-check recommended prompts against the real diagram: flag task-id
	lookalikes that don't exist, and candidates the procedure never mentions."""
	import re as _re

	text = " ".join(
		str(recommendations.get(key) or "")
		for key in ("aiSystemPrompt", "aiUserPrompt")
	)
	if not text.strip():
		return []

	warnings = []
	known = digest["element_ids"] | set(digest["candidate_ids"])
	mentioned_ids = set(_re.findall(r"\b(?:Activity|Task|Gateway|Event)_[0-9A-Za-z]+\b", text))
	unknown = sorted(mentioned_ids - known)
	if unknown:
		warnings.append(
			"These task ids in the suggested prompts do not exist on the diagram: "
			+ ", ".join(unknown)
		)

	if recommendations.get("aiSystemPrompt"):
		unmentioned = sorted(
			c for c in digest["candidate_ids"] if c not in str(recommendations["aiSystemPrompt"])
		)
		if unmentioned:
			warnings.append(
				"The suggested procedure never mentions these selectable tasks: "
				+ ", ".join(unmentioned)
			)
	return warnings


# ---------------------------------------------------------------------------
# Context gathering (permission-aware)
# ---------------------------------------------------------------------------

def _build_context_block(doctype: str, docname: str) -> str:
	if not doctype:
		return ""

	# Do not expose schema for DocTypes the current user cannot read —
	# frappe.get_meta() does not enforce permissions.
	if not frappe.has_permission(doctype, "read"):
		return ""

	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return ""

	field_lines = []
	for f in meta.fields:
		if f.fieldtype in _SKIP_FIELDTYPES:
			continue
		line = f"  - {f.fieldname} ({f.fieldtype})"
		if f.label:
			line += f" — {f.label}"
		if f.options and f.fieldtype in ("Link", "Select"):
			opts = str(f.options).replace("\n", ", ")
			line += f" [{opts}]"
		field_lines.append(line)
		if len(field_lines) >= _MAX_SCHEMA_FIELDS:
			break

	block = f"CONTEXT DOCTYPE: {doctype}\nFIELDS:\n" + "\n".join(field_lines)

	sample_name = docname
	if not sample_name:
		try:
			rows = frappe.get_list(doctype, fields=["name"], limit=1, order_by="modified desc")
			if rows:
				sample_name = rows[0]["name"]
		except Exception:
			sample_name = ""

	if sample_name:
		try:
			# get_doc enforces read permission for the current user.
			doc = frappe.get_doc(doctype, sample_name)
			data = {
				k: v
				for k, v in doc.as_dict().items()
				if not k.startswith("_") and not isinstance(v, (list, dict))
			}
			sample_json = frappe.as_json(data)[:_MAX_SAMPLE_CHARS]
			block += f"\n\nSAMPLE RECORD ({sample_name}):\n{sample_json}"
		except frappe.PermissionError:
			block += "\n\n(Sample record omitted — no read permission.)"
		except Exception:
			pass

	return block


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_history(history: str) -> list:
	try:
		turns = json.loads(history or "[]")
	except Exception:
		return []
	return turns if isinstance(turns, list) else []


def _extract_json(text: str):
	"""Tolerantly extract a JSON object from a model reply.

	Handles plain JSON, fenced ```json blocks, and prose wrapped around an
	object. Returns the parsed object/dict, or None if nothing parses.

	strict=False because models routinely emit literal newlines inside JSON
	string values (invalid per the spec, rejected by strict json.loads).
	Dropping such a reply loses its proposed_config — the confirm/create
	card never renders and the whole raw blob shows in chat as the message.
	"""
	if not text:
		return None
	text = text.strip()

	# Strip markdown code fences if present.
	if text.startswith("```"):
		text = text.strip("`")
		if text[:4].lower() == "json":
			text = text[4:]
		text = text.strip()

	try:
		return json.loads(text, strict=False)
	except Exception:
		pass

	start = text.find("{")
	end = text.rfind("}")
	if start != -1 and end != -1 and end > start:
		try:
			return json.loads(text[start:end + 1], strict=False)
		except Exception:
			return None
	return None


# ── Shared-endpoint integration (WI-001674) ──────────────────────────────────
# The dialog's chat is served through the AG-UI endpoint: the modal sends its
# raw grounding refs as context.assistant_dialog, the builder below turns them
# into the dialog_context the assistant's map renders, and the shaper parses
# the map's JSON contract out of the reply BEFORE any text reaches a bubble —
# which is what makes the raw-JSON-in-the-transcript failure structurally
# impossible. recommend_ai_task_config stays as the deprecated alias for the
# legacy modal path until WI-001679 retires it.


def build_assistant_turn_context(context: dict) -> dict:
	"""Turn the modal's raw grounding into the map's dialog_context."""
	grounding = (context or {}).pop("assistant_dialog", None)
	if not isinstance(grounding, dict):
		return context or {}

	catalog = _catalog_for_mode("agent")
	dialog_context_parts = [
		_creation_capability_block(),
		(
			"PROCESS MODEL OPEN IN THE EDITOR: '{0}' — this is the exact BPMN "
			"Process Model record name. Use it VERBATIM as "
			"proposed_config.process_model when the agent should be mapped to "
			"this process; the human-facing process or diagram title is a "
			"different string and will be rejected.".format(grounding["process_model"])
			if grounding.get("process_model")
			else ""
		),
		_linked_config_block(grounding.get("linked_config") or ""),
		_build_full_diagram_block(grounding.get("bpmn_xml") or "", grounding.get("element_id") or ""),
		_build_context_block(
			grounding.get("context_doctype") or "", grounding.get("context_docname") or ""
		),
		_build_current_config_block(
			grounding.get("current_config") or "{}", catalog
		),
	]
	# Recency wins with LLMs: the emission rules go LAST, after every
	# reference block. Diagnosed on a live thread (f0llmt6v4c): with the
	# contract mid-context, the approval turn answered message-only and
	# claimed it had created the agent — which it cannot do.
	dialog_context_parts.append(
		"FINAL OUTPUT RULES (these override anything above):\n"
		"- You can NEVER create, update or submit anything yourself. Never say "
		"you created or updated an agent, and never describe a proposal as "
		"submitted or in validation.\n"
		"- While details are missing, ask for them via \"message\" only.\n"
		"- The turn in which the designer APPROVES a complete new-agent "
		"proposal MUST include \"proposed_config\" in your JSON reply (and "
		"changes to an existing agent MUST use \"proposed_update\"). The UI "
		"renders it as a card; creation happens only when the designer "
		"confirms there. A reply that promises creation without "
		"\"proposed_config\" is a contract violation."
	)
	out = dict(context or {})
	out["dialog_context"] = "\n\n".join(p for p in dialog_context_parts if p)
	out["source"] = "task_dialog"
	return out


def shape_assistant_reply(result: dict) -> dict:
	"""Parse the assistant map's JSON reply contract into typed keys.

	The human message becomes the visible response; recommendations are
	catalog-filtered and proposals sanitized exactly as the legacy path did
	— the WI-001671 translators then lift them into onefm.* events."""
	raw = result.get("response") or ""
	parsed = _extract_json(raw if isinstance(raw, str) else json.dumps(raw))
	if not isinstance(parsed, dict):
		return result

	catalog = _catalog_for_mode("agent")
	message = str(parsed.get("message", "")).strip()
	recommendations = {
		key: value
		for key, value in (parsed.get("recommendations") or {}).items()
		if key in catalog and value not in (None, "")
	}
	shaped = dict(result)
	shaped["response"] = message or (raw if not recommendations else "")
	if recommendations:
		shaped["recommendations"] = recommendations
	proposed_config = _sanitize_proposed_config(parsed.get("proposed_config"))
	if proposed_config:
		shaped["proposed_config"] = proposed_config
	proposed_update = _sanitize_proposed_update(parsed.get("proposed_update"))
	if proposed_update:
		shaped["proposed_update"] = proposed_update
	return shaped


def _register_agui_hooks():
	from one_bpmn.agents.agui_stream import register_context_builder, register_reply_shaper

	register_context_builder("ai_agent_assistant", build_assistant_turn_context)
	register_reply_shaper("ai_agent_assistant", shape_assistant_reply)


_register_agui_hooks()
