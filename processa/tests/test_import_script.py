# Copyright (c) 2026, one-fm and contributors
"""import_script loads a library Server Script on the same process, in script tasks and agent tools."""

from __future__ import annotations

import json
from itertools import pairwise
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_skills.tools import shape_tools
from processa.api.deploy import compile_process_model
from processa.processa_engine.engine import _make_script_engine, script_imports

LIBRARY = "Import Test: Lib Replies"
CALLER = "Import Test: Finalize"
OUTSIDER = "Import Test: Not On Map"
PROCESS = "Import Script Test Process"

LIBRARY_BODY = """
def strip_fences(text):
	s = (text or "").strip()
	if s.startswith("```"):
		s = s.split("\\n", 1)[-1]
	if s.endswith("```"):
		s = s[: s.rfind("```")].strip()
	return s
"""

CALLER_BODY = f"""
lib = import_script("{LIBRARY}")
result["clean"] = lib.strip_fences(task_data.get("raw"))
"""


class _FakeTaskSpec:
	bpmn_id = "finalize"
	name = "finalize"


class _FakeTask:
	def __init__(self, data):
		self.data = data
		self.task_spec = _FakeTaskSpec()


def _extensions(*script_names):
	return {f"task_{i}": {"serverScript": name} for i, name in enumerate(script_names)}


class TestImportScript(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._script(LIBRARY, LIBRARY_BODY)
		self._script(CALLER, CALLER_BODY)
		self.model = self._process_model()
		self.instance = frappe._dict(
			process_model=self.model,
			context_doctype="",
			context_docname="",
			_script_task_extensions=_extensions(LIBRARY, CALLER),
		)

	def _script(self, name, body, disabled=0):
		if frappe.db.exists("Server Script", name):
			frappe.delete_doc("Server Script", name, force=True, ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": name,
				"script_type": "API",
				"api_method": frappe.scrub(name).replace(":", ""),
				"script": body,
				"disabled": disabled,
			}
		).insert(ignore_permissions=True)
		return name

	def _process_model(self):
		if not frappe.db.exists("Process", PROCESS):
			frappe.get_doc(
				{
					"doctype": "Process",
					"process_name": PROCESS,
					"description": PROCESS,
					"process_owner": "Administrator",
				}
			).insert(ignore_permissions=True)
		name = "Import Script Test Map"
		if frappe.db.exists("BPMN Process Model", name):
			frappe.delete_doc("BPMN Process Model", name, force=1, ignore_permissions=True)
		doc = frappe.new_doc("BPMN Process Model")
		doc.update({"name": name, "title": name, "process_id": "import_script_test", "version": 1})
		doc.bpmn_xml = _map_xml("import_script_test", [])
		doc.insert(ignore_permissions=True)
		frappe.db.set_value("BPMN Process Model", name, "process_name", PROCESS)
		return name

	def _run_task(self, script_name, data, extensions=None):
		engine = _make_script_engine(
			script_task_extensions=extensions or self.instance._script_task_extensions,
			instance=self.instance,
		)
		task = _FakeTask(data)
		engine._run_frappe_server_script(script_name, task)
		return task.data

	def test_script_task_calls_a_library_function(self):
		data = self._run_task(CALLER, {"raw": "```python\nx = 1\n```"})
		self.assertEqual(data["clean"], "x = 1")

	def test_agent_tool_calls_a_library_function(self):
		task = shape_tools._synthetic_task("finalize", {"raw": "```\nhello\n```"})
		shape_tools._run_server_script(self.instance, CALLER, task, "finalize")
		self.assertEqual(task.data["clean"], "hello")

	def test_script_not_on_the_process_is_refused(self):
		self._script(OUTSIDER, LIBRARY_BODY)
		self._script(CALLER, f'import_script("{OUTSIDER}")\nresult["ran"] = True')
		with self.assertRaises(frappe.ValidationError) as caught:
			self._run_task(CALLER, {})
		self.assertIn(f"Script '{OUTSIDER}' is not part of process '{PROCESS}'", str(caught.exception))

	def test_disabled_library_fails_the_step(self):
		self._script(LIBRARY, LIBRARY_BODY, disabled=1)
		data = {"raw": "x"}
		with self.assertRaises(frappe.ValidationError) as caught:
			self._run_task(CALLER, data)
		self.assertIn(LIBRARY, str(caught.exception))
		self.assertNotIn("clean", data)

	def test_missing_library_fails_the_step(self):
		frappe.delete_doc("Server Script", LIBRARY, force=True, ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError) as caught:
			self._run_task(CALLER, {"raw": "x"})
		self.assertIn(LIBRARY, str(caught.exception))

	def test_library_sees_only_frappe(self):
		self._script(LIBRARY, 'ROWS = task_data.get("rows")\n')
		with self.assertRaises(NameError):
			self._run_task(CALLER, {"raw": "x"})

	def test_library_cannot_import_another_script(self):
		self._script(LIBRARY, f'other = import_script("{CALLER}")\n')
		with self.assertRaises(frappe.ValidationError) as caught:
			self._run_task(CALLER, {"raw": "x"})
		self.assertIn("cannot import another script", str(caught.exception))

	def test_library_object_is_read_only(self):
		self._script(CALLER, f'lib = import_script("{LIBRARY}")\nlib.strip_fences = len\n')
		with self.assertRaises(AttributeError):
			self._run_task(CALLER, {})

	def test_library_runs_once_per_engine_run(self):
		second = self._script("Import Test: Second Caller", CALLER_BODY + CALLER_BODY)
		extensions = _extensions(LIBRARY, CALLER, second)
		engine = _make_script_engine(script_task_extensions=extensions, instance=self.instance)
		with patch.object(
			script_imports, "check_server_script", wraps=script_imports.check_server_script
		) as library_checks:
			engine._run_frappe_server_script(CALLER, _FakeTask({"raw": "a"}))
			engine._run_frappe_server_script(second, _FakeTask({"raw": "b"}))
		self.assertEqual(library_checks.call_count, 1)


