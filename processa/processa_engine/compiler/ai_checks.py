# Copyright (c) 2026, one-fm and contributors
"""Deploy checks that refuse a map over its AI shapes: ad-hoc structure, agent configuration, tools and prompts."""

import json
import re

import frappe
from frappe import _

from processa.processa_engine.compiler.agent_tools import ai_agents_with_tools, index_adhoc_subprocesses


def validate_adhoc_structure(bpmn_xml: str) -> None:
	"""Refuse an ad-hoc sub-process that holds a start or end event or has no activity."""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	EVENT_TAGS = {
		f"{{{BPMN_NS}}}startEvent": _("Start Event"),
		f"{{{BPMN_NS}}}endEvent": _("End Event"),
	}
	ACTIVITY_TAGS = {
		f"{{{BPMN_NS}}}task",
		f"{{{BPMN_NS}}}userTask",
		f"{{{BPMN_NS}}}manualTask",
		f"{{{BPMN_NS}}}scriptTask",
		f"{{{BPMN_NS}}}serviceTask",
		f"{{{BPMN_NS}}}sendTask",
		f"{{{BPMN_NS}}}receiveTask",
		f"{{{BPMN_NS}}}businessRuleTask",
		f"{{{BPMN_NS}}}subProcess",
		f"{{{BPMN_NS}}}adHocSubProcess",
		f"{{{BPMN_NS}}}callActivity",
		f"{{{BPMN_NS}}}transaction",
	}

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return

	for adhoc in root.iter(f"{{{BPMN_NS}}}adHocSubProcess"):
		adhoc_id = adhoc.get("id", "?")

		for child in adhoc:
			if child.tag in EVENT_TAGS:
				frappe.throw(
					_(
						"Ad-hoc Subprocess '{0}': a {1} ('{2}') is not allowed "
						"inside an ad-hoc subprocess. Its inner activities start "
						"ad hoc - delete the event."
					).format(adhoc_id, EVENT_TAGS[child.tag], child.get("id", "?")),
					exc=frappe.ValidationError,
				)

		if not any(child.tag in ACTIVITY_TAGS for child in adhoc):
			frappe.throw(
				_(
					"Ad-hoc Subprocess '{0}' must contain at least one activity."
				).format(adhoc_id),
				exc=frappe.ValidationError,
			)


def validate_adhoc_selector_pool(bpmn_xml: str, model_name: str | None = None) -> None:
	"""Refuse a container activity among an AI Task Selector's unconnected candidates."""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	CONTAINER_TAGS = {
		f"{{{BPMN_NS}}}subProcess": "Sub-Process",
		f"{{{BPMN_NS}}}adHocSubProcess": "Ad-hoc Subprocess",
		f"{{{BPMN_NS}}}callActivity": "Call Activity",
		f"{{{BPMN_NS}}}transaction": "Transaction",
	}

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return

	def has_incoming(element):
		return element.find(f"{{{BPMN_NS}}}incoming") is not None

	for adhoc in root.iter(f"{{{BPMN_NS}}}adHocSubProcess"):
		if adhoc.get(f"{{{SPIFF_NS}}}serviceType") != "ai_task_selector":
			continue

		adhoc_id = adhoc.get("id", "?")

		for child in adhoc:
			if has_incoming(child):
				continue  # connected flow, not a selector candidate
			if child.tag in CONTAINER_TAGS:
				frappe.throw(
					_(
						"AI Task Selector '{0}': {1} '{2}' cannot be a selector "
						"candidate - only leaf task activities (Script, Service, "
						"Send, User/Manual, Business Rule) are eligible. Connect "
						"it with a sequence flow or move it out of the subprocess."
					).format(adhoc_id, CONTAINER_TAGS[child.tag], child.get("id", "?")),
					exc=frappe.ValidationError,
				)


