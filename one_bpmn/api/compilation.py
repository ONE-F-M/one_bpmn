# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.utils import cint


def _sanitize_bpmn_xml(bpmn_xml: str) -> str:
	"""
	Remove orphaned references to deleted elements from a BPMN XML string.

	When an element is deleted in bpmn-js the definition is removed but
	references in lanes (flowNodeRef), sequence flows, associations, and
	diagram shapes are sometimes left as orphans.  SpiffWorkflow then raises
	"found two items, perhaps a form has the same ID?".

	This function collects all IDs actually defined in the process body, then
	strips every reference that points to a non-existent ID.
	Returns sanitized XML as a string. Falls back to original XML on any error.
	"""
	try:
		from lxml import etree

		BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
		BPMNDI = "http://www.omg.org/spec/BPMN/20100524/DI"

		parser = etree.XMLParser(resolve_entities=False, no_network=True)
		root = etree.fromstring(bpmn_xml.strip().encode("utf-8"), parser=parser)

		# 1. Collect IDs of elements actually defined inside <bpmn:process>
		defined_ids = set()
		for process in root.iter(f"{{{BPMN}}}process"):
			for child in process:
				eid = child.get("id")
				if eid:
					defined_ids.add(eid)

		# 2. Strip orphaned <bpmn:flowNodeRef> entries inside lanes
		for lane in root.iter(f"{{{BPMN}}}lane"):
			to_remove = [
				fnr
				for fnr in lane.findall(f"{{{BPMN}}}flowNodeRef")
				if (fnr.text or "").strip() not in defined_ids
			]
			for fnr in to_remove:
				lane.remove(fnr)

		# 3. Strip sequence flows whose source or target no longer exists
		for process in root.iter(f"{{{BPMN}}}process"):
			to_remove = [
				sf
				for sf in process.findall(f"{{{BPMN}}}sequenceFlow")
				if sf.get("sourceRef", "") not in defined_ids or sf.get("targetRef", "") not in defined_ids
			]
			for sf in to_remove:
				process.remove(sf)

		# 4. Strip associations whose source AND target are both gone
		for collab in root.iter(f"{{{BPMN}}}collaboration"):
			to_remove = [
				a
				for a in collab.findall(f"{{{BPMN}}}association")
				if a.get("sourceRef", "") not in defined_ids and a.get("targetRef", "") not in defined_ids
			]
			for a in to_remove:
				collab.remove(a)

		# 5. Strip BPMNShape entries whose bpmnElement no longer exists
		#    Only remove shapes for process-flow elements — not lane/participant
		#    shapes which are legitimately defined outside <bpmn:process>.
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

		# 6. Encode raw HTML attribute values to base64
		#    notifyAssigneeBody and emailBody may contain raw HTML (e.g. <p>Hello</p>)
		#    which breaks XML parsers.  Encode to base64 for safe storage.
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
				# Already base64? Try decoding — if it produces valid UTF-8
				# without angle brackets, it's already encoded.
				try:
					decoded = _b64.b64decode(raw).decode("utf-8")
					# Successfully decoded — already base64
					continue
				except Exception:
					pass
				# Raw HTML detected — encode to base64
				encoded = _b64.b64encode(raw.encode("utf-8")).decode("ascii")
				elem.set(attr_key, encoded)

		return etree.tostring(root, encoding="unicode", xml_declaration=False)

	except Exception:
		# If sanitisation fails for any reason, return the original and let
		# SpiffWorkflow's own parser produce the actual error message.
		return bpmn_xml


def _extract_service_task_config(bpmn_xml: str) -> dict:
	"""
	Parse the BPMN XML and extract every ``spiffworkflow:*`` attribute set on
	``<bpmn:serviceTask>`` elements.

	The bpmn-js moddle stores custom properties as XML attributes using the
	spiffworkflow namespace (e.g. ``spiffworkflow:serviceType``).
	SpiffWorkflow's Python parser does NOT read these attributes, so they
	would otherwise be invisible at runtime.  We extract them once at compile
	time and embed them in the serialized spec so the engine can dispatch to
	the correct handler when the task executes.

	Returns:
		dict keyed by BPMN element ID::

			{
				"Activity_097ls3l": {
					"serviceType": "apply_workflow",
					"workflowState": "Draft",
					"onlyAllowEdit": "Employee",
				},
			}
	"""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return {}

	config = {}
	for service_task in root.iter(f"{{{BPMN_NS}}}serviceTask"):
		bpmn_id = service_task.get("id")
		if not bpmn_id:
			continue

		task_cfg = {}
		for attr_name, attr_value in service_task.attrib.items():
			if attr_name.startswith(f"{{{SPIFF_NS}}}"):
				key = attr_name[len(f"{{{SPIFF_NS}}}") :]
				task_cfg[key] = attr_value

		if task_cfg:
			config[bpmn_id] = task_cfg

	return config


def _extract_user_task_config(bpmn_xml: str) -> dict:
	"""
	Parse the BPMN XML and extract every ``spiffworkflow:*`` attribute set on
	``<bpmn:userTask>`` elements (assignment mode, doctype, users list, etc.).

	Mirors ``_extract_service_task_config`` but for UserTasks.

	Returns:
		dict keyed by BPMN element ID::

			{
				"Activity_1abc": {
					"assigneeMode": "Round Robin",
					"assigneeUsers": "admin@example.com,hr@example.com",
					"targetDoctype": "Employee",
				},
			}
	"""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return {}

	config = {}
	for user_task in root.iter(f"{{{BPMN_NS}}}userTask"):
		bpmn_id = user_task.get("id")
		if not bpmn_id:
			continue

		task_cfg = {}
		for attr_name, attr_value in user_task.attrib.items():
			if attr_name.startswith(f"{{{SPIFF_NS}}}"):
				key = attr_name[len(f"{{{SPIFF_NS}}}") :]
				task_cfg[key] = attr_value

		if task_cfg:
			config[bpmn_id] = task_cfg

	return config


