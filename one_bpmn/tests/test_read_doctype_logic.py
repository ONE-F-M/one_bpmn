# Copyright (c) 2026, one-fm and contributors
# License: MIT. See license.txt
"""The read_doctype_logic tool: the source reader, the Server Script and the patch."""

import ast
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import codebase_index as ci
from one_bpmn.one_bpmn.patches.v1_0 import lucrusher_reads_doctype_logic as p
from one_bpmn.security.script_validator import deep_inspect_script

DOCTYPE_DIR = "one_fm/one_fm/one_fm/doctype"
SCHEDULE_ENTRY_HOOK = "one_fm.one_fm.doctype.maintenance_schedule_entry.maintenance_schedule_entry.generate_due_work_orders"


def _entry(name, py_exists=True):
	slug = name.lower().replace(" ", "_")
	return {
		"name": name,
		"app": "one_fm",
		"module": "One Fm",
		"file": f"{DOCTYPE_DIR}/{slug}/{slug}.json",
		"py_file": f"{DOCTYPE_DIR}/{slug}/{slug}.py",
		"py_exists": py_exists,
	}


def _index(*entries, hooks=()):
	return {"doctypes": list(entries), "hooks": list(hooks), "apps_scanned": ["one_fm"]}


def _read(names, index):
	with patch.object(ci, "get_codebase_index", return_value=index):
		return ci.read_doctype_sources(names, 60)


def _one_fm_installed():
	return os.path.isfile(os.path.join(ci.get_apps_root(), DOCTYPE_DIR, "event_staff", "event_staff.py"))


class TestReadDoctypeSources(FrappeTestCase):
	def setUp(self):
		if not _one_fm_installed():
			self.skipTest("one_fm is not installed")

	def test_event_staff_methods_and_deep_throw_survive_the_trim(self):
		item = _read(["Event Staff"], _index(_entry("Event Staff")))[0]
		methods = {m["name"]: m for m in item["methods"]}
		self.assertEqual(item["status"], "read")
		self.assertEqual(methods["on_submit"]["line"], 132)
		self.assertIn("before_update_after_submit", methods)
		self.assertIn("Over-Time", methods["process_employee_schedules"]["body"])

	def test_module_level_private_functions_and_the_scheduler_hook_are_read(self):
		hook = {
			"hook_type": "scheduler_events",
			"doctype": "",
			"event": "daily",
			"method": SCHEDULE_ENTRY_HOOK,
			"app": "one_fm",
		}
		item = _read(["Maintenance Schedule Entry"], _index(_entry("Maintenance Schedule Entry"), hooks=[hook]))[0]
		functions = {f["name"] for f in item["module_functions"]}
		self.assertTrue({"_resolve_base_date", "_get_settings"} <= functions)
		self.assertEqual([h["method"] for h in item["hooks"]], [SCHEDULE_ENTRY_HOOK])
		self.assertIn("def generate_due_work_orders", item["hooks"][0]["body"])

	def test_scheduler_hook_of_another_module_is_left_out(self):
		hook = {
			"hook_type": "scheduler_events",
			"doctype": "",
			"event": "daily",
			"method": SCHEDULE_ENTRY_HOOK,
			"app": "one_fm",
		}
		item = _read(["Event Staff"], _index(_entry("Event Staff"), hooks=[hook]))[0]
		self.assertEqual(item["hooks"], [])

	def test_star_hooks_are_counted_not_returned(self):
		hook = {"hook_type": "doc_events", "doctype": "*", "event": "on_update", "method": "x.y.z", "app": "one_fm"}
		item = _read(["Event Staff"], _index(_entry("Event Staff"), hooks=[hook]))[0]
		self.assertEqual((item["hooks"], item["star_hooks"]), ([], 1))


class TestReadDoctypeSourcesStatus(FrappeTestCase):
	def test_doctype_without_a_controller_file_is_reported(self):
		item = _read(["Custom Thing"], _index(_entry("Custom Thing", py_exists=False)))[0]
		self.assertEqual(item["status"], "no_controller_file")
		self.assertIn("no controller file", item["message"])

	def test_unknown_doctype_is_reported(self):
		item = _read(["Nope"], _index(_entry("Event Staff")))[0]
		self.assertEqual(item["status"], "unknown_doctype")

	def test_long_function_is_cut_to_the_limit_and_keeps_its_throw(self):
		lines = ["def long_fn(doc):", "\tx = 0"] + ["\tx += 1"] * 150
		lines.insert(100, "\tfrappe.throw('late rule')")
		source = "\n".join(lines)
		info = ci._function_info(ast.parse(source).body[0], source.splitlines(), 60)
		self.assertTrue(info["trimmed"])
		self.assertEqual(info["full_lines"], 153)
		self.assertLessEqual(len(info["body"].splitlines()), 60)
		self.assertIn("late rule", info["body"])


def _fake_frappe(workflows=False, scripts=None, script_error=None):
	def get_all(doctype, **kwargs):
		return [{"name": "WF", "workflow_state_field": "workflow_state"}] if workflows else []

	def get_list(doctype, **kwargs):
		if script_error:
			raise script_error
		return scripts or []

	def get_doc(doctype, name):
		return SimpleNamespace(
			name=name,
			workflow_state_field="workflow_state",
			states=[SimpleNamespace(state="Draft", doc_status="0", allow_edit="Operations Supervisor")],
			transitions=[
				SimpleNamespace(
					state="Draft",
					action="Submit",
					next_state="Approved",
					allowed="Project Manager",
					condition=None,
					allow_self_approval=1,
				)
			],
		)

	return SimpleNamespace(get_all=get_all, get_list=get_list, get_doc=get_doc)


