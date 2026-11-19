# Copyright (c) 2026, one-fm and contributors
"""Deploy check: an Apply Workflow task must not set a document status Frappe refuses after the previous one."""

import xml.etree.ElementTree as ET

import frappe
from frappe import _

BPMN_NS = "{http://www.omg.org/spec/BPMN/20100524/MODEL}"
SPIFF_NS = "{http://spiffworkflow.org/bpmn/schema/1.0/core}"
STATUS_LABELS = {"0": "Draft", "1": "Submitted", "2": "Cancelled"}
# Frappe allows 0 to 0, 0 to 1, 1 to 1 and 1 to 2; a cancelled document cannot change.
FORBIDDEN = {("0", "2"), ("1", "0"), ("2", "0"), ("2", "1"), ("2", "2")}
SUBPROCESS_TAGS = {f"{BPMN_NS}subProcess", f"{BPMN_NS}transaction", f"{BPMN_NS}adHocSubProcess"}


def validate_doc_status_transitions(bpmn_xml: str) -> None:
	"""Refuse a map where one Apply Workflow task follows another on the same doctype with a forbidden status change."""
	errors = doc_status_transition_errors(bpmn_xml)
	if errors:
		frappe.throw("\n".join(f"- {error}" for error in errors), title=_("Forbidden Document Status Change"))


def doc_status_transition_errors(bpmn_xml: str) -> list:
	"""One message for each forbidden document status change the map can reach."""
	root = ET.fromstring(bpmn_xml.strip().encode("utf-8"))
	successors = _successor_map(root)
	errors = []
	for node in root.iter(f"{BPMN_NS}serviceTask"):
		if not _is_apply_workflow(node):
			continue
		before = _spiff(node, "docStatus")
		for after_node in _next_apply_workflows(node, successors):
			after = _spiff(after_node, "docStatus")
			if (before, after) in FORBIDDEN:
				errors.append(
					_(
						'"{0}" sets the document to {1} right after "{2}" set it to {3}. Frappe does not allow {3} to {1}.'
					).format(_label(after_node), _status(after), _label(node), _status(before))
				)
	return errors


def _successor_map(root) -> dict:
	"""Which shapes can run right after each shape: flows, boundary events, and entering or leaving a subprocess."""
	by_id = {el.get("id"): el for el in root.iter() if el.get("id")}
	parent = {child: el for el in root.iter() for child in el}
	flows_out, boundaries = {}, {}
	for flow in root.iter(f"{BPMN_NS}sequenceFlow"):
		flows_out.setdefault(flow.get("sourceRef"), []).append(by_id.get(flow.get("targetRef")))
	for event in root.iter(f"{BPMN_NS}boundaryEvent"):
		boundaries.setdefault(event.get("attachedToRef"), []).append(event)

	successors = {}
	for node_id, node in by_id.items():
		starts = [child for child in node if child.tag == f"{BPMN_NS}startEvent"]
		nexts = starts if node.tag in SUBPROCESS_TAGS and starts else list(flows_out.get(node_id, []))
		nexts += boundaries.get(node_id, [])
		container = parent.get(node)
		if container is not None and container.tag in SUBPROCESS_TAGS:
			nexts += boundaries.get(container.get("id"), [])
			if node.tag == f"{BPMN_NS}endEvent":
				nexts += flows_out.get(container.get("id"), [])
		successors[node] = [n for n in nexts if n is not None]
	return successors


def _next_apply_workflows(node, successors: dict) -> list:
	"""The Apply Workflow tasks on the same doctype reachable from node without passing another one."""
	doctype = _spiff(node, "serviceTargetDoctype")
	found, seen, queue = [], {node}, list(successors.get(node, []))
	while queue:
		current = queue.pop(0)
		if current in seen:
			continue
		seen.add(current)
		if _is_apply_workflow(current) and _spiff(current, "serviceTargetDoctype") == doctype:
			found.append(current)
			continue
		queue.extend(successors.get(current, []))
	return found


def _is_apply_workflow(node) -> bool:
	return node.tag == f"{BPMN_NS}serviceTask" and _spiff(node, "serviceType") == "apply_workflow"


def _spiff(node, name: str) -> str:
	return (node.get(f"{SPIFF_NS}{name}") or "").strip()


def _label(node) -> str:
	return node.get("name") or node.get("id")


def _status(status: str) -> str:
	return f"{STATUS_LABELS[status]} ({status})"
