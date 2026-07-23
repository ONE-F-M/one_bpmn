# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Resolve an AI Agent Configuration reference on an AI task/selector shape
(WI-001637, live-link amendment 2026-07-17).

A shape may set ``aiAgentConfig`` (a link to an AI Agent Configuration) as
an alternative to entering a raw provider. The link is LIVE:

* **At dispatch, the configuration is authoritative** for agent-level
  fields (system prompt, provider, model, temperature, max tokens) —
  ``resolve_dispatch_overrides`` supplies them and the dispatchers overlay
  them onto the shape's attributes. The shape's copies are an editing view
  and the fallback when the configuration has been deleted. Shape-only
  fields (output variable, response format/schema, retries, memory, tool
  wiring) describe the task, not the agent, and stay shape-owned.
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

# Which config field feeds which shape attribute. Only executable fields
# with a task-shape equivalent are mapped; chat-only metadata (chat mode
# label, icon, roles, lifecycle, eval suite, sample prompts) has no shape
# meaning and is intentionally omitted.
_CONFIG_TO_SHAPE = {
	"system_prompt": "aiSystemPrompt",
	"temperature": "aiTemperature",
	"max_tokens": "aiMaxTokens",
}

# Shape attributes the modal may write back, and the config fields they land
# in. aiModel is deliberately absent: the configuration derives its model from
# the linked credentials' default, so a model typed on the shape is a
# shape-local override, not an agent property.
_SHAPE_TO_CONFIG = {
	"aiSystemPrompt": "system_prompt",
	"aiTemperature": "temperature",
	"aiMaxTokens": "max_tokens",
	"aiProvider": "ai_provider_credentials",
}

# The platform process that carries an agent Draft -> Live. Used to re-provision
# a Live agent after a write-back; missing model = skip with a log, never block.
CREATION_PROCESS_MODEL = "AI Agent Creation Process"


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
	if cfg.ai_provider_credentials:
		out["aiProvider"] = cfg.ai_provider_credentials
		model = frappe.db.get_value("AI Provider Credentials", cfg.ai_provider_credentials, "default_model")
		if model:
			out["aiModel"] = model
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
		if doc.get(cfield) != value:
			doc.set(cfield, value)
			changed.append(cfield)

	if not changed:
		return {"ok": True, "updated": [], "reprovisioned": False}

	was_live = doc.lifecycle_status == "Live"
	doc.save()

	reprovisioned = False
	if was_live:
		reprovisioned = _start_reprovision(doc.name)

	return {"ok": True, "updated": changed, "reprovisioned": reprovisioned}


def _start_reprovision(config_name: str) -> bool:
	"""Send a Live agent back through the creation process after a write-back.

	The process's start event is After-Insert only, so an existing record
	needs an explicit instance start. Skipped (with a log) when the creation
	model is missing/inactive or an instance is already running for this
	agent — the running one will pick up the saved values itself.
	"""
	if not frappe.db.get_value("BPMN Process Model", CREATION_PROCESS_MODEL, "is_active"):
		frappe.log_error(
			title=f"Re-provision skipped for {config_name}",
			message=f"'{CREATION_PROCESS_MODEL}' is missing or inactive.",
		)
		return False

	already_running = frappe.db.exists(
		"BPMN Process Instance",
		{
			"process_model": CREATION_PROCESS_MODEL,
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
			CREATION_PROCESS_MODEL,
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
