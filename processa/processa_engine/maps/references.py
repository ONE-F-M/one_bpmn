# Copyright (c) 2026, one-fm and contributors
"""Read the DocTypes, fields, states, scripts, roles and Call Activities a BPMN map refers to."""

import json

import frappe
from frappe import _


def extract_bpmn_references(xml_content: str) -> dict:
	"""Parse BPMN XML and extract all external references."""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	try:
		root = _ET.fromstring(xml_content.strip().encode("utf-8"))
	except Exception as exc:
		frappe.throw(_("Invalid BPMN XML: {0}").format(str(exc)))

	referenced_doctypes = set()
	referenced_fields = []
	referenced_states = set()
	referenced_actions = set()
	apply_workflow_doctypes = set()
	referenced_scripts = set()
	referenced_lane_roles = set()
	# The DocTypes a start event binds an instance to.
	context_doctypes = set()

	for start_event in root.iter(f"{{{BPMN_NS}}}startEvent"):
		dt = start_event.get(f"{{{SPIFF_NS}}}triggerDoctype", "")
		if dt:
			referenced_doctypes.add(dt)
			context_doctypes.add(dt)

		ws = start_event.get(f"{{{SPIFF_NS}}}triggerWorkflowState", "")
		if ws:
			referenced_states.add(ws)

		cond_def = start_event.find(f"{{{BPMN_NS}}}conditionalEventDefinition")
		if cond_def is not None:
			dt2 = cond_def.get(f"{{{SPIFF_NS}}}triggerDoctype", "")
			if dt2:
				referenced_doctypes.add(dt2)
				context_doctypes.add(dt2)
			ws2 = cond_def.get(f"{{{SPIFF_NS}}}triggerWorkflowState", "")
			if ws2:
				referenced_states.add(ws2)

	for service_task in root.iter(f"{{{BPMN_NS}}}serviceTask"):
		attrs = {}
		for attr_name, attr_value in service_task.attrib.items():
			if attr_name.startswith(f"{{{SPIFF_NS}}}"):
				key = attr_name[len(f"{{{SPIFF_NS}}}"):]
				attrs[key] = attr_value

		service_type = attrs.get("serviceType", "")

		if service_type == "apply_workflow":
			target_dt = attrs.get("serviceTargetDoctype", "")
			if target_dt:
				referenced_doctypes.add(target_dt)
				apply_workflow_doctypes.add(target_dt)

			state = attrs.get("workflowState", "")
			if state:
				referenced_states.add(state)

		elif service_type == "update_field":
			target_dt = attrs.get("updateFieldDoctype", "")
			if target_dt:
				referenced_doctypes.add(target_dt)

			rows_json = attrs.get("updateFieldRows", "")
			if rows_json:
				try:
					rows = json.loads(rows_json)
					for row in rows:
						field = row.get("field", "")
						if field and target_dt:
							referenced_fields.append((target_dt, field))
				except (json.JSONDecodeError, ValueError):
					pass

			legacy_field = attrs.get("updateFieldName", "")
			if legacy_field and target_dt:
				referenced_fields.append((target_dt, legacy_field))

		else:
			target_dt = attrs.get("serviceTargetDoctype", "")
			if target_dt:
				referenced_doctypes.add(target_dt)

	for user_task in root.iter(f"{{{BPMN_NS}}}userTask"):
		attrs = {}
		for attr_name, attr_value in user_task.attrib.items():
			if attr_name.startswith(f"{{{SPIFF_NS}}}"):
				key = attr_name[len(f"{{{SPIFF_NS}}}"):]
				attrs[key] = attr_value

		target_dt = attrs.get("targetDoctype", "")
		if target_dt:
			referenced_doctypes.add(target_dt)

		assignee_field = attrs.get("assigneeDocfield", "")
		if assignee_field and target_dt:
			referenced_fields.append((target_dt, assignee_field))

		actions_json = attrs.get("taskActions", "")
		if actions_json:
			try:
				actions = json.loads(actions_json)
				for action in actions:
					label = action.get("action", "")
					if label:
						referenced_actions.add(label)
			except (json.JSONDecodeError, ValueError):
				pass

		notify_dt = min(context_doctypes, default="") or target_dt
		if notify_dt:
			for fieldname in _notify_fieldnames(attrs, user_task.get("id", "")):
				referenced_fields.append((notify_dt, fieldname))

	for script_task in root.iter(f"{{{BPMN_NS}}}scriptTask"):
		script_name = script_task.get(f"{{{SPIFF_NS}}}serverScript", "")
		if script_name:
			referenced_scripts.add(script_name)

	for lane in root.iter(f"{{{BPMN_NS}}}lane"):
		role_name = lane.get("name", "").strip()
		if role_name:
			referenced_lane_roles.add(role_name)

	for service_task in root.iter(f"{{{BPMN_NS}}}serviceTask"):
		attrs = {}
		for attr_name, attr_value in service_task.attrib.items():
			if attr_name.startswith(f"{{{SPIFF_NS}}}"):
				key = attr_name[len(f"{{{SPIFF_NS}}}"):]
				attrs[key] = attr_value

		if attrs.get("serviceType") == "send_email":
			email_dt = attrs.get("emailDoctype", "")
			if email_dt:
				to_fields = attrs.get("emailToDocFields", "")
				for field in to_fields.split(","):
					field = field.strip()
					if field:
						referenced_fields.append((email_dt, field))

				table_field = attrs.get("emailToTableField", "").strip()
				if table_field:
					referenced_fields.append((email_dt, table_field))

				cc_fields = attrs.get("emailCcDocFields", "")
				for field in cc_fields.split(","):
					field = field.strip()
					if field:
						referenced_fields.append((email_dt, field))

				for key in ("emailFacts", "emailDetails"):
					for entry in _notify_json(attrs, key, service_task.get("id", "")) or []:
						for name in entry if isinstance(entry, list) else [entry]:
							# A linked field such as employee.employee_name needs its link field on this DocType.
							referenced_fields.append((email_dt, name.split(".")[0]))

	for dt in apply_workflow_doctypes:
		referenced_fields.append((dt, "workflow_state"))

	call_activities = extract_call_activity_refs(xml_content)

	_process_el = root.find(f"{{{BPMN_NS}}}process") or root.find("process")

	return {
		"doctypes": referenced_doctypes,
		"fields": referenced_fields,
		"workflow_states": referenced_states,
		"workflow_actions": referenced_actions,
		"server_scripts": referenced_scripts,
		"lane_roles": referenced_lane_roles,
		"apply_workflow_doctypes": apply_workflow_doctypes,
		"context_doctypes": context_doctypes,
		"call_activities": call_activities,
		"root": root,
		"process_el": _process_el,
	}


