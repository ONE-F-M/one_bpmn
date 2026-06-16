"""
XML Property Preserver

Transfers extension attributes, documentation elements, and other user-configured
properties from an existing (old) BPMN XML document to a newly generated BPMN XML
document by matching element IDs.

This preserves user-configured shape properties (scripts, assignments, triggers,
service task configs, text styling, documentation) that the IR-to-XML pipeline
does not carry.

The module also reports which configured elements were removed so ProsAlly can
warn the user before applying destructive changes.
"""

import re
from xml.etree import ElementTree as ET


# ── Namespace configuration ───────────────────────────────────────────────────

NS = {
	"bpmn":         "http://www.omg.org/spec/BPMN/20100524/MODEL",
	"bpmndi":       "http://www.omg.org/spec/BPMN/20100524/DI",
	"dc":           "http://www.omg.org/spec/DD/20100524/DC",
	"di":           "http://www.omg.org/spec/DD/20100524/DI",
	"spiffworkflow": "http://spiffworkflow.org/bpmn/schema/1.0/core",
	"custom":       "http://custom/text-style",
	"camunda":      "http://camunda.org/schema/1.0/bpmn",
}

# Full namespace URIs for attribute matching in parsed XML (Clark notation)
_EXTENSION_NS_URIS = (
	"{http://spiffworkflow.org/bpmn/schema/1.0/core}",
	"{http://custom/text-style}",
	"{http://camunda.org/schema/1.0/bpmn}",
)

# Human-readable labels for extension attribute families
_ATTR_FAMILY_LABELS = {
	# SpiffWorkflow attributes
	"serverScript":         "Server Script",
	"assignmentMode":       "Assignment Mode",
	"assigneeDocField":     "Assignee (Doc Field)",
	"roundRobinRole":       "Round Robin Role",
	"loadBalancingRole":    "Load Balancing Role",
	"leaveRelieverEnabled": "Leave Reliever",
	"triggerType":          "Trigger Type",
	"triggerDoctype":       "Trigger DocType",
	"serviceType":          "Service Type",
	"serviceTargetDoctype": "Target DocType",
	"workflowState":       "Workflow State",
	"docStatus":            "Doc Status",
	"emailSubject":         "Email Subject",
	"emailTo":              "Email To",
	"emailBody":            "Email Body",
	"emailAccount":         "Email Account",
	"gchatMessage":         "Google Chat Message",
	"gchatSpaceId":         "Google Chat Space",
	"pushTitle":            "Push Notification Title",
	"pushMessage":          "Push Notification Message",
	"updateFieldDoctype":   "Update Field DocType",
	"updateFieldName":      "Update Field Name",
	"updateFieldValue":     "Update Field Value",
	"calledDecisionId":     "Decision Table",
	"notificationName":     "Notification",
	# Custom text-style attributes
	"fontFamily":           "Font Family",
	"fontSize":             "Font Size",
	"fontWeight":           "Font Weight",
	"fontStyle":            "Font Style",
	"textColor":            "Text Color",
	"textDecoration":       "Text Decoration",
	# Camunda attributes
	"assignee":             "Assignee",
	"candidateGroups":      "Candidate Groups",
	"candidateUsers":       "Candidate Users",
	"formKey":              "Form Key",
	"dueDate":              "Due Date",
	"followUpDate":         "Follow-Up Date",
	"priority":             "Priority",
	"asyncBefore":          "Async Before",
	"asyncAfter":           "Async After",
}


# ── Core functions ────────────────────────────────────────────────────────────

def _register_namespaces():
	"""Register known namespaces so ET preserves prefixes during serialisation."""
	for prefix, uri in NS.items():
		ET.register_namespace(prefix, uri)


def _is_extension_attr(attr_name: str) -> bool:
	"""Check if an attribute key (in Clark notation) belongs to an extension NS."""
	return any(attr_name.startswith(uri) for uri in _EXTENSION_NS_URIS)


def _short_attr_name(attr_name: str) -> str:
	"""Convert '{http://...}localName' to 'localName'."""
	if "}" in attr_name:
		return attr_name.split("}", 1)[1]
	return attr_name