def _validate_timer_granularity(bpmn_xml: str) -> None:
	"""
	Validate that no timer event uses second-level precision.

	Frappe's scheduler runs at minute intervals only — values like
	``PT15S`` (15 seconds) or ``R5/PT10S`` (every 10 seconds, 5 times)
	will never fire correctly. This validation rejects such values at
	deploy time with a clear error message.

	Checks all ``<bpmn:timerEventDefinition>`` elements in the XML:
	  - ``<bpmn:timeDuration>`` values ending with digits + 'S' (e.g. PT15S)
	  - ``<bpmn:timeCycle>`` values with second-level ISO intervals (e.g. R5/PT10S)
	"""
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
		# Find the parent element name for a better error message
		parent = None
		for elem in root.iter():
			if timer_def in list(elem):
				parent = elem
				break
		parent_id = parent.get("id", "unknown") if parent is not None else "unknown"
		parent_name = parent.get("name", "") if parent is not None else ""
		label = parent_name or parent_id

		# Check timeDuration
		duration_el = timer_def.find(f"{{{BPMN_NS}}}timeDuration")
		if duration_el is not None and duration_el.text:
			val = duration_el.text.strip()
			# Match durations with only seconds: PT15S, PT30S, etc.
			# Also match mixed with seconds: PT1M30S
			if re.search(r"\d+S\s*$", val, re.IGNORECASE):
				if not re.search(r"[DHMY]\d*M", val, re.IGNORECASE) and not re.search(
					r"\d+M\d+S", val, re.IGNORECASE
				):
					# Pure seconds like PT15S
					errors.append(
						f'Timer "{label}": Duration "{val}" uses seconds. '
						f"Minimum supported duration is 1 minute (PT1M)."
					)
				else:
					# Mixed with seconds like PT1M30S — warn
					errors.append(
						f'Timer "{label}": Duration "{val}" includes a seconds component. '
						f"Frappe scheduler runs at minute intervals — seconds will be ignored. "
						f"Use whole minutes instead."
					)

		# Check timeCycle
		cycle_el = timer_def.find(f"{{{BPMN_NS}}}timeCycle")
		if cycle_el is not None and cycle_el.text:
			val = cycle_el.text.strip()
			# ISO 8601 repeating with seconds: R5/PT10S, R/PT30S
			if re.search(r"/PT\d+S\s*$", val, re.IGNORECASE):
				errors.append(
					f'Timer "{label}": Cycle "{val}" uses second-level intervals. '
					f"Minimum cycle interval is 1 minute. Use cron expressions or PT1M."
				)

	if errors:
		frappe.throw(
			_(
				"Timer validation failed — Frappe scheduler only supports minute-level precision:<br><br>"
				+ "<br>".join(f"• {e}" for e in errors)
			),
			title=_("Invalid Timer Configuration"),
		)


# ── Prohibited shapes — shapes that must NOT appear in executable processes ──
# Each key is a BPMN element local name (the tag after the namespace).
# Values provide a human-readable label and a suggested replacement.
# Populate this dict with the shapes OneFM wants to prohibit.
PROHIBITED_SHAPES: dict[str, dict[str, str]] = {
	"manualTask": {
		"label": "Manual Task",
		"suggestion": "Use a User Task instead",
	},
	"task": {
		"label": "None-type Task",
		"suggestion": "Use a User Task instead",
	},
}


def _validate_prohibited_shapes(bpmn_xml: str) -> None:
	"""
	Validate that no prohibited BPMN shapes appear in the process.

	Scans all elements under ``<bpmn:process>`` and rejects any whose local
	tag name is listed in :data:`PROHIBITED_SHAPES`.  Called at deploy time
	to block deployment of processes containing unsupported shapes.

	Raises:
		frappe.ValidationError: If one or more prohibited shapes are found.
	"""
	if not PROHIBITED_SHAPES:
		return  # Nothing to check — no shapes are currently prohibited

	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	if not bpmn_xml or not bpmn_xml.strip():
		return

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return  # XML errors are caught elsewhere

	process_el = root.find(f"{{{BPMN_NS}}}process") or root.find("process")
	if process_el is None:
		return

	errors = []

	for child in process_el:
		local_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
		if local_tag in PROHIBITED_SHAPES:
			shape_info = PROHIBITED_SHAPES[local_tag]
			el_name = child.get("name", "").strip()
			el_id = child.get("id", "unknown")
			label = f'"{el_name}" ({el_id})' if el_name else f"({el_id})"
			suggestion = shape_info.get("suggestion", "")
			msg = f'{shape_info["label"]} {label} is not allowed in executable processes.'
			if suggestion:
				msg += f" {suggestion}."
			errors.append(msg)

	if errors:
		frappe.throw(
			_(
				"Prohibited shapes found — the following BPMN elements are not allowed "
				"in executable processes:<br><br>"
				+ "<br>".join(f"• {e}" for e in errors)
			),
			title=_("Prohibited Shapes Detected"),
		)


