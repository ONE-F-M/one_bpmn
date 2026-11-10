# Copyright (c) 2026, one-fm and contributors
"""Activation of a deployed model and its siblings, and the Server Scripts each one runs."""

import json
import xml.etree.ElementTree as _ET

import frappe
from frappe import _

from one_bpmn.processa_engine.legacy_migration import OPEN_INSTANCE_STATUSES


def activate_deployed_model(model, script_extensions: dict) -> list:
	"""Activate the model, deactivate its siblings and enable or disable the Server Scripts each runs; the caller saves.

	Returns the scripts left disabled because they await a System Manager's review.
	"""

	model.is_active = 1
	model.deployed_at = frappe.utils.now()
	model.deployed_by = frappe.session.user

	# The compiled spec also holds the scripts a Call Activity embeds.
	active_scripts = _get_linked_server_scripts(model.serialized_spec)
	for cfg in (script_extensions or {}).values():
		if cfg.get("serverScript"):
			active_scripts.add(cfg["serverScript"])

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

	max_sibling_version = max((s.version or 0 for s in siblings), default=0)
	model.version = max_sibling_version + 1

	if siblings:
		sibling_scripts = set()
		for s in siblings:
			frappe.db.set_value("BPMN Process Model", s.name, "is_active", 0)
			# Open instances still run the old map's scripts, so those are not disabled.
			if not frappe.db.exists(
				"BPMN Process Instance", {"process_model": s.name, "status": ["in", OPEN_INSTANCE_STATUSES]}
			):
				sibling_scripts |= _get_linked_server_scripts(s.serialized_spec)

		still_used = _scripts_used_by_active_models({model.name, *(s.name for s in siblings)})
		for script_name in (sibling_scripts - active_scripts - still_used):
			if frappe.db.exists("Server Script", script_name):
				frappe.db.set_value("Server Script", script_name, "disabled", 1)

	pending_review = []
	for script_name in active_scripts:
		if not frappe.db.exists("Server Script", script_name):
			continue
		if frappe.db.get_value("Server Script", script_name, "processa_pending_review"):
			pending_review.append(script_name)
		else:
			frappe.db.set_value("Server Script", script_name, "disabled", 0)
	return sorted(pending_review)


def disable_model(model) -> dict:
	"""Deactivate a deployed model the caller may write, clear its specs and disable the Server Scripts only it runs."""
	model_name = model.name
	if not model.is_active:
		frappe.throw(
			_("Process map '{0}' is already inactive.").format(model_name),
			title=_("Already Disabled"),
		)

	model.is_active = 0

	linked_scripts = _get_linked_server_scripts(model.serialized_spec)
	model.serialized_spec = None
	model.subprocess_specs = None

	for script_name in linked_scripts - _scripts_used_by_active_models({model_name}):
		if frappe.db.exists("Server Script", script_name):
			frappe.db.set_value("Server Script", script_name, "disabled", 1)

	running_count = frappe.db.count(
		"BPMN Process Instance",
		filters={
			"process_model": model_name,
			"status": ["in", ["Active"]],
		},
	)

	model.flags.skip_editability_check = True
	model.save(ignore_permissions=True)  # the caller checked write permission

	return {
		"success": True,
		"model": model_name,
		"running_instances": running_count,
	}


def activate_non_executable(model) -> dict:
	"""Mark a non-executable process model Active; saving it deactivates its siblings."""
	_refuse_executable(model)
	if model.is_active:
		frappe.throw(_("Process model '{0}' is already active.").format(model.name))

	model.is_active = 1
	model.flags.skip_editability_check = True
	model.save()

	return {"success": True, "model": model.name}


def deactivate_non_executable(model) -> dict:
	"""Mark a non-executable process model Inactive."""
	_refuse_executable(model)
	if not model.is_active:
		frappe.throw(_("Process model '{0}' is already inactive.").format(model.name))

	model.is_active = 0
	model.flags.skip_editability_check = True
	model.save()

	return {"success": True, "model": model.name}


def _refuse_executable(model) -> None:
	"""Throw if the model's process is marked executable; Deploy and Disable handle those."""
	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"

	root = _ET.fromstring(model.bpmn_xml.strip().encode("utf-8"))
	for process in root.iter(f"{{{BPMN_NS}}}process"):
		if process.get("isExecutable", "false").strip().lower() == "true":
			frappe.throw(
				_("Process model '{0}' is executable. Use Deploy and Disable instead.").format(model.name),
				title=_("Process Executable"),
			)


def _scripts_used_by_active_models(exclude: set) -> set:
	"""Server Scripts some other active map still runs, Call Activities included."""
	used = set()
	rows = frappe.get_all(
		"BPMN Process Model",
		filters={"is_active": 1, "name": ["not in", sorted(exclude)]},
		fields=["serialized_spec"],
	)
	for row in rows:
		used |= _get_linked_server_scripts(row.serialized_spec)
	return used


def _get_linked_server_scripts(spec_json: str) -> set:
	"""The Server Script names the Script Tasks of a serialized spec run."""
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