def _attr_label(clark_name: str) -> str:
	"""Get a human-readable label for an extension attribute in Clark notation."""
	local = _short_attr_name(clark_name)
	return _ATTR_FAMILY_LABELS.get(local, local)


def _element_type_label(tag: str) -> str:
	"""Convert a BPMN tag to a human-readable type label."""
	local = tag.split("}", 1)[-1] if "}" in tag else tag
	# camelCase → Title Case
	label = re.sub(r"([a-z])([A-Z])", r"\1 \2", local)
	return label.title()


def _get_documentation_text(elem: ET.Element) -> str | None:
	"""Extract the text content of a <bpmn:documentation> child, if present."""
	doc_el = elem.find(f"{{{NS['bpmn']}}}documentation")
	if doc_el is not None and doc_el.text:
		return doc_el.text.strip()
	return None


def _set_documentation(elem: ET.Element, text: str):
	"""Set or create a <bpmn:documentation> child on the given element.

	Inserts the documentation element as the first child to match standard
	BPMN XML ordering conventions.
	"""
	doc_tag = f"{{{NS['bpmn']}}}documentation"
	doc_el = elem.find(doc_tag)
	if doc_el is not None:
		# Already exists — only overwrite if currently empty
		if not (doc_el.text or "").strip():
			doc_el.text = text
	else:
		doc_el = ET.Element(doc_tag)
		doc_el.text = text
		elem.insert(0, doc_el)


def extract_configured_elements(xml: str) -> dict:
	"""
	Parse BPMN XML and return a dict of elements that have extension attributes,
	documentation, or other preservable configurations.

	Returns:
		{element_id: {
			"name": str,
			"type": str,
			"attrs": {attr_clark_name: value, ...},
			"extension_elements_xml": str or None,
			"documentation": str or None,
		}}
	"""
	if not xml or not xml.strip():
		return {}

	_register_namespaces()

	try:
		root = ET.fromstring(xml)
	except ET.ParseError:
		return {}

	configured = {}

	# Walk all elements in BPMN process(es) — skip DI elements
	for elem in root.iter():
		tag = elem.tag
		# Skip DI/DC/DI elements
		if any(ns in tag for ns in (NS["bpmndi"], NS["dc"], NS["di"])):
			continue

		elem_id = elem.get("id")
		if not elem_id:
			continue

		# Collect extension attributes (keyed by full Clark notation to preserve namespace)
		ext_attrs = {}
		for attr_name, attr_value in elem.attrib.items():
			if _is_extension_attr(attr_name):
				ext_attrs[attr_name] = attr_value

		# Collect extensionElements child
		ext_elements_xml = None
		ext_el = elem.find(f"{{{NS['bpmn']}}}extensionElements")
		if ext_el is not None and len(ext_el) > 0:
			ext_elements_xml = ET.tostring(ext_el, encoding="unicode")

		# Collect documentation
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


