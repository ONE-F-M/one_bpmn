# Copyright (c) 2026, one-fm and contributors
"""The shapes of an ad-hoc sub-process resolved into the tools of an AI Agent Task or AI Task Selector."""

import json


_AI_AGENT_AUTO_TAGS = frozenset({"scriptTask", "serviceTask"})
_AI_AGENT_HUMAN_TAGS = frozenset({"userTask", "manualTask"})
_AI_AGENT_TOOL_TAGS = _AI_AGENT_AUTO_TAGS | _AI_AGENT_HUMAN_TAGS

# Arguments a human tool takes when its shape sets no aiToolParams.
_DEFAULT_HUMAN_TOOL_PARAMS = {
	"request": {
		"type": "string",
		"description": "What you need from the person - shown with the task.",
	}
}


def resolve_ai_agent_tool_shapes(bpmn_xml: str, service_extensions: dict) -> None:
	"""Embed aiToolShapes on each AI Agent Task and AI Task Selector from the ad-hoc sub-process holding its tools."""
	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	agents = ai_agents_with_tools(service_extensions)
	selectors = _ai_selectors_with_tools(service_extensions)
	if not agents and not selectors:
		return
	adhocs = index_adhoc_subprocesses(bpmn_xml, BPMN_NS)
	if adhocs is None:
		return
	for agent_id, cfg in agents.items():
		adhoc = adhocs.get((cfg.get("aiToolsAdhoc") or "").strip())
		if adhoc is None:
			continue  # validate_ai_agent_tools reports the missing reference
		cfg["aiToolShapes"] = json.dumps(_tools_for_agent(_extract_tool_shapes(adhoc, BPMN_NS, SPIFF_NS), agent_id))
	for bpmn_id, cfg in selectors.items():
		adhoc = adhocs.get(bpmn_id)
		if adhoc is None:
			continue
		cfg["aiToolShapes"] = json.dumps(_tools_for_agent(_extract_tool_shapes(adhoc, BPMN_NS, SPIFF_NS), bpmn_id))


def _extract_tool_shapes(adhoc_el, bpmn_ns: str, spiff_ns: str) -> list:
	"""Tool descriptors for the eligible leaf shapes of an ad-hoc sub-process; User and Manual Tasks become human tools."""
	shapes = []
	for child in list(adhoc_el):
		tag = child.tag.split("}")[-1]
		if tag not in _AI_AGENT_TOOL_TAGS:
			continue
		bpmn_id = child.get("id")
		if not bpmn_id:
			continue
		is_human = tag in _AI_AGENT_HUMAN_TAGS
		server_script = child.get(f"{{{spiff_ns}}}serverScript", "")
		service_type = child.get(f"{{{spiff_ns}}}serviceType", "")
		if not is_human and not (server_script or service_type):
			continue
		doc_el = child.find(f"{{{bpmn_ns}}}documentation")
		description = (doc_el.text or "").strip() if doc_el is not None and doc_el.text else ""
		shape = {"bpmn_id": bpmn_id, "description": description}
		if is_human:
			shape["human"] = True
			shape["label"] = (child.get("name") or "").strip()
		if server_script:
			shape["serverScript"] = server_script
			ai_agent_config = child.get(f"{{{spiff_ns}}}aiAgentConfig", "")
			if ai_agent_config:
				shape["aiAgentConfig"] = ai_agent_config
		tool_for = (child.get(f"{{{spiff_ns}}}aiToolFor") or "").strip()
		if tool_for:
			shape["toolFor"] = tool_for
		if service_type:
			for attr_name, attr_value in child.attrib.items():
				if not attr_name.startswith(f"{{{spiff_ns}}}"):
					continue
				key = attr_name[len(f"{{{spiff_ns}}}") :]
				if key == "aiToolParams":
					continue
				shape[key] = attr_value
		for attr, value in child.attrib.items():
			if attr.startswith(f"{{{spiff_ns}}}allowed"):
				key = attr.split("}", 1)[1]
				if str(value).strip():
					import re as _re

					# frappe.scrub only lower-cases, so allowedStates would lose its word break.
					snake = _re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
					shape[snake] = str(value).strip()
		tool_params_raw = child.get(f"{{{spiff_ns}}}aiToolParams", "")
		if tool_params_raw:
			try:
				tool_params = json.loads(tool_params_raw)
			except Exception:
				tool_params = {}
			if isinstance(tool_params, dict):
				properties = tool_params.get("properties")
				if isinstance(properties, dict) and properties:
					shape["parameters"] = properties
				required = tool_params.get("required")
				if isinstance(required, list) and required:
					shape["required"] = required
		if is_human and not shape.get("parameters"):
			shape["parameters"] = dict(_DEFAULT_HUMAN_TOOL_PARAMS)
			shape["required"] = ["request"]
		shapes.append(shape)
	return shapes


def ai_agents_with_tools(service_extensions: dict) -> dict:
	"""AI Agent Tasks that name a tools sub-process, keyed by bpmn_id."""
	return {
		bid: cfg
		for bid, cfg in (service_extensions or {}).items()
		if cfg.get("serviceType") == "ai_agent" and (cfg.get("aiToolsAdhoc") or "").strip()
	}


def index_adhoc_subprocesses(bpmn_xml: str, bpmn_ns: str):
	"""Ad-hoc sub-process elements keyed by id, or None when the XML does not parse."""
	import xml.etree.ElementTree as _ET

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return None
	return {el.get("id"): el for el in root.iter(f"{{{bpmn_ns}}}adHocSubProcess") if el.get("id")}


def _ai_selectors_with_tools(service_extensions: dict) -> dict:
	"""AI Task Selectors keyed by their own bpmn_id, since each one is its own tools box."""
	return {
		bid: cfg
		for bid, cfg in (service_extensions or {}).items()
		if cfg.get("serviceType") == "ai_task_selector"
	}


def _tools_for_agent(shapes: list, agent_id: str) -> list:
	"""The shapes of a box this agent may call: those marked aiToolFor it, else the unmarked shapes other than itself."""
	own = [s for s in shapes if s.get("toolFor") == agent_id]
	if own:
		return own
	return [s for s in shapes if not s.get("toolFor") and s.get("bpmn_id") != agent_id]
