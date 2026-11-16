# Copyright (c) 2026, one-fm and contributors
"""Deploy checks for timer events, and the start-timer rewrite of the copy handed to the parser."""

import frappe
from frappe import _


def validate_timer_granularity(bpmn_xml: str) -> None:
	"""Refuse a timer duration or cycle in seconds; the Frappe scheduler runs once a minute."""
	import re
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	if not bpmn_xml or not bpmn_xml.strip():
		return

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return  # XML errors are caught elsewhere

	errors = []

	for timer_def in root.iter(f"{{{BPMN_NS}}}timerEventDefinition"):
		parent = None
		for elem in root.iter():
			if timer_def in list(elem):
				parent = elem
				break
		parent_id = parent.get("id", "unknown") if parent is not None else "unknown"
		parent_name = parent.get("name", "") if parent is not None else ""
		label = parent_name or parent_id

		duration_el = timer_def.find(f"{{{BPMN_NS}}}timeDuration")
		if duration_el is not None and duration_el.text:
			val = duration_el.text.strip()
			if re.search(r"\d+S\s*$", val, re.IGNORECASE):
				if not re.search(r"[DHMY]\d*M", val, re.IGNORECASE) and not re.search(
					r"\d+M\d+S", val, re.IGNORECASE
				):
					errors.append(
						f'Timer "{label}": Duration "{val}" uses seconds. '
						f"Minimum supported duration is 1 minute (PT1M)."
					)
				else:
					errors.append(
						f'Timer "{label}": Duration "{val}" includes a seconds component. '
						f"Frappe scheduler runs at minute intervals - seconds will be ignored. "
						f"Use whole minutes instead."
					)

		cycle_el = timer_def.find(f"{{{BPMN_NS}}}timeCycle")
		if cycle_el is not None and cycle_el.text:
			val = cycle_el.text.strip()
			if re.search(r"/PT\d+S\s*$", val, re.IGNORECASE):
				errors.append(
					f'Timer "{label}": Cycle "{val}" uses second-level intervals. '
					f"Minimum cycle interval is 1 minute. Use cron expressions or PT1M."
				)

	if errors:
		frappe.throw(
			_(
				"Timer validation failed - Frappe scheduler only supports minute-level precision:\n\n"
				+ "\n".join(f"• {e}" for e in errors)
			),
			title=_("Invalid Timer Configuration"),
		)


def validate_start_event_timers(bpmn_xml: str) -> None:
	"""Refuse a Timer Start Event whose cycle is neither a cron expression nor an ISO repeating interval."""
	import xml.etree.ElementTree as _ET

	from processa.processa_engine.timers import timer_start_is_due

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	if not bpmn_xml or not bpmn_xml.strip():
		return

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return  # XML errors are caught elsewhere

	errors = []
	now = frappe.utils.now_datetime()

	for start_event in root.iter(f"{{{BPMN_NS}}}startEvent"):
		timer_def = start_event.find(f"{{{BPMN_NS}}}timerEventDefinition")
		if timer_def is None:
			continue

		label = start_event.get("name") or start_event.get("id", "unknown")
		expression = timer_def.get(f"{{{SPIFF_NS}}}cronExpression", "")
		if not expression:
			cycle_el = timer_def.find(f"{{{BPMN_NS}}}timeCycle")
			expression = (cycle_el.text or "").strip() if cycle_el is not None else ""

		if not expression:
			errors.append(
				_('Timer Start Event "{0}" has no cycle. Give it a cron expression '
					'(e.g. "*/5 * * * *") or an ISO repeating interval '
					'(e.g. "R/2026-01-01T06:00:00+03:00/P1D").').format(label)
			)
			continue

		try:
			timer_start_is_due(expression, now)  # raises on a cycle it cannot read
		except Exception:
			errors.append(
				_('Timer Start Event "{0}": cycle "{1}" is neither a cron expression '
					"nor an ISO repeating interval, so the scheduler can never fire it.").format(
					label, expression
				)
			)

	if errors:
		frappe.throw(
			"\n\n".join(errors),
			title=_("Invalid Timer Start Event"),
		)


def detach_start_timer_definitions(bpmn_xml: str) -> str:
	"""Drop timer definitions from start events in the copy handed to the parser; the scheduler starts those processes."""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	if not bpmn_xml or not bpmn_xml.strip():
		return bpmn_xml

	_ET.register_namespace("bpmn", BPMN_NS)
	_ET.register_namespace("bpmndi", "http://www.omg.org/spec/BPMN/20100524/DI")
	_ET.register_namespace("dc", "http://www.omg.org/spec/DD/20100524/DC")
	_ET.register_namespace("di", "http://www.omg.org/spec/DD/20100524/DI")
	_ET.register_namespace("spiffworkflow", "http://spiffworkflow.org/bpmn/schema/1.0/core")

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return bpmn_xml  # XML errors are caught elsewhere

	detached = False
	for start_event in root.iter(f"{{{BPMN_NS}}}startEvent"):
		for timer_def in start_event.findall(f"{{{BPMN_NS}}}timerEventDefinition"):
			start_event.remove(timer_def)
			detached = True

	if not detached:
		return bpmn_xml

	rewritten = _ET.tostring(root, encoding="unicode", xml_declaration=False)
	if bpmn_xml.strip().startswith("<?xml"):
		decl_end = bpmn_xml.index("?>") + 2
		return bpmn_xml[:decl_end] + "\n" + rewritten
	return rewritten
