"""
WI-001650: retire raw-provider AI shapes.

Every LLM-calling shape (AI Agent Task / AI Task Selector) must be backed by
an AI Agent Configuration; the compile gate now blocks config-less shapes.
This patch brings existing site data under the rule:

1. Seeds the "Platform Prompt Engineer" configuration — a Background-type
   provider grant (EMPTY system prompt, so process shapes keep their own
   prompts; the config pins the platform provider) — and links the AI Agent
   Creation Process's own AI tasks to it.
2. Deletes junk models (ai-test-model-*, ZZ leftovers, the stray
   chat_agent_map_template duplicate); models with instances are
   deactivated instead.
3. Links chat-clone maps to their existing agent configuration, and creates
   minimal provider-grant configurations for process-embedded agents
   (AI ToDo Triage, ProsAlly) — full endpoint migration stays WI-001630-35.

Idempotent: models already carrying aiAgentConfig are skipped.
"""

import frappe
import xml.etree.ElementTree as ET

_B = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"
_S = "{http://spiffworkflow.org/bpmn/schema/1.0/core}"

PLATFORM_AGENT_ID = "platform_prompt_engineer"
PLATFORM_AGENT_NAME = "Platform Prompt Engineer"
CREATION_MODEL = "AI Agent Creation Process"

_JUNK_PREFIXES = ("ai-test-model-", "ZZ ")
_JUNK_EXACT = {"chat_agent_map_template"}


def execute():
	if not frappe.db.exists("DocType", "AI Agent Configuration"):
		return

	platform = _seed_platform_config()

	for m in frappe.get_all("BPMN Process Model", fields=["name", "title", "is_active", "bpmn_xml"]):
		xml = m.bpmn_xml or ""
		shapes = _raw_ai_shapes(xml)

		if _is_junk(m.name) or _is_junk(m.title or ""):
			_remove_model(m.name)
			continue

		if not m.is_active or not shapes or "aiAgentConfig" in xml:
			continue  # inactive stays grandfathered; linked models are done

		if m.name == CREATION_MODEL:
			config = platform
		else:
			config = _config_for_chat_clone(m.name) or _create_provider_grant(m, shapes)
		if not config:
			frappe.log_error(
				title=f"WI-001650 backfill skipped: {m.name}",
				message="No configuration could be resolved or created for its AI shapes.",
			)
			continue

		_link_and_recompile(m.name, xml, config)

	frappe.db.commit()


def _raw_ai_shapes(xml: str) -> list:
	"""BPMN ids of ai_agent / ai_task_selector shapes without aiAgentConfig."""
	if "ai_agent" not in xml and "ai_task_selector" not in xml:
		return []
	try:
		root = ET.fromstring(xml.strip().encode("utf-8"))
	except Exception:
		return []
	out = []
	for el in list(root.iter(f"{_B}serviceTask")) + list(root.iter(f"{_B}adHocSubProcess")):
		if el.get(f"{_S}serviceType") in ("ai_agent", "ai_task_selector") and not el.get(f"{_S}aiAgentConfig"):
			out.append({
				"id": el.get("id"),
				"provider": el.get(f"{_S}aiProvider") or "",
			})
	return out


def _is_junk(name: str) -> bool:
	return name in _JUNK_EXACT or any(name.startswith(p) for p in _JUNK_PREFIXES)


def _remove_model(name: str):
	if not frappe.db.exists("BPMN Process Model", name):
		return
	if frappe.db.exists("BPMN Process Instance", {"process_model": name}):
		# History exists — deactivate instead of breaking instance links.
		frappe.db.set_value("BPMN Process Model", name, "is_active", 0, update_modified=False)
	else:
		frappe.delete_doc("BPMN Process Model", name, force=True, ignore_permissions=True)


