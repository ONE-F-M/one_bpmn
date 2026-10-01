# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Helpers the ProsAlly tool scripts share: property preservation, JSON extraction, history, model calls."""

import json
import re
from xml.etree import ElementTree as ET

import frappe
from frappe import _

from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.agents.turn_state import run_sync
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

AGENT_ID = "prosally_agent"
HISTORY_TURNS = 10
MIN_STAGE_TOKENS = 16384

NS = {
	"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
	"bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
	"dc": "http://www.omg.org/spec/DD/20100524/DC",
	"di": "http://www.omg.org/spec/DD/20100524/DI",
	"spiffworkflow": "http://spiffworkflow.org/bpmn/schema/1.0/core",
	"custom": "http://custom/text-style",
	"camunda": "http://camunda.org/schema/1.0/bpmn",
}
EXTENSION_NS_URIS = (
	"{http://spiffworkflow.org/bpmn/schema/1.0/core}",
	"{http://custom/text-style}",
	"{http://camunda.org/schema/1.0/bpmn}",
)
ATTR_FAMILY_LABELS = {
	"serverScript": "Server Script",
	"assignmentMode": "Assignment Mode",
	"assigneeDocField": "Assignee (Doc Field)",
	"roundRobinRole": "Round Robin Role",
	"loadBalancingRole": "Load Balancing Role",
	"leaveRelieverEnabled": "Leave Reliever",
	"triggerType": "Trigger Type",
	"triggerDoctype": "Trigger DocType",
	"serviceType": "Service Type",
	"serviceTargetDoctype": "Target DocType",
	"workflowState": "Workflow State",
	"docStatus": "Doc Status",
	"emailSubject": "Email Subject",
	"emailTo": "Email To",
	"emailBody": "Email Body",
	"emailAccount": "Email Account",
	"gchatMessage": "Google Chat Message",
	"gchatSpaceId": "Google Chat Space",
	"pushTitle": "Push Notification Title",
	"pushMessage": "Push Notification Message",
	"updateFieldDoctype": "Update Field DocType",
	"updateFieldName": "Update Field Name",
	"updateFieldValue": "Update Field Value",
	"calledDecisionId": "Decision Table",
	"notificationName": "Notification",
	"fontFamily": "Font Family",
	"fontSize": "Font Size",
	"fontWeight": "Font Weight",
	"fontStyle": "Font Style",
	"textColor": "Text Color",
	"textDecoration": "Text Decoration",
	"assignee": "Assignee",
	"candidateGroups": "Candidate Groups",
	"candidateUsers": "Candidate Users",
	"formKey": "Form Key",
	"dueDate": "Due Date",
	"followUpDate": "Follow-Up Date",
	"priority": "Priority",
	"asyncBefore": "Async Before",
	"asyncAfter": "Async After",
}


def prosally_config() -> dict:
	"""ProsAlly's resolved agent configuration."""
	cfg = get_agent_config(AGENT_ID) or {}
	cfg.setdefault("agent_id", AGENT_ID)
	return cfg


def complete_sub_prompt(cfg: dict, sub_id: str, user: str, system: str | None = None, max_tokens=None) -> str:
	"""One model call with a sub-prompt as the system prompt, returning the reply text."""
	if system is None:
		system = ((cfg.get("sub_prompts") or {}).get(sub_id) or {}).get("prompt") or ""
	kwargs = {"system": system, "user": user}
	if max_tokens:
		kwargs["max_tokens"] = max_tokens
	return run_sync(get_llm_adapter_from_settings(cfg).complete(**kwargs)).text


def stage_system_prompt(cfg: dict, sub_id: str, skills_constant: str) -> str:
	"""A stage's sub-prompt followed by each Active skill named in the agent constant ``skills_constant``."""
	system = ((cfg.get("sub_prompts") or {}).get(sub_id) or {}).get("prompt") or ""
	names = [
		n.strip() for n in ((cfg.get("constants") or {}).get(skills_constant) or "").split(",") if n.strip()
	]
	skills = frappe.get_all(
		"AI Skill",
		filters={"name": ["in", names], "status": "Active"},
		fields=["name", "body"],
		order_by="name asc",
	)
	return "\n\n".join([system] + ["## Skill: " + sk.name + "\n\n" + sk.body for sk in skills])


