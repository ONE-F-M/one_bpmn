# Copyright (c) 2026, one-fm and contributors
"""The compile step: parse a model's diagram, run the deploy checks, embed the shape config and activate it."""

import json

import frappe
from frappe import _

from one_bpmn.processa_engine.compiler.agent_tools import resolve_ai_agent_tool_shapes
from one_bpmn.processa_engine.compiler.ai_checks import (
	lint_ai_provider_config,
	validate_adhoc_selector_pool,
	validate_adhoc_structure,
	validate_ai_agent_tools,
	validate_ai_max_tokens,
	validate_ai_tool_contract,
)
from one_bpmn.processa_engine.compiler.called_processes import resolve_called_process_xml
from one_bpmn.processa_engine.compiler.checks import (
	enforce_eval_pass_rate,
	validate_notify_assignee_account,
	validate_prohibited_shapes,
	validate_user_task_config,
	validate_workflow_state_field,
)
from one_bpmn.processa_engine.compiler.deploy_warnings import (
	check_ai_tasks_have_a_user_prompt,
	check_connector_tools_can_answer,
	check_email_settings,
	check_eval_suite_gating,
	check_notification_senders,
	check_script_tasks_have_a_script,
	check_scripts_pending_review,
	check_shape_config_drift,
)
from one_bpmn.processa_engine.compiler.extensions import (
	extract_adhoc_selector_config,
	extract_script_task_config,
	extract_service_task_config,
	extract_user_task_config,
)
from one_bpmn.processa_engine.compiler.lifecycle import activate_deployed_model
from one_bpmn.processa_engine.compiler.prepare import (
	drop_stale_flow_node_refs,
	ensure_script_task_inline_scripts,
	extract_business_rule_task_decisions,
	extract_dmn_decision_id,
	sanitize_bpmn_xml,
)
from one_bpmn.processa_engine.compiler.start_events import populate_start_events
from one_bpmn.processa_engine.compiler.timers import (
	detach_start_timer_definitions,
	validate_start_event_timers,
	validate_timer_granularity,
)
from one_bpmn.processa_engine.compiler.turn_store import validate_turn_store_contract


