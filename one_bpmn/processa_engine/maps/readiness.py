# Copyright (c) 2026, one-fm and contributors
"""Deploy readiness checklist: what a BPMN map needs on this site before it can run."""

from lxml import etree as ET
import frappe
from frappe import _

from one_bpmn.processa_engine.maps.references import extract_bpmn_references, extract_call_activity_refs


def check_readiness(xml_content: str, model_name: str = None) -> dict:
	"""Parse BPMN XML and check all prerequisites against the database."""
	if not xml_content or not xml_content.strip():
		frappe.throw(_("BPMN XML content is required"))

	refs = extract_bpmn_references(xml_content)
	referenced_doctypes = refs["doctypes"]
	referenced_fields = refs["fields"]
	referenced_states = refs["workflow_states"]
	referenced_actions = refs["workflow_actions"]
	referenced_scripts = refs["server_scripts"]
	referenced_lane_roles = refs["lane_roles"]
	_process_el = refs["process_el"]
	is_executable = False
	if _process_el is not None:
		is_executable = _process_el.get("isExecutable", "false").strip().lower() == "true"

	categories = []

	doctype_items = []
	for dt in sorted(referenced_doctypes):
		exists = frappe.db.exists("DocType", dt)
		doctype_items.append({"name": dt, "exists": bool(exists), "type": "check"})
	if doctype_items:
		categories.append({
			"label": "DocTypes",
			"icon": "layout-template",
			"items": doctype_items,
		})

	field_items = []
	seen_fields = set()
	for dt, fieldname in referenced_fields:
		key = f"{fieldname} on {dt}"
		if key in seen_fields:
			continue
		seen_fields.add(key)

		if not frappe.db.exists("DocType", dt):
			field_items.append({"name": key, "exists": False, "type": "check"})
			continue

		try:
			meta = frappe.get_meta(dt)
			# has_field() leaves out the standard columns every table has.
			from frappe.model import default_fields, optional_fields

			exists = bool(
				meta.has_field(fieldname)
				or fieldname in default_fields
				or fieldname in optional_fields
			)
		except Exception:
			exists = False
		field_items.append({"name": key, "exists": exists, "type": "check"})

	if field_items:
		categories.append({
			"label": "Fields",
			"icon": "columns-3",
			"items": field_items,
		})

	state_items = []
	for state in sorted(referenced_states):
		exists = frappe.db.exists("Workflow State", state)
		state_items.append({"name": state, "exists": bool(exists), "type": "check"})
	if state_items:
		categories.append({
			"label": "Workflow States",
			"icon": "git-branch",
			"items": state_items,
		})

	action_items = []
	for action_label in sorted(referenced_actions):
		exists = frappe.db.exists(
			"Workflow Action Master",
			{"workflow_action_name": action_label},
		)
		action_items.append({"name": action_label, "exists": bool(exists), "type": "check"})
	if action_items:
		categories.append({
			"label": "Workflow Actions",
			"icon": "zap",
			"items": action_items,
		})

	script_items = []
	for script_name in sorted(referenced_scripts):
		exists = frappe.db.exists("Server Script", script_name)
		script_items.append({"name": script_name, "exists": bool(exists), "type": "check"})
	if script_items:
		categories.append({
			"label": "Server Scripts",
			"icon": "file-code",
			"items": script_items,
		})

	from one_bpmn.security.script_gate import collect_script_security_violations

	security_items = []
	for finding in collect_script_security_violations(xml_content):
		security_items.append({
			"name": f"{finding['label']}: {finding['message']}",
			"exists": False,
			"type": "check",
		})
	if security_items:
		categories.append({
			"label": "Script Security",
			"icon": "shield-alert",
			"items": security_items,
		})

	agent_items = []
	for shape in _extract_ai_shapes(xml_content):
		label = shape["label"] or shape["id"]
		cfg = shape["config"]
		if not cfg:
			agent_items.append({
				"name": f"{label} - no linked AI Agent Configuration (raw provider setup is retired)",
				"exists": False, "type": "check",
			})
			continue
		row = frappe.db.get_value("AI Agent Configuration", cfg, ["enabled", "lifecycle_status"], as_dict=True)
		if not row:
			agent_items.append({"name": f"{label} - '{cfg}' not found", "exists": False, "type": "check"})
		elif not row.enabled:
			agent_items.append({"name": f"{label} - '{cfg}' is disabled", "exists": False, "type": "check"})
		elif row.lifecycle_status != "Live":
			agent_items.append({
				"name": f"{label} - '{cfg}' is {row.lifecycle_status or 'Draft'} (must be Live to deploy)",
				"exists": False, "type": "check",
			})
		else:
			agent_items.append({"name": f"{label} - {cfg} (Live)", "exists": True, "type": "check"})
	if agent_items:
		categories.append({
			"label": "AI Agents",
			"icon": "bot",
			"items": agent_items,
		})

	from one_bpmn.agents.bpmn_task_config import LANE_ROLE_EXCLUDED, match_lane_role

	role_items = []
	enabled_roles = frappe.get_list("Role", filters={"disabled": 0}, pluck="name") if referenced_lane_roles else []
	for role_name in sorted(referenced_lane_roles):
		role = frappe.db.get_value("Role", role_name, ["name", "disabled"], as_dict=True)
		if not role or role.name in LANE_ROLE_EXCLUDED:
			item = {"name": role_name, "exists": False, "type": "check"}
			item["suggestions"] = match_lane_role(role_name, enabled_roles)
			if frappe.db.exists("User", role_name):
				item["detail"] = _("Not a Role (it matches a User)")
			elif item["suggestions"]:
				item["detail"] = _("Not a Role. Did you mean: {0}").format(", ".join(item["suggestions"]))
			role_items.append(item)
		elif role.disabled:
			role_items.append({
				"name": role_name,
				"exists": False,
				"type": "check",
				"detail": _("Role exists but is disabled"),
			})
		else:
			role_items.append({"name": role_name, "exists": True, "type": "check"})
	if role_items:
		categories.append({
			"label": "Lane Roles",
			"icon": "users",
			"items": role_items,
		})

	from frappe.model.workflow import get_workflow_name

	workflow_items = []
	for dt in sorted(referenced_doctypes):
		if not frappe.db.exists("DocType", dt):
			continue
		wf_name = get_workflow_name(dt)
		if wf_name:
			workflow_items.append({
				"name": f"{wf_name} on {dt}",
				"exists": True,
				"type": "warning",
				"detail": _("Active Frappe Workflow - consider disabling to prevent conflicts with BPMN"),
			})
	if workflow_items:
		categories.append({
			"label": "Frappe Workflows",
			"icon": "workflow",
			"items": workflow_items,
		})

	assignment_items = []
	for dt in sorted(referenced_doctypes):
		if not frappe.db.exists("DocType", dt):
			continue
		active_rules = frappe.get_all(
			"Assignment Rule",
			filters={"document_type": dt, "disabled": 0},
			fields=["name"],
			limit=10,
		)
		for rule in active_rules:
			assignment_items.append({
				"name": f"{rule.name} on {dt}",
				"exists": True,
				"type": "warning",
				"detail": _("Active Assignment Rule - consider disabling to prevent conflicts with BPMN task assignment"),
			})
	if assignment_items:
		categories.append({
			"label": "Assignment Rules",
			"icon": "user-check",
			"items": assignment_items,
		})

	from one_bpmn.processa_engine.compiler.checks import PROHIBITED_SHAPES

	prohibited_items = []
	if PROHIBITED_SHAPES:
		for child in _process_el or []:
			local_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
			if local_tag in PROHIBITED_SHAPES:
				shape_info = PROHIBITED_SHAPES[local_tag]
				el_name = child.get("name", "").strip()
				el_id = child.get("id", "?")
				display_name = f'{shape_info["label"]}: "{el_name}"' if el_name else f'{shape_info["label"]} ({el_id})'
				prohibited_items.append({
					"name": display_name,
					"exists": False,
					"type": "check",
					"detail": shape_info.get("suggestion", ""),
				})
	if prohibited_items:
		categories.append({
			"label": "Prohibited Shapes",
			"icon": "ban",
			"items": prohibited_items,
		})

	if model_name:
		call_activity_ref_items = _check_call_activity_references(model_name)
		if call_activity_ref_items:
			categories.append({
				"label": "Call Activity References",
				"icon": "link-2",
				"items": call_activity_ref_items,
			})

	if model_name:
		eval_suite_items = []
		gating_suites = frappe.get_all(
			"AI Eval Suite",
			filters={"process_model": model_name, "gate_deployment": 1},
			fields=["name", "title"],
		)
		for suite in gating_suites:
			suite_title = suite.title or suite.name
			latest_runs = frappe.get_all(
				"AI Eval Run",
				filters={"suite": suite.name},
				fields=["name", "status", "started_at"],
				order_by="started_at desc",
				limit_page_length=1,
			)
			if not latest_runs:
				eval_suite_items.append({
					"name": suite_title,
					"exists": True,
					"type": "warning",
					"detail": _("Has never been run. Consider running it before deploying."),
				})
			elif latest_runs[0].status == "Failed":
				run_date = frappe.utils.formatdate(latest_runs[0].started_at)
				eval_suite_items.append({
					"name": suite_title,
					"exists": True,
					"type": "warning",
					"detail": _("Failed - last run on {0}. Consider re-running the suite before deploying.").format(run_date),
				})
			else:
				eval_suite_items.append({
					"name": suite_title,
					"exists": True,
					"type": "check",
					"detail": _("Last eval run: {0}").format(latest_runs[0].status),
				})
		if eval_suite_items:
			categories.append({
				"label": "Eval Suites",
				"icon": "flask-conical",
				"items": eval_suite_items,
			})

	# Controller code runs before the BPMN hooks, so warn until its removal is confirmed on Production.
	if model_name:
		removal_status = None
		process_name = frappe.db.get_value("BPMN Process Model", model_name, "process_name")
		if process_name:
			removal_status = frappe.db.get_value(
				"Process", process_name, "backend_code_removal_status"
			)
		if removal_status and removal_status not in ("Removed on Production",):
			backend_items = [{
				"name": _("Backend code removal not confirmed"),
				"exists": True,
				"type": "warning",
				"detail": _(
					"Status is '{0}' - old controller code may still run "
					"alongside BPMN. Confirm removal on production before "
					"go-live, or set status to 'Removed on Production' if "
					"validation must intentionally stay in code."
				).format(removal_status),
			}]

			for dt in sorted(refs["context_doctypes"]):
				if not frappe.db.exists("DocType", dt):
					continue
				overrides = _controller_lifecycle_overrides(dt)
				if overrides:
					backend_items.append({
						"name": dt,
						"exists": True,
						"type": "warning",
						"detail": _(
							"Controller still defines: {0}. This code runs "
							"before/around the BPMN hooks. Remove it, or set "
							"status to 'Removed on Production' if intentional."
						).format(", ".join(overrides)),
					})

			categories.append({
				"label": "Backend Code Removal",
				"icon": "code-2",
				"items": backend_items,
			})

	connector_tool_gaps = connector_tools_without_result_variable(xml_content)
	if connector_tool_gaps:
		categories.append({
			"label": "Connector Tools",
			"icon": "plug",
			"items": [{
				"name": g["shape"] or g["bpmn_id"],
				"exists": True,
				"type": "warning",
				"detail": _(
					"No Result Variable. The {0} connector will run and its side effect will "
					"happen, but nothing is returned to the '{1}' agent - which is "
					"indistinguishable from a broken integration. Set a Result Variable on "
					"this shape."
				).format(g["connector"] or _("connector"), g["agent"]),
			} for g in connector_tool_gaps],
		})

	email_category = _email_settings_category(xml_content, refs["root"])
	if email_category:
		categories.append(email_category)

	script_category = _empty_script_category(refs["root"])
	if script_category:
		categories.append(script_category)

	sender_category = _notification_sender_category(xml_content, refs["root"])
	if sender_category:
		categories.append(sender_category)

	user_task_category = _user_task_config_category(xml_content)
	if user_task_category:
		categories.append(user_task_category)

	total_checked = 0
	total_missing = 0
	total_warnings = 0

	for cat in categories:
		for item in cat["items"]:
			total_checked += 1
			if item["type"] == "check" and not item["exists"]:
				total_missing += 1
			elif item["type"] in ("warning", "call_activity_ref"):
				total_warnings += 1

	return {
		"categories": categories,
		"total_checked": total_checked,
		"total_missing": total_missing,
		"total_warnings": total_warnings,
		"is_executable": is_executable,
		"all_ready": total_missing == 0 and is_executable,
	}


