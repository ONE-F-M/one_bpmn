"""Docu has no Python backend left — the map owns the agent (WI-001813 follow-up).

Docu's stage tools live in the process map's Server Scripts. The only Python
left is shared infrastructure: the DocType schema tools in
``one_bpmn.tools.tool_for_server_scripts`` (which exist because a ToolSpec ``fn``
must be an importable callable — see that module's docstring) and the
``api/docu_api.py`` endpoints the DocuCanvas panel calls.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_docu_backend_rip
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.tools import tool_for_server_scripts as T

# The five stage tools of the Docu map's ad-hoc Tools sub-process.
DOCU_SCRIPTS = (
	"Docu – Tool Classify Intent",
	"Docu – Tool Clarify",
	"Docu – Tool Write Schema",
	"Docu – Tool Review Schema",
	"Docu – Tool Finalize",
)

# Every name the map's scripts import from the shared module.
REQUIRED_CALLABLES = (
	"list_doctypes",
	"doctype_exists",
	"read_doctype_definition",
	"get_doctype_definition",
	"validate_doctype_json",
	"diff_ir",
	"get_doctype_fields",
)
REQUIRED_TUPLES = (
	"DOCFIELD_FLAGS",
	"DOCFIELD_INTS",
	"DOCFIELD_STRS",
	"DOCFIELD_ATTRS",
	"DOCTYPE_SETTING_FLAGS",
	"DOCTYPE_SETTING_INTS",
	"DOCTYPE_SETTING_STRS",
)


class TestDocuBackendRemoved(FrappeTestCase):
	def test_agent_package_is_gone(self):
		for mod in (
			"one_bpmn.agents.google_adk.docu_agent",
			"one_bpmn.agents.google_adk.docu_agent.tools",
			"one_bpmn.agents.google_adk.docu_agent.docu_agent",
		):
			self.assertIsNone(
				importlib.util.find_spec(mod) if _parent_importable(mod) else None,
				msg=f"{mod} still exists — Docu must have no Python backend",
			)

	def test_no_app_module_references_the_package(self):
		app = Path(frappe.get_app_path("one_bpmn"))
		offenders = []
		for py in app.rglob("*.py"):
			if "__pycache__" in str(py):
				continue
			text = py.read_text(errors="ignore")
			# allowed: the history note in the inline patch's docstring, and this
			# test itself (which names the module paths it asserts are gone)
			if py.name in ("inline_docu_tool_scripts.py", Path(__file__).name):
				continue
			if "google_adk.docu_agent" in text:
				offenders.append(str(py.relative_to(app)))
		self.assertEqual(offenders, [], msg="stale imports of the deleted Docu package")

	def test_docu_api_uses_the_shared_module(self):
		src = (Path(frappe.get_app_path("one_bpmn")) / "api" / "docu_api.py").read_text()
		self.assertIn("from one_bpmn.tools.tool_for_server_scripts import", src)
		self.assertNotIn("google_adk", src)


class TestSharedSchemaTools(FrappeTestCase):
	"""The contract the map's Server Scripts depend on."""

	def test_exports_every_name_the_map_imports(self):
		for name in REQUIRED_CALLABLES:
			self.assertTrue(callable(getattr(T, name, None)), msg=f"{name} missing/not callable")
		for name in REQUIRED_TUPLES:
			self.assertIsInstance(getattr(T, name, None), tuple, msg=f"{name} missing")

	def test_docfield_attrs_covers_flags_ints_and_strs(self):
		for group in (T.DOCFIELD_STRS, T.DOCFIELD_INTS, T.DOCFIELD_FLAGS):
			for attr in group:
				self.assertIn(attr, T.DOCFIELD_ATTRS)

	def test_read_doctype_definition_round_trips_a_real_doctype(self):
		ir = T.read_doctype_definition("ToDo")
		self.assertEqual(ir["doctype_name"], "ToDo")
		self.assertTrue(ir["fields"])
		# every field carries the full attribute set, not a subset
		for attr in T.DOCFIELD_ATTRS:
			self.assertIn(attr, ir["fields"][0])
		# DocType-level settings are present and coerced
		self.assertIn("is_submittable", ir)
		self.assertIsInstance(ir["is_submittable"], int)

	def test_read_doctype_definition_missing_is_none(self):
		self.assertIsNone(T.read_doctype_definition("No Such DocType 9x"))

	def test_layout_breaks_keep_an_empty_label(self):
		"""A layout break must not fall back to its fieldname, or a Customize Form
		round-trip emits spurious label Property Setters."""
		ir = T.read_doctype_definition("ToDo")
		breaks = [f for f in ir["fields"] if f["fieldtype"] in ("Section Break", "Column Break", "Tab Break")]
		if breaks:
			self.assertTrue(all(b["label"] == "" or b["label"] for b in breaks))
			unlabelled = [b for b in breaks if b["label"] == b["fieldname"]]
			self.assertEqual(unlabelled, [], msg="layout break label fell back to the fieldname")

	def test_diff_ir_reports_added_removed_and_changed(self):
		before = {"fields": [
			{"fieldname": "a", "label": "A", "fieldtype": "Data", "reqd": 0},
			{"fieldname": "gone", "label": "Gone", "fieldtype": "Int"},
		]}
		after = {"fields": [
			{"fieldname": "a", "label": "A", "fieldtype": "Data", "reqd": 1},
			{"fieldname": "new", "label": "New", "fieldtype": "Small Text"},
		]}
		d = T.diff_ir(before, after)
		self.assertEqual([f["fieldname"] for f in d["added"]], ["new"])
		self.assertEqual([f["fieldname"] for f in d["removed"]], ["gone"])
		self.assertEqual(d["changed"][0]["fieldname"], "a")
		self.assertIn("reqd", d["changed"][0]["changes"])
		self.assertIn("+ add field 'New' (Small Text)", d["summary"])
		self.assertIn("- remove field 'Gone'", d["summary"])

	def test_diff_ir_skips_fields_without_a_fieldname(self):
		ir = {"fields": [{"fieldname": "", "label": "break", "fieldtype": "Section Break"}]}
		self.assertEqual(T.diff_ir(ir, ir), {"added": [], "removed": [], "changed": [], "summary": ""})

	def test_diff_ir_tolerates_none(self):
		self.assertEqual(T.diff_ir(None, None)["summary"], "")

	def test_validate_doctype_json_wraps_the_schema_gate(self):
		import json

		good = json.dumps({"doctype_name": "Rip Probe", "module": "ONE BPMN",
		                   "fields": [{"fieldname": "x", "label": "X", "fieldtype": "Data"}]})
		self.assertTrue(json.loads(T.validate_doctype_json(good))["valid"])
		bad = json.loads(T.validate_doctype_json("{not json"))
		self.assertFalse(bad["valid"])
		self.assertTrue(bad["violations"])

	def test_read_tools_return_json_strings(self):
		import json

		self.assertIsInstance(json.loads(T.list_doctypes("ToDo")), list)
		self.assertEqual(json.loads(T.doctype_exists("ToDo"))["exists"], True)
		self.assertEqual(json.loads(T.doctype_exists("No Such DocType 9x"))["exists"], False)


