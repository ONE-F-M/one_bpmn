# Copyright (c) 2026, one-fm and contributors
# WI-001354 (3-01): AI Agent Tool doctype.

import frappe
from frappe.tests.utils import FrappeTestCase

# The tests create their own Server Script fixture; auto-generating test
# records for the link targets drags in unrelated fixtures (Email Domain)
# that fail on this site.
test_ignore = ["Server Script", "BPMN Process Model"]

VALID_SCHEMA = (
	'{"summary": {"type": "string", "description": "Short summary"},'
	' "priority": {"type": "string", "description": "low/medium/high"}}'
)


def _make_server_script(name, disabled=0):
	if frappe.db.exists("Server Script", name):
		return frappe.get_doc("Server Script", name)
	script = frappe.get_doc(
		{
			"doctype": "Server Script",
			"name": name,
			"script_type": "API",
			"api_method": name.lower().replace(" ", "_"),
			"script": "result = {'ok': True}",
			"disabled": disabled,
		}
	)
	script.insert(ignore_permissions=True)
	return script


def _make_tool(**overrides):
	values = {
		"doctype": "AI Agent Tool",
		"tool_name": "test_tool",
		"description": "Creates a test record from a summary.",
		"input_schema": VALID_SCHEMA,
		"required_params": "summary",
		"handler_type": "server_script",
		"handler_reference": "Test Tool Handler",
		"is_active": 1,
	}
	values.update(overrides)
	return frappe.get_doc(values)


class TestAIAgentTool(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_make_server_script("Test Tool Handler")

	# ── Scenario 1: field shape / creation ──

	def test_tool_creation_with_valid_definition(self):
		tool = _make_tool(tool_name="creation_test_tool")
		tool.insert(ignore_permissions=True)
		self.assertEqual(tool.name, "creation_test_tool")  # autoname field:tool_name
		self.assertEqual(tool.handler_doctype, "Server Script")
		self.assertEqual(tool.get_required_param_list(), ["summary"])
		self.assertIn("summary", tool.get_parsed_input_schema())

	# ── Scenario 2: server_script reference must exist and be enabled ──

	def test_missing_server_script_rejected(self):
		tool = _make_tool(tool_name="missing_handler_tool", handler_reference="No Such Script 404")
		with self.assertRaises(frappe.ValidationError):
			tool.insert(ignore_permissions=True)

	def test_disabled_server_script_rejected(self):
		_make_server_script("Disabled Tool Handler", disabled=1)
		tool = _make_tool(tool_name="disabled_handler_tool", handler_reference="Disabled Tool Handler")
		with self.assertRaises(frappe.ValidationError):
			tool.insert(ignore_permissions=True)

	# ── Scenario 3: schema validation ──

	def test_invalid_json_schema_rejected(self):
		tool = _make_tool(tool_name="bad_json_tool", input_schema="{not valid json")
		with self.assertRaises(frappe.ValidationError):
			tool.insert(ignore_permissions=True)

	def test_missing_type_key_rejected(self):
		tool = _make_tool(
			tool_name="typeless_tool",
			input_schema='{"summary": {"description": "no type key"}}',
		)
		with self.assertRaises(frappe.ValidationError):
			tool.insert(ignore_permissions=True)

	def test_required_param_not_in_schema_rejected(self):
		tool = _make_tool(tool_name="ghost_param_tool", required_params="summary, ghost")
		with self.assertRaises(frappe.ValidationError):
			tool.insert(ignore_permissions=True)

	# ── Scenario 4: duplicate tool_name rejected ──

	def test_duplicate_tool_name_rejected(self):
		_make_tool(tool_name="dup_tool").insert(ignore_permissions=True)
		with self.assertRaises(frappe.DuplicateEntryError):
			_make_tool(tool_name="dup_tool").insert(ignore_permissions=True)

	# ── Scenario 5: permissions split ──

	def test_permissions_split(self):
		meta = frappe.get_meta("AI Agent Tool")
		by_role = {p.role: p for p in meta.permissions}
		self.assertIn("System Manager", by_role)
		sm = by_role["System Manager"]
		self.assertTrue(sm.read and sm.write and sm.create and sm.delete)
		self.assertIn("Process Owner", by_role)
		po = by_role["Process Owner"]
		self.assertTrue(po.read and po.create)
		self.assertFalse(po.write or po.delete)

	# ── call_activity handlers definable (execution out of scope) ──

	def test_call_activity_handler_definable(self):
		model_name = frappe.get_all("BPMN Process Model", limit=1, pluck="name")
		if not model_name:
			self.skipTest("No BPMN Process Model on site to reference")
		tool = _make_tool(
			tool_name="call_activity_tool",
			handler_type="call_activity",
			handler_reference=model_name[0],
		)
		tool.insert(ignore_permissions=True)
		self.assertEqual(tool.handler_doctype, "BPMN Process Model")