def _user_task_config_category(xml_content: str) -> dict | None:
	"""The User Task Configuration readiness category, one missing check per gap, or None."""
	from one_bpmn.processa_engine.compiler.checks import user_task_config_gaps

	gaps = user_task_config_gaps(xml_content)
	if not gaps:
		return None
	items = [
		{"name": message, "exists": False, "type": "check", "detail": _("Set it in the properties panel of the task.")}
		for _bpmn_id, message in gaps
	]
	return {"label": _("User Task Configuration"), "icon": "user-check", "items": items}


def _email_settings_category(xml_content: str, root) -> dict | None:
	"""The Email Settings readiness category, one warning per email step with empty settings, or None."""
	from one_bpmn.processa_engine.compiler.deploy_warnings import email_setting_gaps
	from one_bpmn.processa_engine.compiler.extensions import extract_service_task_config, extract_user_task_config

	email_gaps = email_setting_gaps(extract_service_task_config(xml_content), extract_user_task_config(xml_content))
	if not email_gaps:
		return None
	names = _step_names(root, [bpmn_id for bpmn_id, _missing in email_gaps])
	items = [
		{
			"name": name,
			"exists": True,
			"type": "warning",
			"detail": _("Sends an email with no {0}. Fill these in so the email goes out as intended.").format(
				", ".join(missing)
			),
		}
		for name, (_bpmn_id, missing) in zip(names, email_gaps)
	]
	return {"label": _("Email Settings"), "icon": "mail-warning", "items": items}