def _populate_start_events(model, bpmn_xml: str) -> None:
	"""
	Parse the BPMN XML and populate the ``start_events`` child table on the
	Process Model with one row per ``<bpmn:startEvent>`` element.

	Detects event type from child definitions:
	  - ``<bpmn:conditionalEventDefinition>`` → Conditional
	  - ``<bpmn:timerEventDefinition>``       → Timer
	  - ``<bpmn:signalEventDefinition>``      → Signal
	  - No definition element                 → None (plain start)

	Extracts configuration from ``spiffworkflow:*`` attributes:
	  - triggerWorkflowState → workflow_state_condition
	  - triggerDoctype       → trigger_doctype
	  - triggerType          → trigger_event (e.g. "After Insert")
	  - cronExpression       → cron_expression (on timer definitions)

	Also syncs model-level trigger fields (trigger_type, trigger_doctype,
	trigger_event) so that trigger.py can fire process instances.

	Note: This function modifies the model in-memory only — the caller is
	responsible for calling model.save().
	"""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	# Clear existing rows
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

		# ── Detect event type from child definition elements ───────────
		event_type = "None"
		cron_expr = ""

		cond_def = start_event.find(f"{{{BPMN_NS}}}conditionalEventDefinition")
		timer_def = start_event.find(f"{{{BPMN_NS}}}timerEventDefinition")
		signal_def = start_event.find(f"{{{BPMN_NS}}}signalEventDefinition")

		if cond_def is not None:
			event_type = "Conditional"
		elif timer_def is not None:
			event_type = "Timer"
			# Extract cron from timer definition's spiffworkflow:cronExpression
			cron_expr = timer_def.get(f"{{{SPIFF_NS}}}cronExpression", "")
			# Also check for timeCycle/timeDuration child elements
			if not cron_expr:
				cycle = timer_def.find(f"{{{BPMN_NS}}}timeCycle")
				if cycle is not None and cycle.text:
					cron_expr = cycle.text.strip()
		elif signal_def is not None:
			event_type = "Signal"

		# ── Extract spiffworkflow:* attributes from the start event ────
		workflow_state = start_event.get(f"{{{SPIFF_NS}}}triggerWorkflowState", "")
		trigger_doctype = start_event.get(f"{{{SPIFF_NS}}}triggerDoctype", "")
		trigger_type_attr = start_event.get(f"{{{SPIFF_NS}}}triggerType", "")

		# Also check conditional definition for nested attributes
		if cond_def is not None and not workflow_state:
			workflow_state = cond_def.get(f"{{{SPIFF_NS}}}triggerWorkflowState", "")
		if cond_def is not None and not trigger_doctype:
			trigger_doctype = cond_def.get(f"{{{SPIFF_NS}}}triggerDoctype", "")
		if cond_def is not None and not trigger_type_attr:
			trigger_type_attr = cond_def.get(f"{{{SPIFF_NS}}}triggerType", "")

		# ── Resolve trigger_event from XML or fall back to model field ──
		trigger_event = trigger_type_attr or model.trigger_event or ""

		# ── Determine trigger_type for this specific start event ──
		trigger_type = "API"  # Default
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
			},
		)

	# ── Sync spec → model-level trigger fields (DECOMMISSIONED) ────────────────
	# Note: Model-level trigger fields are now kept for backward compatibility
	# but are no longer updated. trigger.py and tasks.py now look at the
	# start_events child table directly to support multiple start triggers.
	pass


def _get_linked_server_scripts(spec_json: str) -> set:
	"""
	Extract the set of Server Script names referenced by Script Tasks
	in a BPMN Process Model's serialized spec.

	Args:
		spec_json: JSON string from BPMN Process Model.serialized_spec

	Returns:
		set of Server Script names (may be empty)
	"""
	if not spec_json:
		return set()
	try:
		spec_data = json.loads(spec_json)
	except (json.JSONDecodeError, TypeError):
		return set()

	scripts = set()
	for cfg in spec_data.get("script_task_extensions", {}).values():
		name = cfg.get("serverScript", "")
		if name:
			scripts.add(name)
	return scripts


def _activate_deployed_model(model, script_extensions: dict) -> None:
	"""
	Handle the deployment lifecycle for a BPMN Process Model:

	1. Mark the model as active (``is_active = 1``)
	2. Deactivate sibling models with the same ``process_name``
	3. Enable Server Scripts linked to the deployed model
	4. Disable Server Scripts linked to deactivated siblings
	   (unless shared with the active model)

	Modifies the model in-memory — the caller is responsible for
	calling ``model.save()``.

	Args:
		model:             BPMN Process Model document (in-memory)
		script_extensions: dict from ``_extract_script_task_config()``
	"""

	model.is_active = 1
	model.deployed_at = frappe.utils.now()
	model.deployed_by = frappe.session.user

	# Server scripts referenced by the deployed model
	active_scripts = set()
	for cfg in (script_extensions or {}).values():
		if cfg.get("serverScript"):
			active_scripts.add(cfg["serverScript"])

	# Fetch active siblings once — used for both version calculation and deactivation
	siblings = []
	if model.process_name:
		siblings = frappe.get_all(
			"BPMN Process Model",
			filters={
				"process_name": model.process_name,
				"is_active": 1,
				"name": ["!=", model.name],
			},
			fields=["name", "version", "serialized_spec"],
		)

	# Version: max sibling version + 1, or 1 if no siblings
	max_sibling_version = max((s.version or 0 for s in siblings), default=0)
	model.version = max_sibling_version + 1

	# Deactivate sibling models and their exclusive server scripts
	if siblings:
		sibling_scripts = set()
		for s in siblings:
			sibling_scripts |= _get_linked_server_scripts(s.serialized_spec)
			frappe.db.set_value("BPMN Process Model", s.name, "is_active", 0)

		# Disable scripts exclusive to deactivated siblings
		for script_name in (sibling_scripts - active_scripts):
			if frappe.db.exists("Server Script", script_name):
				frappe.db.set_value("Server Script", script_name, "disabled", 1)

	# Enable server scripts linked to the deployed model
	for script_name in active_scripts:
		if frappe.db.exists("Server Script", script_name):
			frappe.db.set_value("Server Script", script_name, "disabled", 0)


