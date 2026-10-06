# Copyright (c) 2026, one-fm and contributors
"""Each Docu writer tool reports when its call started and ended, and how long it took, in its result."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import docu_writer_tools_record_their_timing as p
from one_bpmn.tools.tool_for_server_scripts import timed

# The six scripts as the live site holds them.
SCRIPTS = {
	"docu_writer_tool_doctype_exists": (
		"# Docu writer tool: whether a DocType exists and whether it is custom.\n"
		"from one_bpmn.tools.tool_for_server_scripts import doctype_exists\n"
		'result["answer"] = doctype_exists(doctype)\n'
	),
	"docu_writer_tool_get_doctype_definition": (
		"# Docu writer tool: the complete definition of a DocType, as JSON.\n"
		"from one_bpmn.tools.tool_for_server_scripts import get_doctype_definition\n"
		'result["definition"] = get_doctype_definition(doctype)\n'
	),
	"docu_writer_tool_get_doctype_fields": (
		"# Docu writer tool: the fields of a DocType (fieldname, fieldtype, label, reqd).\n"
		"from one_bpmn.tools.tool_for_server_scripts import get_doctype_fields\n"
		'result["fields"] = get_doctype_fields(doctype)\n'
	),
	"docu_writer_tool_list_doctypes": (
		"# Docu writer tool: existing DocTypes, optionally filtered by a search term.\n"
		"# An argument the model leaves out is not injected, so read it defensively.\n"
		"from one_bpmn.tools.tool_for_server_scripts import list_doctypes\n"
		"try:\n"
		"    _search = search\n"
		"except NameError:\n"
		'    _search = ""\n'
		'result["doctypes"] = list_doctypes(_search or "")\n'
	),
	"docu_writer_tool_list_roles": (
		"# Docu writer tool: role names a permission rule may use.\n"
		"# An argument the model leaves out is not injected, so read it defensively.\n"
		"from one_bpmn.tools.tool_for_server_scripts import list_roles\n"
		"try:\n"
		"    _search = search\n"
		"except NameError:\n"
		'    _search = ""\n'
		'result["roles"] = list_roles(_search or "")\n'
	),
	"docu_writer_tool_validate_doctype": (
		"# Docu writer tool: the schema-safety gate on a definition given as JSON text.\n"
		"from one_bpmn.tools.tool_for_server_scripts import validate_doctype_json\n"
		'result["validation"] = validate_doctype_json(ir)\n'
	),
}
ANSWER_KEYS = {
	"docu_writer_tool_doctype_exists": "answer",
	"docu_writer_tool_get_doctype_definition": "definition",
	"docu_writer_tool_get_doctype_fields": "fields",
	"docu_writer_tool_list_doctypes": "doctypes",
	"docu_writer_tool_list_roles": "roles",
	"docu_writer_tool_validate_doctype": "validation",
}
IR = json.dumps({"name": "Timing Probe", "fields": []})


def _script_name(api_method: str) -> str:
	return frappe.db.get_value("Server Script", {"api_method": api_method}, "name")


def _script(api_method: str) -> str:
	return frappe.db.get_value("Server Script", {"api_method": api_method}, "script")


class TestDocuWriterToolsRecordTheirTiming(FrappeTestCase):
	def setUp(self):
		frappe.db.savepoint("writer_tool_timing")
		for api_method, script in SCRIPTS.items():
			name = _script_name(api_method)
			if name:
				frappe.db.set_value("Server Script", name, "script", script)
			else:
				frappe.get_doc(
					{
						"doctype": "Server Script",
						"name": f"Timing Probe {api_method}",
						"script_type": "API",
						"api_method": api_method,
						"script": script,
					}
				).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback(save_point="writer_tool_timing")

	def _run(self, api_method: str) -> dict:
		result = {}
		scope = {"frappe": frappe, "result": result, "doctype": "Note", "ir": IR, "search": "Note"}
		exec(_script(api_method), scope)
		return result

	def test_each_tool_result_carries_the_timing_of_its_call(self):
		p.execute()
		for api_method, _line, call in p.TOOLS:
			with self.subTest(tool=call):
				result = self._run(api_method)
				self.assertIn(ANSWER_KEYS[api_method], result)
				self.assertEqual(len(result["timings"]), 1)
				timing = result["timings"][0]
				self.assertEqual(timing["call"], call)
				self.assertGreaterEqual(timing["ms"], 0)
				self.assertLessEqual(timing["started_at"], timing["ended_at"])

	def test_running_twice_changes_nothing(self):
		p.execute()
		first = {api_method: _script(api_method) for api_method in SCRIPTS}
		p.execute()

		self.assertEqual({api_method: _script(api_method) for api_method in SCRIPTS}, first)

	def test_a_script_missing_its_call_line_is_left_as_it_is(self):
		frappe.db.set_value(
			"Server Script", _script_name("docu_writer_tool_list_roles"), "script", 'result["x"] = 1'
		)
		p.execute()

		self.assertEqual(_script("docu_writer_tool_list_roles"), 'result["x"] = 1')


class TestTimedRecordsABlockThatRaises(FrappeTestCase):
	def test_the_timing_is_kept_when_the_call_fails(self):
		timings = []
		with self.assertRaises(ValueError):
			with timed(timings, "boom"):
				raise ValueError

		self.assertEqual([t["call"] for t in timings], ["boom"])
