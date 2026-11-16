# Copyright (c) 2026, one-fm and contributors
"""Call Activities pointed at the active map of the process they call, and that map's XML collected for the parser."""

import frappe
from frappe import _

from processa.processa_engine.compiler.prepare import ensure_script_task_inline_scripts, sanitize_bpmn_xml


CALL_BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
CALL_SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"


def resolve_called_process_xml(bpmn_xml: str, model_name: str) -> tuple:
	"""(this diagram with each Call Activity pointed at the map it runs, the XML of every map it calls, transitively)."""
	import xml.etree.ElementTree as _ET

	_ET.register_namespace("bpmn", CALL_BPMN_NS)
	_ET.register_namespace("bpmndi", "http://www.omg.org/spec/BPMN/20100524/DI")
	_ET.register_namespace("dc", "http://www.omg.org/spec/DD/20100524/DC")
	_ET.register_namespace("di", "http://www.omg.org/spec/DD/20100524/DI")
	_ET.register_namespace("spiffworkflow", "http://spiffworkflow.org/bpmn/schema/1.0/core")

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8"))
	except Exception:
		return bpmn_xml, []  # a malformed diagram surfaces properly in parse_bpmn

	seen = {p.get("id") for p in root.iter(f"{{{CALL_BPMN_NS}}}process") if p.get("id")}
	queue: list = []
	resolved = (
		_ET.tostring(root, encoding="unicode")
		if _point_call_activities(root, model_name, queue)
		else bpmn_xml
	)

	collected: list = []
	while queue:
		target = queue.pop()
		if target.process_id in seen:
			continue
		seen.add(target.process_id)
		child_xml = ensure_script_task_inline_scripts(sanitize_bpmn_xml(target.bpmn_xml))
		try:
			child_root = _ET.fromstring(child_xml.strip().encode("utf-8"))
		except Exception:
			collected.append(child_xml)  # the called model's own compile is where that gets reported
			continue
		if _point_call_activities(child_root, target.name, queue):
			child_xml = _ET.tostring(child_root, encoding="unicode")
		collected.append(child_xml)

	return resolved, collected


def _point_call_activities(root, model_name: str, queue: list) -> bool:
	"""Point each Call Activity under *root* at the map it runs and queue that map; True when an id changed."""
	changed = False
	for call in root.iter(f"{{{CALL_BPMN_NS}}}callActivity"):
		process = (call.get(f"{{{CALL_SPIFF_NS}}}calledProcess") or "").strip()
		called = (call.get("calledElement") or "").strip()
		if not (process or called):
			continue  # an unconfigured shape fails validation elsewhere with a better message
		target = called_model(process, called)
		if not target or not target.bpmn_xml:
			_throw_called_process_missing(model_name, call.get("id") or "?", process, called)
		if called != target.process_id:
			call.set("calledElement", target.process_id)
			changed = True
		queue.append(target)
	return changed


def called_model(process: str, called: str):
	"""The active map of the called Process; a Call Activity naming only an old process id runs its Process's active map."""
	fields = ["name", "process_id", "bpmn_xml"]
	if process:
		return frappe.db.get_value(
			"BPMN Process Model", {"process_name": process, "is_active": 1}, fields, as_dict=True
		)
	owner = frappe.db.get_value(
		"BPMN Process Model", {"process_id": called}, "process_name", order_by="is_active desc"
	)
	active = owner and frappe.db.get_value(
		"BPMN Process Model", {"process_name": owner, "is_active": 1}, fields, as_dict=True
	)
	return active or frappe.db.get_value("BPMN Process Model", {"process_id": called}, fields, as_dict=True)


def _throw_called_process_missing(model_name: str, shape_id: str, process: str, called: str) -> None:
	if process:
		message = _(
			"Cannot deploy '{0}': the Call Activity '{1}' calls the process '{2}', which has no active "
			"map. Activate a map of '{2}', or pick another process on the Call Activity."
		).format(model_name, shape_id, process)
	else:
		message = _(
			"Cannot deploy '{0}': the Call Activity '{1}' calls the process '{2}', and no BPMN Process "
			"Model has that Process ID. Open the Call Activity and pick the process it should run."
		).format(model_name, shape_id, called)
	frappe.throw(message, title=_("Called Process Not Found"))