def transfer_properties(old_xml: str, new_xml: str) -> tuple:
	"""
	Transfer extension attributes, extensionElements, and documentation
	from old_xml to new_xml.

	Matches elements by ID. Only transfers to elements that exist in both.

	Returns:
		(merged_xml: str, removed_elements: list[dict])

	Each removed element dict:
		{"id": str, "name": str, "type": str, "configs": list[str]}
	"""
	if not old_xml or not old_xml.strip() or not new_xml or not new_xml.strip():
		return new_xml, []

	old_configured = extract_configured_elements(old_xml)
	if not old_configured:
		return new_xml, []

	_register_namespaces()

	try:
		new_root = ET.fromstring(new_xml)
	except ET.ParseError:
		return new_xml, []

	# Build a map of all elements in new XML by ID
	new_elements_by_id = {}
	for elem in new_root.iter():
		elem_id = elem.get("id")
		if elem_id:
			new_elements_by_id[elem_id] = elem

	removed_elements = []

	for elem_id, old_data in old_configured.items():
		if elem_id in new_elements_by_id:
			# Element survived — transfer its properties
			new_elem = new_elements_by_id[elem_id]

			# 1. Transfer extension attributes (keys are already in Clark notation)
			for clark_name, value in old_data["attrs"].items():
				new_elem.set(clark_name, value)

			# 2. Transfer extensionElements children
			if old_data["extension_elements_xml"]:
				try:
					old_ext_el = ET.fromstring(old_data["extension_elements_xml"])
					# Find or create extensionElements in new element
					new_ext_el = new_elem.find(f"{{{NS['bpmn']}}}extensionElements")
					if new_ext_el is None:
						new_ext_el = ET.SubElement(
							new_elem, f"{{{NS['bpmn']}}}extensionElements"
						)
					# Add children from old
					for child in old_ext_el:
						new_ext_el.append(child)
				except ET.ParseError:
					pass

			# 3. Transfer documentation
			if old_data.get("documentation"):
				_set_documentation(new_elem, old_data["documentation"])
		else:
			# Element was removed — collect info about what was configured
			configs = []
			for clark_name, value in old_data["attrs"].items():
				label = _attr_label(clark_name)
				configs.append(f"{label}: {value}")

			if old_data["extension_elements_xml"]:
				configs.append("Extension Elements (pre/post scripts or other)")

			if old_data.get("documentation"):
				# Truncate long documentation for the warning message
				doc_preview = old_data["documentation"][:80]
				if len(old_data["documentation"]) > 80:
					doc_preview += "…"
				configs.append(f"Documentation: {doc_preview}")

			removed_elements.append({
				"id": elem_id,
				"name": old_data["name"],
				"type": old_data["type"],
				"configs": configs,
			})

	# Serialise merged XML
	merged_xml = ET.tostring(new_root, encoding="unicode", xml_declaration=True)

	# Ensure the XML declaration uses the standard BPMN format
	# ET may produce <?xml version='1.0' encoding='us-ascii'?> — normalise
	merged_xml = re.sub(
		r"<\?xml[^?]*\?>",
		'<?xml version="1.0" encoding="UTF-8"?>',
		merged_xml,
	)

	return merged_xml, removed_elements


def format_removal_warning(removed_elements: list) -> str:
	"""
	Format a human-readable warning about elements that will be removed
	along with their configurations.

	Returns an empty string if there are no removed elements with configs.
	"""
	if not removed_elements:
		return ""

	lines = [
		"I've prepared the changes, but the following configured shapes "
		"will be removed and their settings will be lost:\n"
	]

	for elem in removed_elements:
		name = elem.get("name", elem.get("id", "Unknown"))
		elem_type = elem.get("type", "Element")
		configs = elem.get("configs", [])

		line = f"• **{name}** ({elem_type})"
		if configs:
			# Show up to 3 config details
			detail_items = configs[:3]
			if len(configs) > 3:
				detail_items.append(f"and {len(configs) - 3} more")
			line += " — " + ", ".join(detail_items)

		lines.append(line)

	lines.append(
		"\nThese configurations (scripts, assignments, triggers, documentation, etc.) "
		"cannot be recovered after applying the changes."
		"\n\nShall I apply the changes anyway?"
	)

	return "\n".join(lines)


def summarize_configured_elements(configured: dict) -> str:
	"""
	Format a human-readable summary of all configured elements in a diagram.
	Used when warning about OVERWRITE_EXISTING which replaces everything.

	Returns an empty string if there are no configured elements.
	"""
	if not configured:
		return ""

	lines = [
		"This will completely replace the existing diagram. "
		"The following shapes have configurations that will be lost:\n"
	]

	for elem_id, data in configured.items():
		name = data.get("name", elem_id)
		elem_type = data.get("type", "Element")
		attrs = data.get("attrs", {})

		config_labels = []
		for clark_name in attrs:
			label = _attr_label(clark_name)
			if label not in config_labels:
				config_labels.append(label)

		if data.get("extension_elements_xml"):
			config_labels.append("Extension Elements")

		if data.get("documentation"):
			config_labels.append("Documentation")

		line = f"• **{name}** ({elem_type})"
		if config_labels:
			line += " — " + ", ".join(config_labels[:4])
			if len(config_labels) > 4:
				line += f" and {len(config_labels) - 4} more"
		lines.append(line)

	lines.append(
		"\nAll of these configurations will be lost. "
		"Are you sure you want to proceed?"
	)

	return "\n".join(lines)