def _notification_sender_category(xml_content: str, root) -> dict | None:
	"""The Notification Sender readiness category for a Production site, or None."""
	from one_bpmn.processa_engine.compiler.deploy_warnings import notification_sender_gaps
	from one_bpmn.processa_engine.compiler.extensions import extract_service_task_config, extract_user_task_config

	expected, gaps = notification_sender_gaps(
		extract_service_task_config(xml_content), extract_user_task_config(xml_content)
	)
	if not gaps:
		return None
	items = [
		{
			"name": name,
			"exists": True,
			"type": "warning",
			"detail": _("Sends from {0}. On this Production site notifications should send from {1}.").format(
				sender, expected
			),
		}
		for name, (_bpmn_id, sender) in zip(_step_names(root, [bpmn_id for bpmn_id, _sender in gaps]), gaps)
	]
	return {"label": _("Notification Sender"), "icon": "mail-warning", "items": items}


def _empty_script_category(root) -> dict | None:
	"""The Script Tasks readiness category, one warning per Script Task with no script, or None."""
	from one_bpmn.processa_engine.compiler.deploy_warnings import empty_script_tasks

	empty = empty_script_tasks(root)
	if not empty:
		return None
	items = [
		{
			"name": name,
			"exists": True,
			"type": "warning",
			"detail": _("Has no script, so it does nothing when it runs. Pick a Server Script or write one."),
		}
		for name in _step_names(root, empty)
	]
	return {"label": _("Script Tasks"), "icon": "file-warning", "items": items}