def _update_round_robin_in_model(model_name: str, task_bpmn_id: str, last_user: str) -> None:
	"""
	Update the round-robin tracking state on the BPMN Process Model:

	  1. Reads/increments ``next_idx`` in ``round_robin_state`` JSON field.
	  2. Updates ``spiffworkflow:roundRobinLastUser`` attribute in the stored
		 BPMN XML so the editor reflects the last-assigned user.
	  3. Saves the model with ``ignore_permissions=True`` (called from engine).
	"""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	try:
		model = frappe.get_doc("BPMN Process Model", model_name)
		state = json.loads(model.round_robin_state or "{}")
		if task_bpmn_id not in state:
			state[task_bpmn_id] = {"next_idx": 0, "last_user": ""}
		state[task_bpmn_id]["last_user"] = last_user
		model.round_robin_state = json.dumps(state)

		# ---  Also patch the BPMN XML so the editor shows the last user  ---
		if model.bpmn_xml:
			try:
				_ET.register_namespace("", BPMN_NS)
				_ET.register_namespace("spiffworkflow", SPIFF_NS)
				root = _ET.fromstring(model.bpmn_xml.strip().encode("utf-8"))
				attr_key = f"{{{SPIFF_NS}}}roundRobinLastUser"
				for el in root.iter(f"{{{BPMN_NS}}}userTask"):
					if el.get("id") == task_bpmn_id:
						el.set(attr_key, last_user)
						break
				model.bpmn_xml = _ET.tostring(root, encoding="unicode", xml_declaration=False)
			except Exception:
				pass  # XML patch failure is non-fatal — state field is the truth

		model.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="BPMN: round-robin state update failed",
			message=frappe.get_traceback(),
		)


def _ensure_script_task_inline_scripts(bpmn_xml: str) -> str:
	"""
	Ensure every ``<bpmn:scriptTask>`` element in the BPMN XML has at least
	a ``<bpmn:script>pass</bpmn:script>`` child element.

	SpiffWorkflow's parser asserts exactly one ``<bpmn:script>`` element per
	Script Task.  When a designer uses ONLY the Server Script picker (our
	custom behaviour) and does not write any inline script, bpmn-js omits the
	``<bpmn:script>`` tag entirely.  Without this function the compile step
	would fail with:

		AssertionError: Expected 1 result. Received 0 results.

	At runtime FrappeScriptEngine ignores the inline "pass" script when a
	Server Script is configured and calls the Server Script directly instead.
	"""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	try:
		# Register namespace to avoid ns0 prefix noise in output
		_ET.register_namespace("bpmn", BPMN_NS)
		_ET.register_namespace("bpmndi", "http://www.omg.org/spec/BPMN/20100524/DI")
		_ET.register_namespace("dc", "http://www.omg.org/spec/DD/20100524/DC")
		_ET.register_namespace("di", "http://www.omg.org/spec/DD/20100524/DI")
		_ET.register_namespace("spiffworkflow", "http://spiffworkflow.org/bpmn/schema/1.0/core")

		encoded = bpmn_xml.strip().encode("utf-8")
		root = _ET.fromstring(encoded)

		injected = 0
		for script_task in root.iter(f"{{{BPMN_NS}}}scriptTask"):
			# Check if a <bpmn:script> element already exists
			existing = script_task.findall(f"{{{BPMN_NS}}}script")
			if not existing:
				# Inject a minimal "pass" script as the FIRST child element
				script_elem = _ET.Element(f"{{{BPMN_NS}}}script")
				script_elem.text = "pass  # executed by FrappeScriptEngine (Server Script)"
				script_task.insert(0, script_elem)
				injected += 1

		if injected == 0:
			return bpmn_xml  # nothing to change — return original string

		# Re-serialize preserving the XML declaration (if any)
		xml_bytes = _ET.tostring(root, encoding="unicode", xml_declaration=False)
		if bpmn_xml.strip().startswith("<?xml"):
			# Restore the declaration
			decl_end = bpmn_xml.index("?>") + 2
			return bpmn_xml[:decl_end] + "\n" + xml_bytes
		return xml_bytes

	except Exception:
		# If parsing fails here just return the original — parse_bpmn will surface the real error
		return bpmn_xml


def _extract_business_rule_task_decisions(bpmn_xml: str) -> list:
	"""
	Parse the BPMN XML and extract the ``calledDecisionId`` values from all
	``<bpmn:businessRuleTask>`` elements.

	The calledDecisionId is stored by bpmn-js-spiffworkflow as a spiffworkflow
	extension element::

	    <bpmn:businessRuleTask id="Activity_1abc" name="Check Eligibility">
	      <bpmn:extensionElements>
	        <spiffworkflow:calledDecisionId>my_decision</spiffworkflow:calledDecisionId>
	      </bpmn:extensionElements>
	    </bpmn:businessRuleTask>

	The returned list of decision IDs must each match a ``<decision id="...">``
	attribute inside a DMN XML document.

	Returns:
		List of calledDecisionId strings (may be empty).
	"""
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
		# Look for <spiffworkflow:calledDecisionId> inside extensionElements
		ext_els = brt.find(f"{{{BPMN_NS}}}extensionElements")
		if ext_els is None:
			continue
		called = ext_els.find(f"{{{SPIFF_NS}}}calledDecisionId")
		if called is not None and called.text and called.text.strip():
			decision_ids.append(called.text.strip())

	return decision_ids