class TestImportScriptThroughCallActivity(FrappeTestCase):
	"""A library on a called map is part of the calling process."""

	def setUp(self):
		super().setUp()
		self._models = []
		for name, body in ((LIBRARY, LIBRARY_BODY), (CALLER, CALLER_BODY)):
			if frappe.db.exists("Server Script", name):
				frappe.delete_doc("Server Script", name, force=True, ignore_permissions=True)
			frappe.get_doc(
				{
					"doctype": "Server Script",
					"name": name,
					"script_type": "API",
					"api_method": frappe.scrub(name).replace(":", ""),
					"script": body,
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		for name in self._models:
			if frappe.db.exists("BPMN Process Model", name):
				frappe.delete_doc("BPMN Process Model", name, force=1, ignore_permissions=True)
		frappe.db.commit()
		super().tearDown()

	def _model(self, name, process_id, xml):
		if frappe.db.exists("BPMN Process Model", name):
			frappe.delete_doc("BPMN Process Model", name, force=1, ignore_permissions=True)
		doc = frappe.new_doc("BPMN Process Model")
		doc.update({"name": name, "title": name, "process_id": process_id, "version": 1, "bpmn_xml": xml})
		doc.insert(ignore_permissions=True)
		self._models.append(name)
		return doc

	def test_library_on_a_called_map_can_be_imported(self):
		self._model("Import Test Child", "import_test_child", _map_xml("import_test_child", [LIBRARY]))
		parent = self._model(
			"Import Test Parent",
			"import_test_parent",
			_map_xml("import_test_parent", [CALLER], called="import_test_child"),
		)
		compiled = compile_process_model(parent.name)
		self.assertTrue(compiled["success"], compiled)
		spec = json.loads(frappe.db.get_value("BPMN Process Model", parent.name, "serialized_spec"))
		instance = frappe._dict(process_model=parent.name)
		engine = _make_script_engine(script_task_extensions=spec["script_task_extensions"], instance=instance)
		task = _FakeTask({"raw": "```\nfrom child\n```"})
		engine._run_frappe_server_script(CALLER, task)
		self.assertEqual(task.data["clean"], "from child")


def _map_xml(process_id, scripts, called=""):
	"""A map whose flow runs each script task in turn, then an optional Call Activity."""
	ids = (
		["start"]
		+ [f"{process_id}_s{i}" for i in range(len(scripts))]
		+ (["call"] if called else [])
		+ ["end"]
	)
	flows = [
		f'<bpmn:sequenceFlow id="f{i}" sourceRef="{source}" targetRef="{target}" />'
		for i, (source, target) in enumerate(pairwise(ids))
	]

	def links(index):
		incoming = f"<bpmn:incoming>f{index - 1}</bpmn:incoming>" if index else ""
		outgoing = f"<bpmn:outgoing>f{index}</bpmn:outgoing>" if index < len(ids) - 1 else ""
		return incoming + outgoing

	shapes = [f'<bpmn:startEvent id="start">{links(0)}</bpmn:startEvent>']
	shapes += [
		f'<bpmn:scriptTask id="{process_id}_s{i}" name="Step {i}" spiffworkflow:serverScript="{name}" '
		f'spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="{name}">'
		f"{links(i + 1)}</bpmn:scriptTask>"
		for i, name in enumerate(scripts)
	]
	if called:
		shapes.append(
			f'<bpmn:callActivity id="call" name="Call" calledElement="{called}">{links(len(ids) - 2)}</bpmn:callActivity>'
		)
	shapes.append(f'<bpmn:endEvent id="end">{links(len(ids) - 1)}</bpmn:endEvent>')
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
 xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
 id="Defs_{process_id}" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="{process_id}" name="{process_id}" isExecutable="true">
    {"".join(shapes)}
    {"".join(flows)}
  </bpmn:process>
</bpmn:definitions>"""