def lint_ai_provider_config(_bpmn_xml: str, service_extensions: dict) -> None:
	"""Refuse a raw API key on an AI shape, and an AI shape with no enabled, Live AI Agent Configuration."""
	import re
	_RAW_KEY_RE = re.compile(r"^(sk-|key-)", re.IGNORECASE)
	_RAW_KEY_ATTR_NAMES = frozenset({"aiApiKey", "aiKey"})

	for bpmn_id, task_cfg in (service_extensions or {}).items():
		service_type = task_cfg.get("serviceType")
		if service_type not in ("ai_agent", "ai_task_selector"):
			continue

		for attr_name, attr_value in task_cfg.items():
			if attr_name in _RAW_KEY_ATTR_NAMES or _RAW_KEY_RE.match(str(attr_value)):
				frappe.throw(
					_(
						"Raw API keys must not appear in BPMN XML "
						"(task '{0}', attribute '{1}'). "
						"Use an AI Provider reference."
					).format(bpmn_id, attr_name),
					exc=frappe.ValidationError,
				)

		agent_config = (task_cfg.get("aiAgentConfig") or "").strip()

		if agent_config:
			cfg_row = frappe.db.get_value(
				"AI Agent Configuration", agent_config, ["enabled", "lifecycle_status"], as_dict=True
			)
			if not cfg_row:
				frappe.throw(
					_("Referenced AI Agent Configuration '{0}' not found (task '{1}').").format(agent_config, bpmn_id),
					exc=frappe.ValidationError,
				)
			if not cfg_row.enabled:
				frappe.throw(
					_("Referenced AI Agent Configuration '{0}' is disabled (task '{1}').").format(agent_config, bpmn_id),
					exc=frappe.ValidationError,
				)
			if cfg_row.lifecycle_status != "Live":
				frappe.throw(
					_(
						"AI Agent Configuration '{0}' is {1} (task '{2}'). "
						"Wait for it to reach Live - or repair it - before deploying."
					).format(agent_config, cfg_row.lifecycle_status or "Draft", bpmn_id),
					exc=frappe.ValidationError,
				)

		if not agent_config:
			frappe.throw(
				_(
					"AI shape '{0}' has no linked AI Agent Configuration. Link an "
					"existing agent or create one from the task dialog - setting up "
					"an AI task with a raw provider has been retired."
				).format(bpmn_id),
				exc=frappe.ValidationError,
			)


def validate_ai_agent_tools(bpmn_xml: str, service_extensions: dict) -> None:
	"""Refuse an AI Agent Task whose tools sub-process is missing or holds no eligible tool shape."""
	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	agents = ai_agents_with_tools(service_extensions)
	if not agents:
		return
	adhocs = index_adhoc_subprocesses(bpmn_xml, BPMN_NS) or {}
	for agent_id, cfg in agents.items():
		adhoc_id = (cfg.get("aiToolsAdhoc") or "").strip()
		if adhoc_id not in adhocs:
			frappe.throw(
				_(
					"AI Agent Task '{0}' references ad-hoc sub-process '{1}', "
					"which does not exist. Point it at the sub-process that holds its tools."
				).format(agent_id, adhoc_id),
				exc=frappe.ValidationError,
			)
		shapes = json.loads(cfg.get("aiToolShapes") or "[]")
		if not shapes:
			frappe.throw(
				_(
					"AI Agent Task '{0}' references ad-hoc sub-process '{1}', which has no "
					"eligible tool shapes (Script tasks with a Server Script, Service "
					"tasks with a service type, or User/Manual tasks as human tools). "
					"Add at least one tool."
				).format(agent_id, adhoc_id),
				exc=frappe.ValidationError,
			)


def validate_ai_max_tokens(service_extensions: dict) -> None:
	"""Refuse an AI Agent Task whose Max Tokens is set but is not a whole number above 0."""
	for bpmn_id, cfg in (service_extensions or {}).items():
		if (cfg or {}).get("serviceType") != "ai_agent" or cfg.get("aiMaxTokens") is None:
			continue
		text = str(cfg.get("aiMaxTokens")).strip()
		if not text.isdigit() or int(text) <= 0:
			frappe.throw(
				_("Max tokens must be a positive number (AI Agent Task {0})").format(bpmn_id),
				exc=frappe.ValidationError,
			)