def _extract_dmn_decision_id(dmn_xml: str) -> str:
	"""
	Extract the ``<decision id="...">`` value from a DMN XML string.

	The DMN parser registers each document by this ID, which must match
	the ``calledDecisionId`` in the BPMN XML.

	Returns:
		The decision ID string, or empty string if not found.
	"""
	import xml.etree.ElementTree as _ET

	if not dmn_xml or not dmn_xml.strip():
		return ""

	try:
		root = _ET.fromstring(
			dmn_xml.strip().encode("utf-8") if isinstance(dmn_xml, str) else dmn_xml
		)
	except Exception:
		return ""

	# DMN namespace varies by version; find any <decision> element
	for child in root:
		tag_local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
		if tag_local == "decision":
			return child.get("id", "")

	return ""


def _validate_workflow_state_field(model, service_extensions: dict) -> None:
	"""
	At deploy time, verify that every doctype referenced in the process model
	has a ``workflow_state`` field when the process depends on workflow state —
	either via a workflow-state start-event trigger or an ``apply_workflow``
	service task.

	Raises ``frappe.ValidationError`` for each doctype missing the field.
	Skips entirely when neither condition is present in the model.
	"""
	has_workflow_state_trigger = any(
		row.workflow_state_condition for row in (model.start_events or [])
	)
	has_apply_workflow_task = any(
		cfg.get("serviceType") == "apply_workflow"
		for cfg in service_extensions.values()
	)

	if not has_workflow_state_trigger and not has_apply_workflow_task:
		return

	# Collect only doctypes involved in workflow operations
	doctypes_to_check = set()

	# Start events that trigger on a specific workflow state
	if has_workflow_state_trigger:
		for row in (model.start_events or []):
			if not row.workflow_state_condition:
				continue
			dt = row.trigger_doctype or model.trigger_doctype
			if dt:
				doctypes_to_check.add(dt)

	# Apply Workflow service tasks — use explicit override or fall back to all context doctypes
	if has_apply_workflow_task:
		for cfg in service_extensions.values():
			if cfg.get("serviceType") != "apply_workflow":
				continue
			target = cfg.get("serviceTargetDoctype")
			if target:
				doctypes_to_check.add(target)
			else:
				if model.trigger_doctype:
					doctypes_to_check.add(model.trigger_doctype)
				for row in (model.target_doctypes or []):
					if row.doctype_name:
						doctypes_to_check.add(row.doctype_name)

	missing = []
	for doctype in sorted(doctypes_to_check):
		try:
			meta = frappe.get_meta(doctype)
		except Exception:
			continue  # unknown doctype — let other validations surface it
		if not meta.get_field("workflow_state"):
			missing.append(doctype)

	if not missing:
		return

	error_lines = [_("Workflow State field is missing on: {0}").format(dt) for dt in missing]
	frappe.throw(
		"<br>".join(f"• {line}" for line in error_lines),
		title=_("Missing Workflow State Field"),
	)


def _extract_script_task_config(bpmn_xml: str) -> dict:
	"""
	Extract Script Task configuration from BPMN XML at compile time.

	Reads the ``spiffworkflow:serverScript`` attribute from every
	``<bpmn:scriptTask>`` element and returns a dict keyed by BPMN element ID.

	The attribute is written by the BPMN editor as a direct XML attribute on
	the ``<bpmn:scriptTask>`` element, e.g.:

		<bpmn:scriptTask id="Task_1"
			spiffworkflow:serverScript="My Server Script">
		  <bpmn:script>pass</bpmn:script>
		</bpmn:scriptTask>

	Fallback: if no ``spiffworkflow:serverScript`` attribute is set, but the
	inline ``<bpmn:script>`` content looks like a Frappe record name (i.e. it
	does NOT contain Python keywords such as ``=``, ``(``, newlines, etc.), it
	is treated as a Server Script name.  This handles diagrams where the
	designer typed the Server Script name directly into the inline script field
	before the dedicated UI picker existed.

	Embedded at compile time in ``serialized_spec["script_task_extensions"]``.
	"""
	import keyword as _kw
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	def _looks_like_python(text: str) -> bool:
		"""Return True if the text is likely inline Python (not a record name)."""
		if not text:
			return False
		# Heuristics: contains Python-ish characters or keywords
		py_chars = ("=", "(", ")", "{", "}", ":", "\n", ".", "import", "def ", "class ", "return")
		lower = text.strip().lower()
		if any(c in lower for c in py_chars):
			return True
		# Single-word Python keywords (pass, exec, etc.)
		if lower in _kw.kwlist:
			return True
		return False

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8"))
	except Exception:
		return {}

	extensions = {}
	for elem in root.iter(f"{{{BPMN_NS}}}scriptTask"):
		bpmn_id = elem.get("id", "")
		if not bpmn_id:
			continue

		# ── Primary: spiffworkflow:serverScript attribute ──────────────────────
		server_script = elem.get(f"{{{SPIFF_NS}}}serverScript", "").strip()

		# ── Fallback: inline <bpmn:script> content that is a record name ──────
		if not server_script:
			script_elem = elem.find(f"{{{BPMN_NS}}}script")
			if script_elem is not None and script_elem.text:
				inline = script_elem.text.strip()
				if inline and not _looks_like_python(inline):
					server_script = inline  # treat as Server Script name

		if server_script:
			extensions[bpmn_id] = {"serverScript": server_script}

	return extensions