def _step_names(root, bpmn_ids: list) -> list:
	"""Each step's name as drawn on the canvas, with its id added when two steps share a name."""
	drawn = {el.get("id"): (el.get("name") or "").strip() for el in root.iter() if el.get("id")}
	seen = set()
	names = []
	for bpmn_id in bpmn_ids:
		name = drawn.get(bpmn_id) or bpmn_id
		if name in seen:
			name = f"{name} ({bpmn_id})"
		seen.add(name)
		names.append(name)
	return names


def _controller_lifecycle_overrides(doctype: str) -> list:
	"""Inspect a doctype's controller class for native lifecycle methods."""
	LIFECYCLE_METHODS = (
		"validate",
	)
	from frappe.model.base_document import get_controller

	try:
		controller = get_controller(doctype)
	except Exception:
		return []
	if controller is None:
		return []
	own = getattr(controller, "__dict__", {})
	return [m for m in LIFECYCLE_METHODS if m in own]


def _check_call_activity_references(model_name: str) -> list:
	"""Detect Call Activities in other models that reference process models which will be disabled when
	``model_name`` is deployed."""
	model = frappe.db.get_value(
		"BPMN Process Model",
		model_name,
		["name", "process_name", "process_id"],
		as_dict=True,
	)
	if not model or not model.process_name:
		return []

	siblings = frappe.get_all(
		"BPMN Process Model",
		filters={
			"process_name": model.process_name,
			"is_active": 1,
			"name": ["!=", model_name],
		},
		fields=["name", "process_id", "title"],
	)
	if not siblings:
		return []

	disabled_process_ids = {}
	for s in siblings:
		if s.process_id:
			disabled_process_ids[s.process_id] = s

	if not disabled_process_ids:
		return []

	sibling_names = [s.name for s in siblings] + [model_name]
	other_models = frappe.get_all(
		"BPMN Process Model",
		filters={
			"name": ["not in", sibling_names],
			"bpmn_xml": ["is", "set"],
		},
		fields=["name", "title", "bpmn_xml", "process_name"],
	)

	items = []
	for other in other_models:
		if not other.bpmn_xml:
			continue

		call_refs = extract_call_activity_refs(other.bpmn_xml)
		for ref in call_refs:
			if ref["called_element"] in disabled_process_ids:
				disabled_sibling = disabled_process_ids[ref["called_element"]]
				items.append({
					"name": _(
						"'{0}' in {1} -> references {2} (will be disabled)"
					).format(ref["name"], other.title, disabled_sibling.title),
					"exists": True,
					"type": "call_activity_ref",
					"detail": _(
						"Update calledElement from {0} to {1}?"
					).format(ref["called_element"], model.process_id),
					"source_model": other.name,
					"source_element_id": ref["bpmn_id"],
					"old_process_id": ref["called_element"],
					"new_process_id": model.process_id,
				})

	return items