def compile_model(model) -> dict:
	"""Compile a BPMN Process Model the caller may write: store its spec, run the deploy checks and activate it."""
	model_name = model.name

	if not model.bpmn_xml:
		frappe.throw(_("No BPMN XML found in process model '{0}'").format(model_name))

	import xml.etree.ElementTree as _ET

	from one_bpmn.processa_engine.doctype.bpmn_process_model.bpmn_process_model import swap_process_id

	_bpmn_ns = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	try:
		_root = _ET.fromstring(model.bpmn_xml.strip().encode("utf-8"))
		_process_el = _root.find(f"{{{_bpmn_ns}}}process") or _root.find("process")
		if _process_el is not None:
			xml_process_id = _process_el.get("id", "").strip()
			if xml_process_id and not model.process_id:
				model.process_id = xml_process_id
			elif xml_process_id and xml_process_id != model.process_id:
				model.bpmn_xml = swap_process_id(model.bpmn_xml, xml_process_id, model.process_id)

			is_executable = _process_el.get("isExecutable", "false").strip().lower()
			if is_executable != "true":
				frappe.throw(
					_("Cannot deploy '{0}': the process is not marked as Executable. "
					  "Open the diagram, select the process (click the pool header or empty canvas), "
					  "and enable the 'Executable' checkbox in the properties panel.").format(model_name),
					title=_("Process Not Executable"),
				)
	except frappe.ValidationError:
		raise
	except Exception:
		pass  # XML parse errors will surface properly in parse_bpmn() below

	if not model.process_id:
		frappe.throw(
			_("No process_id found in the BPMN XML for '{0}'. Save the Process Map first.").format(model_name)
		)

	from one_bpmn.processa_engine import engine as bpmn_engine

	sanitized_xml = sanitize_bpmn_xml(model.bpmn_xml)

	sanitized_xml = ensure_script_task_inline_scripts(sanitized_xml)

	cleaned_xml = drop_stale_flow_node_refs(model.bpmn_xml)
	if cleaned_xml != model.bpmn_xml:
		model.bpmn_xml = cleaned_xml
	sanitized_xml = drop_stale_flow_node_refs(sanitized_xml)

	brt_decision_ids = extract_business_rule_task_decisions(sanitized_xml)
	dmn_xml_list = []

	if brt_decision_ids:
		available_dmn = {}
		for row in model.decision_tables or []:
			if row.dmn_xml and row.dmn_xml.strip():
				dmn_id = extract_dmn_decision_id(row.dmn_xml)
				if dmn_id:
					available_dmn[dmn_id] = row.dmn_xml

		for decision_id in brt_decision_ids:
			if decision_id in available_dmn:
				dmn_xml_list.append(available_dmn[decision_id])

		found_ids = set(available_dmn.keys())
		missing = set(brt_decision_ids) - found_ids
		if missing:
			frappe.throw(
				_(
					"Cannot deploy: Business Rule Tasks reference decisions "
					"that have no DMN XML in the Decision Tables: {0}.\n\n"
					"Open each Business Rule Task in the diagram and create a "
					"Decision Table using the DMN modeler."
				).format(", ".join(sorted(missing))),
				title=_("Missing Decision Tables"),
			)

	sanitized_xml, called_xml_list = resolve_called_process_xml(sanitized_xml, model_name)

	try:
		spec_dict, sp_dict = bpmn_engine.parse_bpmn(
			bpmn_xml=detach_start_timer_definitions(sanitized_xml),
			process_id=model.process_id,
			dmn_xml_list=dmn_xml_list,
			called_xml_list=called_xml_list,
		)
	except Exception as exc:
		frappe.log_error(title="BPMN compile failed", message=frappe.get_traceback())
		frappe.throw(_("Failed to compile BPMN for '{0}': {1}").format(model_name, str(exc)))

	model.serialized_spec = json.dumps(spec_dict)
	model.subprocess_specs = json.dumps(sp_dict)

	spec_data = json.loads(model.serialized_spec)

	called_service_extensions: dict = {}
	called_script_extensions: dict = {}
	for called_xml in called_xml_list:
		called_service_extensions.update(extract_service_task_config(called_xml))
		called_service_extensions.update(extract_adhoc_selector_config(called_xml))
		resolve_ai_agent_tool_shapes(called_xml, called_service_extensions)
		called_script_extensions.update(extract_script_task_config(called_xml))

	service_extensions = extract_service_task_config(sanitized_xml)
	service_extensions.update(extract_adhoc_selector_config(sanitized_xml))
	resolve_ai_agent_tool_shapes(sanitized_xml, service_extensions)
	if service_extensions or called_service_extensions:
		# On an id collision the document being compiled wins over a called one.
		spec_data["service_task_extensions"] = {
			**called_service_extensions,
			**service_extensions,
		}
	lint_ai_provider_config(sanitized_xml, service_extensions)
	validate_adhoc_structure(sanitized_xml)
	validate_adhoc_selector_pool(sanitized_xml, model_name)
	validate_ai_agent_tools(sanitized_xml, service_extensions)
	validate_ai_max_tokens(service_extensions)
	validate_ai_tool_contract(service_extensions)

	deploy_warnings = check_eval_suite_gating(model_name)
	deploy_warnings.extend(check_ai_tasks_have_a_user_prompt(spec_data))
	deploy_warnings.extend(validate_turn_store_contract(sanitized_xml, service_extensions))
	deploy_warnings.extend(check_connector_tools_can_answer(sanitized_xml))
	deploy_warnings.extend(check_shape_config_drift(service_extensions))

	script_extensions = extract_script_task_config(sanitized_xml)
	if script_extensions or called_script_extensions:
		spec_data["script_task_extensions"] = {
			**called_script_extensions,
			**script_extensions,
		}

	from one_bpmn.ai_agent_security.code_checks.script_gate import validate_process_model_scripts

	validate_process_model_scripts(sanitized_xml)

	user_extensions = extract_user_task_config(sanitized_xml)
	if user_extensions:
		spec_data["user_task_extensions"] = user_extensions
	deploy_warnings.extend(check_email_settings(service_extensions, user_extensions))
	deploy_warnings.extend(check_notification_senders(service_extensions, user_extensions))
	deploy_warnings.extend(check_script_tasks_have_a_script(model.bpmn_xml))

	model.serialized_spec = json.dumps(spec_data)

	validate_timer_granularity(sanitized_xml)
	validate_start_event_timers(sanitized_xml)

	validate_prohibited_shapes(sanitized_xml)
	validate_user_task_config(sanitized_xml)

	validate_notify_assignee_account(sanitized_xml)

	populate_start_events(model, sanitized_xml)

	validate_workflow_state_field(model, service_extensions)

	enforce_eval_pass_rate(model_name)

	deploy_warnings.extend(check_scripts_pending_review(activate_deployed_model(model, script_extensions)))

	model.flags.skip_editability_check = True
	model.flags.skip_script_security_check = True
	model.save(ignore_permissions=True)  # the caller checked write permission

	from one_bpmn.processa_engine.triggers import send_process_model_deployed_message

	send_process_model_deployed_message(model)

	removal_status = None
	if model.get("process_name"):
		removal_status = frappe.db.get_value(
			"Process", model.process_name, "backend_code_removal_status"
		)
	if removal_status and removal_status not in ("Removed on Production",):
		deploy_warnings.append({
			"label": "Backend Code Removal",
			"icon": "code-2",
			"type": "warning",
			"detail": _("Backend code removal not yet confirmed on production - "
			            "confirm before go-live"),
		})

	_recompile_callers_of(model.process_id, model_name)

	result = {
		"success": True,
		"model": model_name,
		"version": model.version,
		"subprocess_count": len(sp_dict),
	}

	if deploy_warnings:
		result["warnings"] = deploy_warnings

	return result