def _validate_adhoc_selector_pool(bpmn_xml: str, model_name: str | None = None) -> None:
	"""
	Compile-time validation of an AI Task Selector's candidate pool
	(WI-001353). Runs while the designer edits, not at dispatch time.

	1. Eligibility (decision 2026-07-02): candidates are leaf task
	   activities only. A container activity — embedded Sub-Process,
	   Call Activity, Transaction or nested Ad-hoc Subprocess — with no
	   incoming sequence flow inside a selector-tagged ad-hoc subprocess is
	   rejected with an error naming the element and its type. This also
	   rules out recursive selector-in-selector loops.
	2. Name collisions: a diagram candidate's bpmn_id must not equal an
	   enabled AI Agent Tool name applicable to this process — neither may
	   silently shadow the other.
	"""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	CONTAINER_TAGS = {
		f"{{{BPMN_NS}}}subProcess": "Sub-Process",
		f"{{{BPMN_NS}}}adHocSubProcess": "Ad-hoc Subprocess",
		f"{{{BPMN_NS}}}callActivity": "Call Activity",
		f"{{{BPMN_NS}}}transaction": "Transaction",
	}
	LEAF_TASK_TAGS = {
		f"{{{BPMN_NS}}}task",
		f"{{{BPMN_NS}}}userTask",
		f"{{{BPMN_NS}}}manualTask",
		f"{{{BPMN_NS}}}scriptTask",
		f"{{{BPMN_NS}}}serviceTask",
		f"{{{BPMN_NS}}}sendTask",
		f"{{{BPMN_NS}}}receiveTask",
		f"{{{BPMN_NS}}}businessRuleTask",
	}

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return

	def has_incoming(element):
		return element.find(f"{{{BPMN_NS}}}incoming") is not None

	for adhoc in root.iter(f"{{{BPMN_NS}}}adHocSubProcess"):
		if adhoc.get(f"{{{SPIFF_NS}}}serviceType") != "ai_task_selector":
			continue

		adhoc_id = adhoc.get("id", "?")
		candidate_names = []

		for child in adhoc:
			if has_incoming(child):
				continue  # connected flow, not a selector candidate
			if child.tag in CONTAINER_TAGS:
				frappe.throw(
					_(
						"AI Task Selector '{0}': {1} '{2}' cannot be a selector "
						"candidate — only leaf task activities (Script, Service, "
						"Send, User/Manual, Business Rule) are eligible. Connect "
						"it with a sequence flow or move it out of the subprocess."
					).format(adhoc_id, CONTAINER_TAGS[child.tag], child.get("id", "?")),
					exc=frappe.ValidationError,
				)
			if child.tag in LEAF_TASK_TAGS and child.get("id"):
				candidate_names.append(child.get("id"))

		if not candidate_names or not frappe.db.exists("DocType", "AI Agent Tool"):
			continue

		registry_rows = frappe.get_all(
			"AI Agent Tool",
			filters={"is_active": 1, "tool_name": ["in", candidate_names]},
			fields=["name", "tool_name"],
		)
		for row in registry_rows:
			scoped = frappe.get_all(
				"AI Agent Tool Process",
				filters={"parent": row.name},
				pluck="process_model",
			)
			if scoped and model_name not in scoped:
				continue
			frappe.throw(
				_(
					"AI Task Selector '{0}': inner task '{1}' has the same name "
					"as AI Agent Tool '{1}'. Rename one of them — a diagram task "
					"and a registry tool must not shadow each other."
				).format(adhoc_id, row.tool_name),
				exc=frappe.ValidationError,
			)


def _lint_ai_provider_config(_bpmn_xml: str, service_extensions: dict) -> None:
	"""
	Compile-time lint for AI Agent Tasks:
	1. Rejects raw API keys embedded in any spiffworkflow:ai* attribute.
	2. Validates that referenced AI Provider records exist in the database.
	"""
	import re
	_RAW_KEY_RE = re.compile(r"^(sk-|key-)", re.IGNORECASE)
	_RAW_KEY_ATTR_NAMES = frozenset({"aiApiKey", "aiKey"})

	for bpmn_id, task_cfg in (service_extensions or {}).items():
		if task_cfg.get("serviceType") != "ai_agent":
			continue

		for attr_name, attr_value in task_cfg.items():
			if attr_name in _RAW_KEY_ATTR_NAMES or _RAW_KEY_RE.match(str(attr_value)):
				frappe.throw(
					_(
						"Raw API keys must not appear in BPMN XML "
						"(task '{0}', attribute '{1}'). "
						"Use an AI Provider reference."
					).format(bpmn_id, attr_name),
					exc=frappe.ValidationError,
				)

		provider_name = (task_cfg.get("aiProvider") or "").strip()
		if provider_name and not frappe.db.exists("AI Provider", provider_name):
			frappe.throw(
				_(
					"AI Provider '{0}' not found (task '{1}'). "
					"Create it in the AI Provider list."
				).format(provider_name, bpmn_id),
				exc=frappe.ValidationError,
			)