def _doc(name, body_lines=2):
	method = {"name": "m", "line": 1, "end_line": 9, "body": "\n".join(["x = 1"] * body_lines), "trimmed": False}
	return {"doctype": name, "status": "read", "methods": [method], "module_functions": [], "hooks": []}


def _run_script(names, sources, **fake):
	scope = {"frappe": _fake_frappe(**fake), "task_data": {"doctypes": names}, "result": {}}
	with patch.object(ci, "read_doctype_sources", side_effect=lambda read, limit: sources(read)):
		exec(p.READ_DOCTYPE_LOGIC_SCRIPT, scope, {})  # noqa: S102 - the script text under test
	return scope["result"]["doctype_logic"]


class TestReadDoctypeLogicScript(FrappeTestCase):
	def test_script_passes_the_script_gate(self):
		self.assertEqual(deep_inspect_script(p.READ_DOCTYPE_LOGIC_SCRIPT), [])

	def test_seven_names_read_five_and_skip_two(self):
		names = [f"DT {i}" for i in range(7)] + ["dt 0"]
		seen = []
		out = _run_script(names, lambda read: seen.extend(read) or [_doc(n) for n in read])
		self.assertEqual(seen, [f"DT {i}" for i in range(5)])
		self.assertEqual(out["read"], seen)
		self.assertEqual(out["skipped"], ["DT 5", "DT 6"])
		self.assertIn("call again", out["note"])

	def test_output_over_the_cap_is_cut_but_keeps_names_and_workflow(self):
		out = _run_script(
			["A", "B", "C", "D", "E"],
			lambda read: [_doc(n, body_lines=1500) for n in read],
			workflows=True,
		)
		self.assertTrue(out["truncated"])
		self.assertLessEqual(len(json.dumps(out, default=str)), 30000)
		for doc in out["doctypes"]:
			self.assertEqual(doc["methods"][0]["name"], "m")
			self.assertEqual(doc["workflow"]["transitions"][0]["allowed"], "Project Manager")

	def test_workflow_is_none_when_the_doctype_has_none(self):
		out = _run_script(["A"], lambda read: [_doc("A")])
		self.assertIsNone(out["doctypes"][0]["workflow"])

	def test_workflow_states_and_transitions_are_returned(self):
		wf = _run_script(["A"], lambda read: [_doc("A")], workflows=True)["doctypes"][0]["workflow"]
		self.assertEqual(wf["states"][0]["allow_edit"], "Operations Supervisor")
		self.assertEqual(wf["transitions"][0]["next_state"], "Approved")

	def test_server_script_permission_error_becomes_a_note(self):
		doc = _run_script(["A"], lambda read: [_doc("A")], script_error=PermissionError("denied"))["doctypes"][0]
		self.assertEqual(doc["server_scripts"], [])
		self.assertIn("could not read Server Scripts", doc["server_scripts_note"])

	def test_server_scripts_on_the_doctype_are_returned(self):
		rows = [{"name": "S1", "script_type": "DocType Event", "doctype_event": "Before Save", "script": "# c\nx = 1\n\ny = 2"}]
		doc = _run_script(["A"], lambda read: [_doc("A")], scripts=rows)["doctypes"][0]
		self.assertEqual(doc["server_scripts"][0]["body"], "x = 1\ny = 2")

	def test_no_names_gives_an_error_text(self):
		out = _run_script([" ", ""], lambda read: [])
		self.assertEqual(out["error"], "No DocType names supplied.")


MAP_XML = (
	'<bpmn:adHocSubProcess id="lucrusher_tools" name="Tools">\n'
	'  <bpmn:scriptTask id="finalize" name="finalize"></bpmn:scriptTask>\n'
	'  <bpmn:completionCondition xsi:type="bpmn:tFormalExpression">True</bpmn:completionCondition>\n'
	"</bpmn:adHocSubProcess>\n"
	"<bpmndi:BPMNPlane></bpmndi:BPMNPlane>"
)


class TestReadDoctypeLogicPatch(FrappeTestCase):
	def test_splice_adds_the_shape_inside_the_tools_sub_process_with_bounds(self):
		xml = p._splice_shape(MAP_XML)
		inside = xml[xml.index("<bpmn:adHocSubProcess") : xml.index("</bpmn:adHocSubProcess>")]
		self.assertIn('id="read_doctype_logic"', inside)
		self.assertIn('spiffworkflow:serverScript="LuCrusher - Tool Read DocType Logic"', inside)
		self.assertIn('bpmnElement="read_doctype_logic"', xml)
		self.assertIn('x="870" y="460" width="120" height="70"', xml)

	def test_splice_leaves_a_map_without_the_anchor_alone(self):
		self.assertEqual(p._splice_shape("<bpmn:definitions/>"), "<bpmn:definitions/>")

	def test_a_second_run_changes_nothing(self):
		store = {"xml": MAP_XML}
		with (
			patch.object(p.frappe.db, "exists", return_value=True),
			patch.object(p.frappe.db, "get_value", side_effect=lambda *a: store["xml"]),
			patch.object(p.frappe.db, "set_value", side_effect=lambda *a: store.update(xml=a[3])) as set_value,
			patch("one_bpmn.api.compilation.compile_process_model") as compile_model,
		):
			p._update_process_model()
			p._update_process_model()
		self.assertEqual(set_value.call_count, 1)
		self.assertEqual(compile_model.call_count, 1)
		self.assertEqual(store["xml"].count('id="read_doctype_logic"'), 1)