def _extract_ai_shapes(xml_content: str) -> list:
	"""AI Agent Task / AI Task Selector shapes with their linked configuration [{"id", "label", "config"}].
	Empty list on unparsable XML - the well-formedness check elsewhere owns that failure."""
	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"
	try:
		parser = ET.XMLParser(resolve_entities=False, no_network=True)
		root = ET.fromstring(xml_content.strip().encode("utf-8"), parser=parser)
	except Exception:
		return []
	shapes = []
	for tag in ("serviceTask", "adHocSubProcess"):
		for el in root.iter(f"{{{BPMN_NS}}}{tag}"):
			if el.get(f"{{{SPIFF_NS}}}serviceType") in ("ai_agent", "ai_task_selector"):
				shapes.append({
					"id": el.get("id") or "",
					"label": el.get("name") or "",
					"config": (el.get(f"{{{SPIFF_NS}}}aiAgentConfig") or "").strip(),
				})
	return shapes


def connector_tools_without_result_variable(xml_content: str) -> list:
	"""Connector tool shapes that will run but can return nothing to the agent.
	Only connectors inside a Tools sub-process an AI Agent Task uses count, and not ones that answer out of band."""
	import xml.etree.ElementTree as _ET

	from one_bpmn.agents.shape_tools import ANSWERS_OUT_OF_BAND

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	try:
		root = _ET.fromstring(xml_content.strip().encode("utf-8"))
	except Exception:
		return []  # unparseable XML is already reported by the caller's own checks

	adhocs = {el.get("id"): el for el in root.iter(f"{{{BPMN_NS}}}adHocSubProcess") if el.get("id")}
	if not adhocs:
		return []

	findings = []
	for st in root.iter(f"{{{BPMN_NS}}}serviceTask"):
		if st.get(f"{{{SPIFF_NS}}}serviceType") != "ai_agent":
			continue
		adhoc = adhocs.get((st.get(f"{{{SPIFF_NS}}}aiToolsAdhoc") or "").strip())
		if adhoc is None:
			continue  # missing reference is reported by the compiler's own check
		agent_label = (st.get("name") or st.get("id") or "").strip()
		for child in list(adhoc):
			if child.tag.split("}")[-1] != "serviceTask":
				continue
			if child.get(f"{{{SPIFF_NS}}}serviceType") != "connector":
				continue
			if (child.get(f"{{{SPIFF_NS}}}resultVariable") or "").strip():
				continue
			connector = (child.get(f"{{{SPIFF_NS}}}connectorId") or "").strip()
			operation = (child.get(f"{{{SPIFF_NS}}}operation") or "").strip()
			if connector in ANSWERS_OUT_OF_BAND:
				continue
			findings.append({
				"shape": (child.get("name") or child.get("id") or "").strip(),
				"bpmn_id": child.get("id") or "",
				"agent": agent_label,
				"connector": f"{connector}/{operation}".strip("/"),
			})
	return findings