def _check_eval_suite_gating(model_name: str) -> list:
	"""
	Check linked AI Eval Suites with ``gate_deployment=True`` and return
	advisory warning messages based on the latest AI Eval Run status.

	This is a non-blocking check — warnings are informational only and
	never prevent deployment.

	Args:
		model_name: Name of the BPMN Process Model being deployed.

	Returns:
		list of warning strings (may be empty).
	"""
	warnings = []

	suites = frappe.get_list(
		"AI Eval Suite",
		filters={"process_model": model_name, "gate_deployment": 1},
		fields=["name", "title"],
		ignore_permissions=True,
	)

	if not suites:
		return warnings

	for suite in suites:
		suite_title = suite.title or suite.name

		# Find the most recent eval run for this suite
		latest_runs = frappe.get_list(
			"AI Eval Run",
			filters={"suite": suite.name},
			fields=["name", "status", "started_at"],
			order_by="started_at desc",
			limit_page_length=1,
			ignore_permissions=True,
		)

		if not latest_runs:
			warnings.append(
				_("Eval suite '{0}' has never been run. "
				  "Consider running it before deploying.").format(suite_title)
			)
		elif latest_runs[0].status == "Failed":
			run_date = frappe.utils.formatdate(latest_runs[0].started_at)
			warnings.append(
				_("Eval suite '{0}' failed — last run on {1}. "
				  "Consider re-running the suite before deploying.").format(
					suite_title, run_date
				)
			)
		# If status is "Passed" (or anything else), no warning is added.

	return warnings


@frappe.whitelist()
def compile_process_model(model_name: str) -> dict:
	"""
	Parse the BPMN XML in a Process Model and store the compiled spec.

	Must be called after saving/importing a diagram before any instance
	can be started.  Stores the result in:
		BPMN Process Model.serialized_spec  (main process spec)
		BPMN Process Model.subprocess_specs (call activities / sub-processes)

	Args:
		model_name: Name of the BPMN Process Model

	Returns:
		dict with success, version, subprocess_count
	"""
	if not model_name:
		frappe.throw(_("Model name is required"))

	model = frappe.get_doc("BPMN Process Model", model_name)
	model.check_permission("write")

	if not model.bpmn_xml:
		frappe.throw(_("No BPMN XML found in process model '{0}'").format(model_name))

	# ── Always extract the real process_id from the XML ──────────────────────
	# The stored process_id field may be a stale UUID assigned at record-create
	# time, while the BPMN diagram itself uses a different id (e.g. 'Process_1').
	# SpiffWorkflow will fail if the two don't match, so we re-sync here.
	import xml.etree.ElementTree as _ET

	_bpmn_ns = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	try:
		_root = _ET.fromstring(model.bpmn_xml.strip().encode("utf-8"))
		_process_el = _root.find(f"{{{_bpmn_ns}}}process") or _root.find("process")
		if _process_el is not None:
			xml_process_id = _process_el.get("id", "").strip()
			if xml_process_id and xml_process_id != model.process_id:
				# Sync the field so it always reflects the XML truth
				model.process_id = xml_process_id

			# Block deploy if process is not marked executable in the diagram
			is_executable = _process_el.get("isExecutable", "false").strip().lower()
			if is_executable != "true":
				frappe.throw(
					_("Cannot deploy '{0}': the process is not marked as Executable. "
					  "Open the diagram, select the process (click the pool header or empty canvas), "
					  "and enable the 'Executable' checkbox in the properties panel.").format(model_name),
					title=_("Process Not Executable"),
				)
	except frappe.ValidationError:
		raise  # Re-raise our own validation errors
	except Exception:
		pass  # XML parse errors will surface properly in parse_bpmn() below

	if not model.process_id:
		frappe.throw(
			_("No process_id found in the BPMN XML for '{0}'. Save the Process Map first.").format(model_name)
		)

	from one_bpmn.one_bpmn import engine as bpmn_engine

	# Sanitize XML before parsing
	sanitized_xml = _sanitize_bpmn_xml(model.bpmn_xml)

	# Ensure every ScriptTask has a <bpmn:script> element.
	# SpiffWorkflow REQUIRES a non-empty <bpmn:script> element to parse a
	# scriptTask.  When a designer configures only a Server Script via our
	# properties panel (no inline script), no <bpmn:script> element is written
	# by bpmn-js.  We inject "pass" so SpiffWorkflow parses successfully,
	# and the FrappeScriptEngine will replace it with the configured Server Script.
	sanitized_xml = _ensure_script_task_inline_scripts(sanitized_xml)

	# ── Scan for Business Rule Tasks and collect DMN XML ─────────────────
	# Business Rule Tasks reference a calledDecisionId in the spiffworkflow
	# extension elements.  Each referenced decision must have a corresponding
	# DMN XML stored in the model's decision_tables child table.
	brt_decision_ids = _extract_business_rule_task_decisions(sanitized_xml)
	dmn_xml_list = []

	if brt_decision_ids:
		# Build a lookup: DMN decision ID → DMN XML string
		# The child table stores rows keyed by BPMN element ID (decision_id),
		# but the DMN parser indexes by the <decision id="..."> attribute
		# INSIDE the DMN XML.  So we parse each DMN XML to extract its internal
		# decision ID and match it against the calledDecisionId list.
		available_dmn = {}  # dmn_decision_id → dmn_xml string
		for row in model.decision_tables or []:
			if row.dmn_xml and row.dmn_xml.strip():
				dmn_id = _extract_dmn_decision_id(row.dmn_xml)
				if dmn_id:
					available_dmn[dmn_id] = row.dmn_xml

		# Collect the DMN XML strings that match the BPMN's calledDecisionIds
		for decision_id in brt_decision_ids:
			if decision_id in available_dmn:
				dmn_xml_list.append(available_dmn[decision_id])

		# Validate: every calledDecisionId must have a matching DMN XML
		found_ids = set(available_dmn.keys())
		missing = set(brt_decision_ids) - found_ids
		if missing:
			frappe.throw(
				_(
					"Cannot deploy: Business Rule Tasks reference decisions "
					"that have no DMN XML in the Decision Tables: {0}.<br><br>"
					"Open each Business Rule Task in the diagram and create a "
					"Decision Table using the DMN modeler."
				).format(", ".join(sorted(missing))),
				title=_("Missing Decision Tables"),
			)

	try:
		spec_dict, sp_dict = bpmn_engine.parse_bpmn(
			bpmn_xml=sanitized_xml,
			process_id=model.process_id,
			dmn_xml_list=dmn_xml_list,
		)
	except Exception as exc:
		frappe.log_error(title="BPMN compile failed", message=frappe.get_traceback())
		frappe.throw(_("Failed to compile BPMN for '{0}': {1}").format(model_name, str(exc)))

	model.serialized_spec = json.dumps(spec_dict)
	model.subprocess_specs = json.dumps(sp_dict)

	# ── Embed all task extensions into the serialized spec in one pass ─────
	# SpiffWorkflow's Python parser ignores custom spiffworkflow:* XML attributes,
	# so we extract them from the BPMN XML now and store them alongside the spec.
	# At runtime, bpmn_process_instance.py reads these to know what each task
	# should actually do (e.g. apply a Frappe workflow state, call a Server Script,
	# resolve user assignments).
	spec_data = json.loads(model.serialized_spec)

	service_extensions = _extract_service_task_config(sanitized_xml)
	if service_extensions:
		spec_data["service_task_extensions"] = service_extensions
	_lint_ai_provider_config(sanitized_xml, service_extensions)
	_validate_adhoc_selector_pool(sanitized_xml, model_name)

	# ── Eval suite deployment gating (non-blocking warnings) ──────────
	deploy_warnings = _check_eval_suite_gating(model_name)

	script_extensions = _extract_script_task_config(sanitized_xml)
	if script_extensions:
		spec_data["script_task_extensions"] = script_extensions

	user_extensions = _extract_user_task_config(sanitized_xml)
	if user_extensions:
		spec_data["user_task_extensions"] = user_extensions

	model.serialized_spec = json.dumps(spec_data)

	# ── Validate timer events (enforce minute-level granularity) ──────────
	# Frappe scheduler only runs at minute intervals — reject any timer value
	# that uses seconds (e.g. PT15S, R5/PT10S).
	_validate_timer_granularity(sanitized_xml)

	# ── Validate prohibited shapes (block unsupported elements) ──────────
	# Reject any BPMN element type that OneFM has marked as prohibited for
	# executable processes (e.g. manual tasks, none-type tasks).
	_validate_prohibited_shapes(sanitized_xml)

	# ── Extract and populate Start Events child table ─────────────────────
	# Parse all <bpmn:startEvent> elements from the XML and capture their type
	# (None, Conditional, Timer, Signal) and configuration into the child table.
	# Also syncs model-level trigger fields (trigger_type, trigger_doctype,
	# trigger_event) from the BPMN XML so trigger.py can fire instances.
	_populate_start_events(model, sanitized_xml)

	# ── Ensure workflow_state field exists on all reference doctypes ──────
	# When the process uses a workflow-state trigger or apply_workflow service
	# task, every referenced doctype must have the field — create it if absent.
	_validate_workflow_state_field(model, service_extensions)

	# ── Activate this model and manage deployment lifecycle ───────────────
	_activate_deployed_model(model, script_extensions)

	# ── Single save ──────────────────────────────────────────────────────
	# Deploy is allowed even on Production — bypass editability gate
	model.flags.skip_editability_check = True
	model.save(ignore_permissions=True)

	result = {
		"success": True,
		"model": model_name,
		"version": model.version,
		"subprocess_count": len(sp_dict),
	}

	if deploy_warnings:
		result["warnings"] = deploy_warnings

	return result