# A tool name in a calling position, after call, use or invoke.
_TOOL_CALL_RE = re.compile(
	r"\b(?:call|calls|calling|called|use|uses|using|invoke|invokes|invoking)\s+`?([a-z][a-z0-9_]{2,})`?",
	re.I,
)


# A snake_case name in backticks; it counts only when some map has a tool of that name.
_TOOL_BACKTICK_RE = re.compile(r"`([a-z][a-z0-9]*(?:_[a-z0-9]+)+)`")


def validate_ai_tool_contract(service_extensions: dict) -> None:
	"""Refuse a deploy when an agent's instructions name a tool its Tools box does not hold."""
	agents = ai_agents_with_tools(service_extensions)
	if not agents:
		return
	known = _known_tool_ids()
	blocking = []
	for agent_id, cfg in agents.items():
		tool_ids = {s.get("bpmn_id") for s in json.loads(cfg.get("aiToolShapes") or "[]")}
		shape_prompt = cfg.get("aiSystemPrompt") or ""
		config_prompt = ""
		config_name = (cfg.get("aiAgentConfig") or "").strip()
		if config_name and frappe.db.exists("AI Agent Configuration", config_name):
			config_prompt = (
				frappe.db.get_value("AI Agent Configuration", config_name, "system_prompt") or ""
			)
		# A linked configuration's prompt is what reaches the model, not the shape's copy.
		instructions = "\n".join(
			p for p in (config_prompt or shape_prompt, cfg.get("aiUserPrompt") or "") if p
		)
		gaps = _tool_contract_gaps(instructions, tool_ids, known)
		if not gaps:
			continue
		adhoc_id = (cfg.get("aiToolsAdhoc") or "").strip() or "?"
		detail = _(
			"Instructions for '{0}' reference tool {1}, which does not exist in Tools box '{2}'. "
			"Fix the instructions or add the shape."
		).format(agent_id, ", ".join(f"'{g}'" for g in gaps), adhoc_id)
		blocking.append(detail)
	if blocking:
		frappe.throw(
			_("The prompt and the Tools box disagree:") + "\n" + "\n".join(f"• {b}" for b in blocking),
			exc=frappe.ValidationError,
		)


def _known_tool_ids() -> set:
	"""Every tool id in any active map's compiled spec, so a bare word after call counts only when it is a real tool."""
	ids = set()
	for spec in frappe.get_all("BPMN Process Model", filters={"is_active": 1}, pluck="serialized_spec"):
		try:
			exts = (json.loads(spec or "{}") or {}).get("service_task_extensions") or {}
		except ValueError:
			continue
		for cfg in exts.values():
			for shape in json.loads((cfg or {}).get("aiToolShapes") or "[]"):
				if shape.get("bpmn_id"):
					ids.add(shape["bpmn_id"])
	return ids


def _tool_contract_gaps(prompt: str, tool_ids: set, known_ids: set) -> list:
	"""Names the prompt tells the model to call that are not in its own Tools box."""
	from processa.ai_agent_skills.skill_tools import SKILL_TOOL_NAMES

	# Skill tools are added at dispatch for any linked configuration, so no box holds them.
	tool_ids = set(tool_ids) | SKILL_TOOL_NAMES
	called = {m.lower() for m in _TOOL_CALL_RE.findall(prompt or "")}
	gaps = {n for n in called if n not in tool_ids and ("_" in n or n in known_ids)}
	quoted = {m.lower() for m in _TOOL_BACKTICK_RE.findall(prompt or "")}
	gaps |= {n for n in quoted if n not in tool_ids and n in known_ids}
	return sorted(gaps)