def _recompile_callers_of(process_id: str, model_name: str, _seen: set | None = None) -> None:
	"""Recompile every active map whose Call Activity calls this one; a caller that fails is logged and skipped."""
	if not process_id:
		return
	seen = _seen if _seen is not None else set()
	if model_name in seen:
		return
	seen.add(model_name)

	for caller in frappe.get_all(
		"BPMN Process Model",
		filters={"name": ["!=", model_name], "is_active": 1},
		or_filters=[
			["bpmn_xml", "like", f"%{needle}%"] for needle in _caller_needles(process_id, model_name)
		],
		fields=["name", "process_id"],
	):
		if caller.name in seen:
			continue
		try:
			caller_model = frappe.get_doc("BPMN Process Model", caller.name)
			caller_model.check_permission("write")
			compile_model(caller_model)
			frappe.logger("one_bpmn").info(
				f"Recompiled '{caller.name}' because it calls '{model_name}'"
			)
		except Exception:
			frappe.log_error(
				title="Call Activity: caller could not be recompiled",
				message=(
					f"'{caller.name}' calls '{model_name}' and embeds a copy of it, but "
					f"recompiling it failed - it is still running the previous copy.\n\n"
					+ frappe.get_traceback()
				),
			)
		_recompile_callers_of(caller.process_id, caller.name, seen)


def _caller_needles(process_id: str, model_name: str) -> list:
	"""Text a caller's XML holds when it calls this map: its Process, or the process id of any version of it."""
	from xml.sax.saxutils import quoteattr

	process = frappe.db.get_value("BPMN Process Model", model_name, "process_name")
	if not process:
		return [f'calledElement="{process_id}"']
	process_ids = set(
		frappe.get_all("BPMN Process Model", filters={"process_name": process}, pluck="process_id")
	)
	process_ids.add(process_id)
	return [f"calledProcess={quoteattr(process)}"] + [f'calledElement="{pid}"' for pid in process_ids if pid]