def stage_max_tokens(cfg: dict) -> int:
	"""Output budget for a full IR: at least MIN_STAGE_TOKENS, at most what the model allows."""
	max_tokens = max(int(cfg.get("max_tokens") or 0), MIN_STAGE_TOKENS)
	ceiling = 0
	if cfg.get("ai_model"):
		ceiling = frappe.db.get_value("AI Model", cfg.get("ai_model"), "max_output_tokens") or 0
	if ceiling:
		max_tokens = min(max_tokens, int(ceiling))
	return max_tokens


def format_history(chat_history: list, agent_label: str = "ProsAlly") -> str:
	"""The last HISTORY_TURNS messages as "User: ..." lines and lines labelled with the agent's name."""
	lines = []
	for entry in (chat_history or [])[-HISTORY_TURNS:]:
		role = entry.get("role") or entry.get("type", "user")
		content = (entry.get("content") or "").strip()
		if content:
			lines.append(("User" if role == "user" else agent_label) + ": " + content)
	return "\n".join(lines)


def extract_json(raw: str) -> dict | None:
	"""The first JSON object found in a model reply: whole, fenced, or embedded in prose."""
	if not raw:
		return None
	stripped = raw.strip()
	candidates = [stripped]
	fenced = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", raw)
	if fenced:
		candidates.append(fenced.group(1).strip())
	greedy = re.search(r"\{[\s\S]*\}", raw)
	if greedy:
		candidates.append(greedy.group(0))
	if stripped.startswith("```"):
		unfenced = stripped.split("\n", 1)[-1]
		if unfenced.rstrip().endswith("```"):
			unfenced = unfenced.rstrip()[: unfenced.rstrip().rfind("```")]
		candidates.append(unfenced.strip())
	start = raw.find("{")
	if start != -1:
		depth = 0
		for i in range(start, len(raw)):
			if raw[i] == "{":
				depth += 1
			elif raw[i] == "}":
				depth -= 1
				if depth == 0:
					candidates.append(raw[start : i + 1])
					break
	for candidate in candidates:
		try:
			parsed = json.loads(candidate)
		except json.JSONDecodeError:
			continue
		if isinstance(parsed, dict):
			return parsed
	return None


def overwrite_warning(xml: str) -> str:
	"""The warning listing the configured shapes an overwrite would discard, or "" when none are."""
	configured = extract_configured_elements(xml)
	if not configured:
		return ""
	return summarize_configured_elements(configured)