@frappe.whitelist()
def disable_process_model(model_name: str) -> dict:
	"""
	Disable a deployed BPMN Process Model.

	This is the inverse of ``compile_process_model`` (Deploy).  It:
	1. Sets ``is_active = 0`` — trigger.py will stop creating new instances.
	2. Clears ``serialized_spec`` and ``subprocess_specs`` to prevent
	   stale instantiation.
	3. Disables all Server Scripts linked to this model's script tasks.

	Running instances are NOT affected — they continue to completion with
	their own ``workflow_state``.

	Args:
		model_name: Name of the BPMN Process Model to disable.

	Returns:
		dict with keys ``success`` (bool), ``model`` (str), and
		``running_instances`` (int) — the count of in-flight instances.
	"""
	if not model_name:
		frappe.throw(_("Model name is required"))

	model = frappe.get_doc("BPMN Process Model", model_name)
	model.check_permission("write")

	if not model.is_active:
		frappe.throw(
			_("Process map '{0}' is already inactive.").format(model_name),
			title=_("Already Disabled"),
		)

	# ── Deactivate the model ──────────────────────────────────────────────
	model.is_active = 0

	# ── Clear compiled specs (prevents stale instantiation) ───────────────
	# Extract linked scripts BEFORE clearing the spec.
	linked_scripts = _get_linked_server_scripts(model.serialized_spec)
	model.serialized_spec = None
	model.subprocess_specs = None

	# ── Disable linked Server Scripts ─────────────────────────────────────
	for script_name in linked_scripts:
		if frappe.db.exists("Server Script", script_name):
			frappe.db.set_value("Server Script", script_name, "disabled", 1)

	# ── Count running instances (informational) ──────────────────────────
	running_count = frappe.db.count(
		"BPMN Process Instance",
		filters={
			"process_model": model_name,
			"status": ["in", ["Active"]],
		},
	)

	# ── Save — bypass editability gate (same as deploy) ──────────────────
	model.flags.skip_editability_check = True
	model.save(ignore_permissions=True)

	return {
		"success": True,
		"model": model_name,
		"running_instances": running_count,
	}
