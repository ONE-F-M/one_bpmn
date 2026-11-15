# Copyright (c) 2026, one-fm and contributors
"""XML clean-up applied to a diagram before SpiffWorkflow parses it, and the DMN decisions it calls."""

import re


def sanitize_bpmn_xml(bpmn_xml: str) -> str:
	"""Strip references to deleted elements and base64 the raw HTML attributes; on any error return the input."""
	try:
		from lxml import etree

		BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
		BPMNDI = "http://www.omg.org/spec/BPMN/20100524/DI"

		parser = etree.XMLParser(resolve_entities=False, no_network=True)
		root = etree.fromstring(bpmn_xml.strip().encode("utf-8"), parser=parser)

		defined_ids = set()
		for process in root.iter(f"{{{BPMN}}}process"):
			for child in process:
				eid = child.get("id")
				if eid:
					defined_ids.add(eid)

		for lane in root.iter(f"{{{BPMN}}}lane"):
			to_remove = [
				fnr
				for fnr in lane.findall(f"{{{BPMN}}}flowNodeRef")
				if (fnr.text or "").strip() not in defined_ids
			]
			for fnr in to_remove:
				lane.remove(fnr)

		for process in root.iter(f"{{{BPMN}}}process"):
			to_remove = [
				sf
				for sf in process.findall(f"{{{BPMN}}}sequenceFlow")
				if sf.get("sourceRef", "") not in defined_ids or sf.get("targetRef", "") not in defined_ids
			]
			for sf in to_remove:
				process.remove(sf)

		for collab in root.iter(f"{{{BPMN}}}collaboration"):
			to_remove = [
				a
				for a in collab.findall(f"{{{BPMN}}}association")
				if a.get("sourceRef", "") not in defined_ids and a.get("targetRef", "") not in defined_ids
			]
			for a in to_remove:
				collab.remove(a)

		for plane in root.iter(f"{{{BPMNDI}}}BPMNPlane"):
			lane_participant_ids = {
				el.get("id")
				for el in root.iter()
				if el.get("id")
				and el.tag.split("}")[-1] in ("lane", "participant", "laneSet", "collaboration")
			}
			to_remove = [
				shape
				for shape in plane.findall(f"{{{BPMNDI}}}BPMNShape")
				if shape.get("bpmnElement", "") not in defined_ids
				and shape.get("bpmnElement", "") not in lane_participant_ids
			]
			for shape in to_remove:
				plane.remove(shape)

		import base64 as _b64

		SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"
		_HTML_ATTRS = (
			f"{{{SPIFF_NS}}}notifyAssigneeBody",
			f"{{{SPIFF_NS}}}emailBody",
		)
		for attr_key in _HTML_ATTRS:
			for elem in root.iter():
				raw = elem.get(attr_key)
				if not raw:
					continue
				# A value that decodes is already base64.
				try:
					_b64.b64decode(raw).decode("utf-8")
					continue
				except Exception:
					pass
				encoded = _b64.b64encode(raw.encode("utf-8")).decode("ascii")
				elem.set(attr_key, encoded)

		return etree.tostring(root, encoding="unicode", xml_declaration=False)

	except Exception:
		return bpmn_xml


def ensure_script_task_inline_scripts(bpmn_xml: str) -> str:
	"""Give every Script Task with no script a pass stub, which SpiffWorkflow needs to parse it."""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	try:
		_ET.register_namespace("bpmn", BPMN_NS)
		_ET.register_namespace("bpmndi", "http://www.omg.org/spec/BPMN/20100524/DI")
		_ET.register_namespace("dc", "http://www.omg.org/spec/DD/20100524/DC")
		_ET.register_namespace("di", "http://www.omg.org/spec/DD/20100524/DI")
		_ET.register_namespace("spiffworkflow", "http://spiffworkflow.org/bpmn/schema/1.0/core")

		encoded = bpmn_xml.strip().encode("utf-8")
		root = _ET.fromstring(encoded)

		injected = 0
		for script_task in root.iter(f"{{{BPMN_NS}}}scriptTask"):
			existing = script_task.findall(f"{{{BPMN_NS}}}script")
			if not existing:
				script_elem = _ET.Element(f"{{{BPMN_NS}}}script")
				script_elem.text = "pass  # executed by FrappeScriptEngine (Server Script)"
				script_task.insert(0, script_elem)
				injected += 1

		if injected == 0:
			return bpmn_xml

		xml_bytes = _ET.tostring(root, encoding="unicode", xml_declaration=False)
		if bpmn_xml.strip().startswith("<?xml"):
			decl_end = bpmn_xml.index("?>") + 2
			return bpmn_xml[:decl_end] + "\n" + xml_bytes
		return xml_bytes

	except Exception:
		return bpmn_xml


def drop_stale_flow_node_refs(xml: str) -> str:
	"""Remove <flowNodeRef> entries whose node id is not defined anywhere in the XML."""
	if not xml or "flowNodeRef" not in xml:
		return xml
	defined = set(re.findall(r'\bid="([^"]+)"', xml))
	pattern = re.compile(r"\s*<(?:bpmn2?:)?flowNodeRef>\s*([^<\s]+)\s*</(?:bpmn2?:)?flowNodeRef>")
	return pattern.sub(lambda m: m.group(0) if m.group(1) in defined else "", xml)


def extract_business_rule_task_decisions(bpmn_xml: str) -> list:
	"""The calledDecisionId of every Business Rule Task in the XML."""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	if not bpmn_xml or not bpmn_xml.strip():
		return []

	try:
		root = _ET.fromstring(
			bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml
		)
	except Exception:
		return []

	decision_ids = []
	for brt in root.iter(f"{{{BPMN_NS}}}businessRuleTask"):
		ext_els = brt.find(f"{{{BPMN_NS}}}extensionElements")
		if ext_els is None:
			continue
		called = ext_els.find(f"{{{SPIFF_NS}}}calledDecisionId")
		if called is not None and called.text and called.text.strip():
			decision_ids.append(called.text.strip())

	return decision_ids


def extract_dmn_decision_id(dmn_xml: str) -> str:
	"""The id of the decision in a DMN document, or an empty string."""
	import xml.etree.ElementTree as _ET

	if not dmn_xml or not dmn_xml.strip():
		return ""

	try:
		root = _ET.fromstring(
			dmn_xml.strip().encode("utf-8") if isinstance(dmn_xml, str) else dmn_xml
		)
	except Exception:
		return ""

	for child in root:
		tag_local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
		if tag_local == "decision":
			return child.get("id", "")

	return ""