def _seed_platform_config() -> str | None:
	existing = frappe.db.get_value("AI Agent Configuration", {"agent_id": PLATFORM_AGENT_ID}, "name")
	if existing:
		return existing
	credentials = frappe.db.get_value(
		"AI Provider Credentials", {"provider_type": "Anthropic", "enabled": 1}, "name"
	) or frappe.db.get_value("AI Provider Credentials", {"enabled": 1}, "name")
	if not credentials:
		return None
	doc = frappe.new_doc("AI Agent Configuration")
	doc.agent_name = PLATFORM_AGENT_NAME
	doc.agent_id = PLATFORM_AGENT_ID
	doc.agent_framework = "Direct API"
	# Background: never trips the chat-agent creation trigger.
	doc.agent_type = "Background"
	doc.enabled = 1
	doc.ai_provider_credentials = credentials
	# DELIBERATELY empty system prompt: this configuration is a provider
	# grant. config_field_map skips empty fields, so linked shapes keep their
	# own prompts (the creation process's Assess and Generate prompts differ).
	doc.system_prompt = ""
	doc.description = (
		"Platform provider grant for the platform's own AI process shapes "
		"(e.g. the AI Agent Creation Process). Pins the provider; the shapes "
		"keep their own prompts."
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _config_for_chat_clone(model_name: str) -> str | None:
	"""The configuration a chat-clone map belongs to (its provisioner)."""
	rows = frappe.get_all(
		"AI Agent Configuration",
		filters={"process_model": model_name, "enabled": 1},
		fields=["name", "agent_id"],
		order_by="creation asc",
	)
	if not rows:
		return None
	# Prefer the seeded assistant when several configs share one map.
	for r in rows:
		if r.agent_id == "ai_agent_assistant":
			return r.name
	return rows[0].name


def _create_provider_grant(m, shapes: list) -> str | None:
	"""Minimal Background configuration for a process-embedded agent: pins the
	provider the shapes already use; empty prompt so shapes stay authoritative."""
	agent_name = f"{(m.title or m.name)} Agent"
	existing = frappe.db.get_value("AI Agent Configuration", {"agent_name": agent_name}, "name")
	if existing:
		return existing
	provider = next((s["provider"] for s in shapes if s["provider"]), None)
	if provider and not frappe.db.exists("AI Provider Credentials", provider):
		provider = None
	provider = provider or frappe.db.get_value("AI Provider Credentials", {"enabled": 1}, "name")
	if not provider:
		return None
	doc = frappe.new_doc("AI Agent Configuration")
	doc.agent_name = agent_name
	doc.agent_id = frappe.scrub(agent_name)
	doc.agent_framework = "Direct API"
	doc.agent_type = "Background"
	doc.enabled = 1
	doc.ai_provider_credentials = provider
	doc.system_prompt = ""
	doc.description = f'Provider grant backfilled for the "{m.title or m.name}" process (WI-001650).'
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _link_and_recompile(model_name: str, xml: str, config: str):
	"""Inject aiAgentConfig next to every raw AI serviceType attribute.

	String-level insertion (as chat_map_template does) keeps namespaces
	untouched; guarded by the caller's 'aiAgentConfig not in xml' check so a
	duplicate attribute can never be produced.
	"""
	from frappe.utils import escape_html

	attr = escape_html(config)
	new_xml = xml.replace(
		'spiffworkflow:serviceType="ai_agent"',
		f'spiffworkflow:serviceType="ai_agent" spiffworkflow:aiAgentConfig="{attr}"',
	).replace(
		'spiffworkflow:serviceType="ai_task_selector"',
		f'spiffworkflow:serviceType="ai_task_selector" spiffworkflow:aiAgentConfig="{attr}"',
	)
	if new_xml == xml:
		return
	frappe.db.set_value("BPMN Process Model", model_name, "bpmn_xml", new_xml, update_modified=False)
	try:
		from one_bpmn.api.compilation import compile_process_model

		compile_process_model(model_name)
	except Exception:
		frappe.log_error(
			title=f"WI-001650 recompile failed: {model_name}",
			message=frappe.get_traceback(),
		)
