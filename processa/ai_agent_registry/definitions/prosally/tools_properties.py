"""ProsAlly keeps and describes the configuration on diagram elements across a redraw."""

import json
import re
from xml.etree import ElementTree as ET

from frappe import _

from processa.ai_agent_registry.definitions.prosally.helpers import NS, register_namespaces

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


def overwrite_warning(xml: str) -> str:
	"""The warning listing the configured shapes an overwrite would discard, or "" when none are."""
	configured = extract_configured_elements(xml)
	if not configured:
		return ""
	return summarize_configured_elements(configured)


def transfer_properties(old_xml: str, new_xml: str, skip_ids: tuple = ()) -> tuple:
	"""Copy configuration from old_xml onto the same ids in new_xml, except skip_ids; return (merged_xml, removed)."""
	if not (old_xml or "").strip():
		return new_xml, []
	if not (new_xml or "").strip():
		return new_xml, []
	old_configured = {k: v for k, v in extract_configured_elements(old_xml).items() if k not in skip_ids}
	if not old_configured:
		return new_xml, []
	register_namespaces()
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
	register_namespaces()
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
