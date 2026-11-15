# Copyright (c) 2026, one-fm and contributors
"""The start_events table of a process model synced from the start events in its diagram."""

import frappe


def populate_start_events(model, bpmn_xml: str) -> None:
	"""Rebuild the model's start_events table from the start events in the XML; the caller saves the model."""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	last_started = {row.bpmn_element_id: row.last_started_at for row in (model.start_events or [])}
	model.start_events = []

	if not bpmn_xml or not bpmn_xml.strip():
		return

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		frappe.log_error(
			title="BPMN: Failed to parse XML for start events",
			message=frappe.get_traceback(),
		)
		return

	for start_event in root.iter(f"{{{BPMN_NS}}}startEvent"):
		bpmn_id = start_event.get("id", "")

		event_type = "None"
		cron_expr = ""

		cond_def = start_event.find(f"{{{BPMN_NS}}}conditionalEventDefinition")
		timer_def = start_event.find(f"{{{BPMN_NS}}}timerEventDefinition")
		signal_def = start_event.find(f"{{{BPMN_NS}}}signalEventDefinition")

		if cond_def is not None:
			event_type = "Conditional"
		elif timer_def is not None:
			event_type = "Timer"
			cron_expr = timer_def.get(f"{{{SPIFF_NS}}}cronExpression", "")
			if not cron_expr:
				cycle = timer_def.find(f"{{{BPMN_NS}}}timeCycle")
				if cycle is not None and cycle.text:
					cron_expr = cycle.text.strip()
		elif signal_def is not None:
			event_type = "Signal"

		workflow_state = start_event.get(f"{{{SPIFF_NS}}}triggerWorkflowState", "")
		trigger_doctype = start_event.get(f"{{{SPIFF_NS}}}triggerDoctype", "")
		trigger_type_attr = start_event.get(f"{{{SPIFF_NS}}}triggerType", "")

		if cond_def is not None and not workflow_state:
			workflow_state = cond_def.get(f"{{{SPIFF_NS}}}triggerWorkflowState", "")
		if cond_def is not None and not trigger_doctype:
			trigger_doctype = cond_def.get(f"{{{SPIFF_NS}}}triggerDoctype", "")
		if cond_def is not None and not trigger_type_attr:
			trigger_type_attr = cond_def.get(f"{{{SPIFF_NS}}}triggerType", "")

		trigger_event = trigger_type_attr or model.trigger_event or ""

		trigger_type = "API"
		if trigger_doctype:
			trigger_type = "DocType Event"
		elif cron_expr:
			trigger_type = "Scheduler Event"

		model.append(
			"start_events",
			{
				"event_type": event_type,
				"bpmn_element_id": bpmn_id,
				"trigger_type": trigger_type,
				"trigger_doctype": trigger_doctype,
				"trigger_event": trigger_event,
				"workflow_state_condition": workflow_state,
				"cron_expression": cron_expr,
				"last_started_at": last_started.get(bpmn_id),
			},
		)
