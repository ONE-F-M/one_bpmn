# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Helpers the ProsAlly tool scripts share: property preservation, JSON extraction, confirmation replies, history, model calls."""

import json
import re
from collections import Counter
from xml.etree import ElementTree as ET

import frappe
from frappe import _

from one_bpmn.agents.bpmn_ir_pipeline import element_names
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.agents.memory.text_clean import strip_html
from one_bpmn.agents.turn_state import run_sync
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

AGENT_ID = "prosally_agent"
HISTORY_TURNS = 10
MIN_STAGE_TOKENS = 16384

# Whole replies that approve a pending confirmation, after punctuation and "please" or "thanks" are dropped.
AFFIRMATIONS = frozenset(
	{
		"yes",
		"y",
		"yeah",
		"yep",
		"yup",
		"sure",
		"ok",
		"okay",
		"alright",
		"all right",
		"go",
		"go ahead",
		"yes go ahead",
		"ok go ahead",
		"okay go ahead",
		"proceed",
		"yes proceed",
		"ok proceed",
		"do it",
		"yes do it",
		"do",
		"just do it",
		"go for it",
		"draw it",
		"yes draw it",
		"confirm",
		"confirmed",
		"yes confirm",
		"sounds good",
		"looks good",
		"yes sounds good",
		"yes looks good",
		"perfect",
		"correct",
		"yes correct",
		"thats right",
		"yes thats right",
		"absolutely",
		"of course",
	}
)
# Replies starting with one of these turn a pending confirmation down.
DECLINES = ("no", "nope", "nah", "wait", "change", "not yet", "hold on", "stop", "dont", "do not", "cancel")
_POLITE_WORDS = re.compile(r"\b(please|thanks|thank you)\b")

# "lanes" then optional "only/named/called/are" and a colon, then the list up to the end of the clause.
_LANE_LIST = re.compile(r"\blanes\b(?:\s+(?:only|named|called|are))*\s*:?\s*([^.;:\n]+)", re.I)
# Plain words for the element types a designer sees in a change list.
_ELEMENT_WORDS = {
	"startEvent": "the start",
	"endEvent": "the end",
	"exclusiveGateway": "the decision",
	"inclusiveGateway": "the decision",
	"eventBasedGateway": "the decision",
	"parallelGateway": "the parallel split",
	"sequenceFlow": "the path",
	"subProcess": "the sub-process",
	"intermediateCatchEvent": "the event",
	"intermediateThrowEvent": "the event",
	"boundaryEvent": "the event",
	"userTask": "the step",
	"serviceTask": "the step",
	"scriptTask": "the step",
	"manualTask": "the step",
	"sendTask": "the step",
	"receiveTask": "the step",
	"businessRuleTask": "the step",
	"callActivity": "the step",
	"task": "the step",
}

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


def answer_to_confirmation(conversation: str, user_text: str) -> dict:
	"""{"confirmed_action": ...} or {"declined_action": ...} when user_text answers the last Bot confirmation, else {}."""
	last = frappe.get_all(
		"Chat Message",
		filters={"conversation": conversation, "message_type": "Bot"},
		fields=["metadata"],
		order_by="creation desc",
		limit=1,
	)
	meta = frappe.parse_json(last[0].metadata or "{}") if last else {}
	action = (meta.get("agent_result") or {}).get("action_intent")
	if meta.get("intent") != "CONFIRM" or not action:
		return {}
	reply = confirmation_reply(user_text)
	if reply == "yes":
		return {"confirmed_action": action}
	if reply == "no":
		return {"declined_action": action}
	return {}


def confirmation_reply(text: str) -> str:
	""" "yes" when text is a plain affirmation, "no" when it starts with a decline, else ""."""
	words = re.sub(r"[^a-z ]", " ", strip_html(text).lower().replace("'", ""))
	words = " ".join(_POLITE_WORDS.sub(" ", words).split())
	if words in AFFIRMATIONS:
		return "yes"
	if any(words == d or words.startswith(d + " ") for d in DECLINES):
		return "no"
	return ""


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


def describe_task_config(xml: str, previous_xml: str = "") -> str:
	"""The settings on the diagram's shapes as plain sentences, leaving out any previous_xml already had; "" when none."""
	before = extract_configured_elements(previous_xml)
	lines = []
	for elem_id, data in extract_configured_elements(xml).items():
		config = {_local_name(clark): value for clark, value in data["attrs"].items()}
		previous = {_local_name(clark): value for clark, value in before.get(elem_id, {}).get("attrs", {}).items()}
		if elem_id in before and previous == config:
			continue
		kind = data["type"].replace(" ", "")
		if kind == "StartEvent" and config.get("triggerDoctype"):
			lines.append(_("The process starts when a new {0} is created.").format(config["triggerDoctype"]))
		elif kind == "ServiceTask":
			lines.append(_service_task_sentence(data["name"], config))
		elif kind == "UserTask":
			lines.append(_user_task_sentence(data["name"], config))
	lines = [line for line in lines if line]
	if not lines:
		return ""
	return "\n\n" + _("I also set these up on the steps:") + "\n" + "\n".join("- " + line for line in lines)