def transfer_properties(old_xml: str, new_xml: str) -> tuple:
	"""Copy configuration from old_xml onto the same ids in new_xml; return (merged_xml, removed)."""
	if not (old_xml or "").strip():
		return new_xml, []
	if not (new_xml or "").strip():
		return new_xml, []
	old_configured = extract_configured_elements(old_xml)
	if not old_configured:
		return new_xml, []
	_register_namespaces()
	new_root = ET.fromstring(new_xml)
	new_by_id = {elem.get("id"): elem for elem in new_root.iter() if elem.get("id")}
	removed = []
	for elem_id, old_data in old_configured.items():
		if elem_id in new_by_id:
			_copy_configuration(new_by_id[elem_id], old_data)
		else:
			removed.append(
				{
					"id": elem_id,
					"name": old_data["name"],
					"type": old_data["type"],
					"configs": _config_descriptions(old_data),
				}
			)
	merged_xml = ET.tostring(new_root, encoding="unicode", xml_declaration=True)
	merged_xml = re.sub(r"^<\?xml\s[^?]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', merged_xml)
	return merged_xml, removed


def format_removal_warning(removed_elements: list) -> str:
	"""The message asking the user to confirm a change that drops configured shapes."""
	lines = [
		_(
			"I've prepared the changes, but the following configured shapes will be removed and their settings will be lost:\n"
		)
	]
	for elem in removed_elements:
		line = _("• **{0}** ({1})").format(elem["name"], elem["type"])
		configs = elem["configs"]
		if configs:
			detail = list(configs[:3])
			if len(configs) > 3:
				detail.append(_("and {0} more").format(len(configs) - 3))
			line = line + " - " + ", ".join(detail)
		lines.append(line)
	lines.append(
		_(
			"\nThese configurations (scripts, assignments, triggers, documentation, etc.) cannot be recovered after applying the changes.\n\nShall I apply the changes anyway?"
		)
	)
	return "\n".join(lines)


def extract_configured_elements(xml: str) -> dict:
	"""Every BPMN element carrying extension attributes, extension elements or documentation, by id."""
	if not xml or not xml.strip():
		return {}
	_register_namespaces()
	root = ET.fromstring(xml)
	configured = {}
	for elem in root.iter():
		tag = elem.tag
		if any(ns in tag for ns in (NS["bpmndi"], NS["dc"], NS["di"])):
			continue
		elem_id = elem.get("id")
		if not elem_id:
			continue
		ext_attrs = {name: value for name, value in elem.attrib.items() if _is_extension_attr(name)}
		ext_elements_xml = None
		ext_el = elem.find("{" + NS["bpmn"] + "}extensionElements")
		if ext_el is not None and len(ext_el) > 0:
			ext_elements_xml = ET.tostring(ext_el, encoding="unicode")
		documentation = _get_documentation_text(elem)
		if ext_attrs or ext_elements_xml or documentation:
			configured[elem_id] = {
				"name": elem.get("name", elem_id),
				"type": _element_type_label(tag),
				"attrs": ext_attrs,
				"extension_elements_xml": ext_elements_xml,
				"documentation": documentation,
			}
	return configured


def summarize_configured_elements(configured: dict) -> str:
	"""The overwrite warning text for shapes that carry configuration."""
	lines = [
		_(
			"This will completely replace the existing diagram. The following shapes have configurations that will be lost:\n"
		)
	]
	for data in configured.values():
		config_labels = []
		for clark in data["attrs"]:
			label = _attr_label(clark)
			if label not in config_labels:
				config_labels.append(label)
		if data.get("extension_elements_xml"):
			config_labels.append(_("Extension Elements"))
		if data.get("documentation"):
			config_labels.append(_("Documentation"))
		line = _("• **{0}** ({1})").format(data["name"], data["type"])
		if config_labels:
			line = line + " - " + ", ".join(config_labels[:4])
			if len(config_labels) > 4:
				line = line + " " + _("and {0} more").format(len(config_labels) - 4)
		lines.append(line)
	lines.append(_("\nAll of these configurations will be lost. Are you sure you want to proceed?"))
	return "\n".join(lines)


def _copy_configuration(new_elem, old_data: dict) -> None:
	for clark, value in old_data["attrs"].items():
		new_elem.set(clark, value)
	if old_data["extension_elements_xml"]:
		new_ext_el = new_elem.find("{" + NS["bpmn"] + "}extensionElements")
		if new_ext_el is None:
			new_ext_el = ET.SubElement(new_elem, "{" + NS["bpmn"] + "}extensionElements")
		for child in ET.fromstring(old_data["extension_elements_xml"]):
			new_ext_el.append(child)
	if old_data.get("documentation"):
		_set_documentation(new_elem, old_data["documentation"])


def _config_descriptions(old_data: dict) -> list:
	configs = [_attr_label(clark) + ": " + value for clark, value in old_data["attrs"].items()]
	if old_data["extension_elements_xml"]:
		configs.append(_("Extension Elements (pre/post scripts or other)"))
	if old_data.get("documentation"):
		preview = old_data["documentation"][:80]
		if len(old_data["documentation"]) > 80:
			preview = preview + "…"
		configs.append(_("Documentation: {0}").format(preview))
	return configs


def _register_namespaces() -> None:
	for prefix, uri in NS.items():
		ET.register_namespace(prefix, uri)


def _is_extension_attr(attr_name: str) -> bool:
	return any(attr_name.startswith(uri) for uri in EXTENSION_NS_URIS)


def _attr_label(clark_name: str) -> str:
	local = clark_name.split("}", 1)[1] if "}" in clark_name else clark_name
	return _(ATTR_FAMILY_LABELS.get(local, local))


def _element_type_label(tag: str) -> str:
	local = tag.split("}", 1)[-1] if "}" in tag else tag
	return re.sub(r"([a-z])([A-Z])", r"\1 \2", local).title()


def _get_documentation_text(elem):
	doc_el = elem.find("{" + NS["bpmn"] + "}documentation")
	if doc_el is not None and doc_el.text:
		return doc_el.text.strip()
	return None


def _set_documentation(elem, text: str) -> None:
	doc_tag = "{" + NS["bpmn"] + "}documentation"
	doc_el = elem.find(doc_tag)
	if doc_el is not None:
		if not (doc_el.text or "").strip():
			doc_el.text = text
	else:
		doc_el = ET.Element(doc_tag)
		doc_el.text = text
		elem.insert(0, doc_el)
