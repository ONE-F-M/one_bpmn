# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
import logging
from SpiffWorkflow.bpmn.parser.ValidationException import ValidationException
from SpiffWorkflow.bpmn import BpmnWorkflow
from SpiffWorkflow.bpmn.parser.BpmnParser import BpmnParser
from SpiffWorkflow.bpmn.script_engine import PythonScriptEngine, TaskDataEnvironment
from one_bpmn.one_bpmn.safe_frappe import get_safe_frappe
from .instance import Instance

logger = logging.getLogger('spiff_engine')

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
			"_": frappe._,
		})
		super().__init__(environment=env, **kwargs)

	def execute(self, task, script, external_context=None):
		"""
		Inject 'data' into the execution context temporarily so scripts can 
		use data['field'] = value. We pass it via external_context so the
		environment handles its cleanup after execution, avoiding circular
		references in task.data.
		"""
		ext_ctx = external_context or {}
		if "data" not in ext_ctx:
			ext_ctx["data"] = task.data
		
		return super().execute(task, script, ext_ctx)

def get_script_engine():
	"""
	Returns an instance of the custom SpiffWorkflow script engine.
	"""
	return SpiffScriptEngine()

class BpmnEngine:
	"""
	Custom BPMN Engine for Frappe integration.
	"""
	def __init__(self, parser=None, serializer=None, instance_cls=None):
		self.parser = parser or BpmnParser()
		self.serializer = serializer # Should be a Frappe-aware serializer
		self._script_engine = get_script_engine()
		self.instance_cls = instance_cls or Instance

	def add_files(self, bpmn_files):
		self.parser.add_bpmn_files(bpmn_files)

	def start_workflow(self, process_id, bpmn_xml=None):
		"""
		Starts a workflow based on a process ID and optionally XML content.
		"""
		if bpmn_xml:
			if isinstance(bpmn_xml, str):
				bpmn_xml = bpmn_xml.encode("utf-8")
			self.parser.add_bpmn_str(bpmn_xml)
		
		# If process_id is not found, try to get the first executable process from the parser
		available_processes = self.parser.get_process_ids()
		if process_id not in available_processes and available_processes:
			process_id = available_processes[0]

		spec = self.parser.get_spec(process_id)
		# For simple execution, we might not have a full serializer persistence yet
		wf = BpmnWorkflow(spec, script_engine=self._script_engine)
		
		# In a real app, wf_id would come from a database record
		import uuid
		wf_id = str(uuid.uuid4())
		
		instance = self.instance_cls(wf_id, wf)
		instance.run_all()
		return instance

	def get_workflow_from_doctype(self, model_name: str):
		"""
		Loads and starts a workflow from a 'BPMN Process Model' doctype.
		"""
		doc = frappe.get_doc("BPMN Process Model", model_name)
		return self.start_workflow(doc.process_id or "Process_1", bpmn_xml=doc.bpmn_xml)