def _service_task_sentence(name: str, config: dict) -> str:
	service = config.get("serviceType")
	if service == "apply_workflow":
		return _("{0} moves the {1} to {2}.").format(
			name, config.get("serviceTargetDoctype") or _("document"), config.get("workflowState") or _("its next state")
		)
	if service == "send_email":
		return _("{0} sends an email.").format(name)
	if service == "update_field":
		return _("{0} updates a field on the {1}.").format(name, config.get("updateFieldDoctype") or _("document"))
	if service == "google_chat":
		return _("{0} sends a Google Chat message.").format(name)
	if service == "push_notification":
		return _("{0} sends a push notification.").format(name)
	if service == "connector":
		return _("{0} runs the {1} connector.").format(name, config.get("connectorId") or "")
	return ""


def _user_task_sentence(name: str, config: dict) -> str:
	parts = []
	if config.get("targetDoctype"):
		parts.append(_("works on the {0}").format(config["targetDoctype"]))
	mode = config.get("assigneeMode")
	if mode == "User" and config.get("assigneeUser"):
		parts.append(_("is assigned to {0}").format(config["assigneeUser"]))
	elif mode == "DocField" and config.get("assigneeDocfield"):
		parts.append(_("is assigned to the person in the {0} field").format(config["assigneeDocfield"]))
	elif mode == "Table Field" and config.get("assigneeTableField"):
		parts.append(_("is assigned to the people in the {0} table").format(config["assigneeTableField"]))
	elif mode == "Round Robin":
		parts.append(_("is assigned by round robin"))
	elif mode == "Load Balancing":
		parts.append(_("is assigned by load balancing"))
	elif mode:
		parts.append(_("has no one chosen to do it yet"))
	actions = config.get("taskActions") or []
	if isinstance(actions, str):
		actions = json.loads(actions)
	actions = [a.get("action") if isinstance(a, dict) else a for a in actions]
	actions = [str(a) for a in actions if a]
	if actions:
		parts.append(_("has the buttons {0}").format(", ".join(actions)))
	if not parts:
		return ""
	return _("{0} {1}.").format(name, ", ".join(parts))


def describe_changes(previous_xml: str, xml: str) -> str:
	"""What a modify added, removed and renamed on the diagram, as plain lines; says so when nothing changed."""
	before = element_names(previous_xml)
	after = element_names(xml)
	lines = []
	for elem_id, (kind, name) in after.items():
		if kind == "sequenceFlow":
			continue
		if elem_id not in before:
			lines.append(_("Added {0}.").format(_element_label(kind, name)))
			continue
		old_name = before[elem_id][1]
		if name and old_name and name != old_name:
			lines.append(_("Renamed {0} to {1}.").format(_element_label(kind, old_name), _quoted(name)))
	for elem_id, (kind, name) in before.items():
		if kind != "sequenceFlow" and elem_id not in after:
			lines.append(_("Removed {0}.").format(_element_label(kind, name)))
	# Paths are compared by label, since a modify may give an unchanged path a new id.
	old_paths = Counter(name for kind, name in before.values() if kind == "sequenceFlow" and name)
	new_paths = Counter(name for kind, name in after.values() if kind == "sequenceFlow" and name)
	for name in (new_paths - old_paths).elements():
		lines.append(_("Added {0}.").format(_element_label("sequenceFlow", name)))
	for name in (old_paths - new_paths).elements():
		lines.append(_("Removed {0}.").format(_element_label("sequenceFlow", name)))
	if not lines:
		return "\n\n" + _("I could not find any change on the diagram. Check that your request was applied.")
	return "\n\n" + _("What changed:") + "\n" + "\n".join("- " + line for line in lines)


def describe_lanes(chat_history: list, user_text: str, ir: dict | None) -> str:
	"""The lanes drawn, and any lane the person named that is not among them; "" when no lanes were drawn."""
	drawn = [lane.get("name") for lane in (ir or {}).get("lanes") or [] if lane.get("name")]
	if not drawn:
		return ""
	text = "\n\n" + _("Lanes drawn: {0}.").format(", ".join(drawn))
	asked = [e.get("content") or "" for e in chat_history if (e.get("role") or e.get("type")) == "user"]
	missing = [
		lane
		for lane in requested_lanes([*asked, user_text or ""])
		if not any(lane.lower() in d.lower() or d.lower() in lane.lower() for d in drawn)
	]
	if missing:
		text += " " + _("You also asked for {0}, which I did not draw. Ask me to add it.").format(
			", ".join(missing)
		)
	return text


def requested_lanes(texts: list) -> list[str]:
	"""The lane names listed after "lanes" in the latest of texts that lists two or more, else []."""
	for text in reversed(texts):
		for match in _LANE_LIST.finditer(strip_html(text)):
			names = [
				re.sub(r"^the\s+", "", n.strip(), flags=re.I) for n in re.split(r",|\band\b|&", match[1])
			]
			names = [n for n in names if n and n[0].isupper() and len(n.split()) <= 4]
			if len(names) >= 2:
				return names
	return []


def _element_label(kind: str, name: str) -> str:
	return _ELEMENT_WORDS.get(kind, "the element") + (" " + _quoted(name) if name else "")


def _quoted(name: str) -> str:
	return '"' + name + '"'


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


def _local_name(clark_name: str) -> str:
	return clark_name.split("}", 1)[1] if "}" in clark_name else clark_name


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