class TestDocuMapScripts(FrappeTestCase):
	"""The live Server Scripts must stay self-contained and gate-clean."""

	def _bodies(self):
		out = {}
		for name in DOCU_SCRIPTS:
			if frappe.db.exists("Server Script", name):
				out[name] = frappe.db.get_value("Server Script", name, "script") or ""
		return out

	def test_scripts_do_not_import_the_deleted_package(self):
		for name, body in self._bodies().items():
			self.assertNotIn("google_adk", body, msg=f"{name} imports the deleted package")
			self.assertNotIn("docu_tools", body, msg=f"{name} still references docu_tools")

	def test_scripts_are_flat(self):
		"""No def/lambda: an AI Agent shape tool runs under split globals/locals,
		so a nested scope cannot see the script's own imports."""
		for name, body in self._bodies().items():
			code = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
			self.assertNotIn("def ", code, msg=f"{name} defines a function")
			self.assertNotIn("lambda", code, msg=f"{name} uses a lambda")

	def test_scripts_pass_the_bpmn_script_gate(self):
		from one_bpmn.security.script_validator import deep_inspect_script

		for name, body in self._bodies().items():
			self.assertEqual(deep_inspect_script(body), [], msg=f"{name} fails the script gate")

	def test_scripts_compile(self):
		for name, body in self._bodies().items():
			# context_docname / result are injected by the executor
			src = body.replace("context_docname", '"x"').replace("result[", "_r[")
			compile(src, name, "exec")

	def test_inline_patch_bodies_are_self_contained(self):
		from one_bpmn.one_bpmn.patches.v1_0 import inline_docu_tool_scripts as patch

		for name, body in patch.SCRIPTS.items():
			self.assertNotIn("google_adk", body, msg=f"patch body {name} imports the deleted package")
			self.assertNotIn("docu_tools", body, msg=f"patch body {name} references docu_tools")


def _parent_importable(dotted: str) -> bool:
	"""find_spec raises ModuleNotFoundError when a PARENT is missing; treat that
	as 'gone' rather than letting it blow up the assertion."""
	parent = dotted.rsplit(".", 1)[0]
	try:
		return importlib.util.find_spec(parent) is not None
	except ModuleNotFoundError:
		return False
