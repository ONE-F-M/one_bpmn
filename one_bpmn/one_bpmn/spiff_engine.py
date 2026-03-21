# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
from SpiffWorkflow.bpmn.script_engine import PythonScriptEngine, TaskDataEnvironment
from one_bpmn.one_bpmn.safe_frappe import get_safe_frappe

class SpiffScriptEngine(PythonScriptEngine):
	"""
	Custom SpiffWorkflow Script Engine for Frappe.
	"""
	def __init__(self, **kwargs):
		# Initialize with a TaskDataEnvironment that includes our safe frappe proxy
		safe_frappe = get_safe_frappe()
		env = TaskDataEnvironment({
			"frappe": safe_frappe,
			"get_doc": safe_frappe.get_doc,
			"get_list": safe_frappe.get_list,
			"get_value": safe_frappe.get_value,
		})
		super().__init__(environment=env, **kwargs)

def get_script_engine():
	"""
	Returns an instance of the custom SpiffWorkflow script engine.
	"""
	return SpiffScriptEngine()