def _notify_fieldnames(attrs: dict, element_id: str) -> list[str]:
	"""Fields on the context DocType that a task's Notification Editor settings name."""
	names = []
	for key in ("notifyFacts", "notifyDetails"):
		for entry in _notify_json(attrs, key, element_id) or []:
			for name in entry if isinstance(entry, list) else [entry]:
				# A linked field such as employee.employee_name needs its link field on this DocType.
				names.append(name.split(".")[0])
	for action in (_notify_json(attrs, "notifyActions", element_id) or {}).values():
		if action.get("reasonField"):
			names.append(action["reasonField"])
	return names


def _notify_json(attrs: dict, key: str, element_id: str):
	raw = attrs.get(key, "")
	if not raw:
		return None
	try:
		return json.loads(raw)
	except ValueError as exc:
		raise frappe.ValidationError(
			_("Task {0} has an unreadable {1} setting: {2}").format(element_id, key, exc)
		) from exc


def extract_call_activity_refs(xml_content: str) -> list:
	"""Parse BPMN XML and extract all Call Activity references."""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	if not xml_content or not xml_content.strip():
		return []

	try:
		root = _ET.fromstring(
			xml_content.strip().encode("utf-8") if isinstance(xml_content, str) else xml_content
		)
	except Exception:
		return []

	refs = []
	for call_activity in root.iter(f"{{{BPMN_NS}}}callActivity"):
		bpmn_id = call_activity.get("id", "")
		called_element = call_activity.get("calledElement", "").strip()
		name = call_activity.get("name", "").strip()
		if bpmn_id and called_element:
			refs.append({
				"bpmn_id": bpmn_id,
				"called_element": called_element,
				"name": name or bpmn_id,
			})

	return refs

