# Copyright (c) 2026, one-fm and contributors
"""import_script: reuse the functions of a library Server Script on the same process."""

from collections import namedtuple
from types import FunctionType

import frappe
from frappe import _

from processa.processa_engine.engine.script_engine import check_server_script


def make_import_script(instance, script_task_extensions: dict):
	"""The import_script callable for one engine run; each library runs at most once."""
	process_scripts = {cfg.get("serverScript") for cfg in script_task_extensions.values()}
	loaded = {}

	def import_script(script_name: str):
		if script_name not in loaded:
			loaded[script_name] = _load_library(instance, process_scripts, script_name)
		return loaded[script_name]

	return import_script


def _load_library(instance, process_scripts: set, script_name: str):
	if script_name not in process_scripts:
		process_name = frappe.db.get_value("BPMN Process Model", instance.process_model, "process_name")
		frappe.throw(_("Script '{0}' is not part of process '{1}'").format(script_name, process_name))
	if not frappe.db.exists("Server Script", script_name) or frappe.db.get_value(
		"Server Script", script_name, "disabled"
	):
		frappe.throw(_("Library script '{0}' is missing or disabled").format(script_name))

	script_doc = frappe.get_doc("Server Script", script_name)
	check_server_script(script_doc)

	namespace = {"frappe": frappe, "__builtins__": __builtins__, "import_script": _refuse_nested_import}
	exec(script_doc.script, namespace)

	functions = {
		name: value
		for name, value in namespace.items()
		if isinstance(value, FunctionType) and value is not _refuse_nested_import and not name.startswith("_")
	}
	return namedtuple("Library", functions)(**functions)


def _refuse_nested_import(script_name: str):
	frappe.throw(_("A library script cannot import another script ('{0}')").format(script_name))
