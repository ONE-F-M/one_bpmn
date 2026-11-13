"""The tool functions Server Scripts call answer a raised error with their error value, through tool_envelope."""

import inspect
import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_registry.definitions.docu import tools as docu_tools
from processa.ai_agent_registry.definitions.logix import tools as logix_tools
from processa.ai_agent_registry.definitions.shared import tools as shared_tools
from processa.ai_agent_registry.definitions.shared.helpers import tool_envelope

BROKEN = RuntimeError("database went away")

# Each tool, the call made to fail, the tool's arguments and the error value it returns.
CASES = (
	(
		logix_tools.get_server_script_content,
		(frappe, "get_doc"),
		{"script_name": "ZZ Script"},
		"# Error: Failed to fetch Server Script 'ZZ Script'.",
	),
	(
		logix_tools.get_server_script_meta,
		(frappe, "get_doc"),
		{"script_name": "ZZ Script"},
		json.dumps({"error": "Failed to fetch metadata for 'ZZ Script'."}),
	),
	(logix_tools.list_api_server_scripts, (frappe, "get_all"), {}, json.dumps([])),
	(
		shared_tools.get_doctype_fields,
		(frappe, "get_meta"),
		{"doctype": "ToDo"},
		json.dumps({"error": "Failed to fetch fields for DocType 'ToDo'."}),
	),
	(docu_tools.list_doctypes, (frappe, "get_all"), {"search": "To"}, json.dumps([])),
	(
		docu_tools.list_roles,
		(frappe, "get_all"),
		{"search": "Sys"},
		json.dumps({"roles": [], "error": "Could not read the role list."}),
	),
	(
		docu_tools.get_doctype_definition,
		(docu_tools, "read_doctype_definition"),
		{"doctype": "ToDo"},
		json.dumps({"error": "Failed to read DocType 'ToDo'."}),
	),
)


class TestToolEnvelope(FrappeTestCase):
	def test_a_raising_tool_returns_its_error_value_and_logs_it(self):
		for tool, (owner, call), kwargs, expected in CASES:
			with self.subTest(tool=tool.__name__):
				with (
					patch.object(owner, call, side_effect=BROKEN),
					patch.object(frappe, "log_error") as log_error,
				):
					self.assertEqual(tool(**kwargs), expected)
				self.assertTrue(log_error.call_args.kwargs["title"].endswith(tool.__name__))

	def test_doctype_exists_answers_not_found_when_the_lookup_raises(self):
		with patch.object(frappe.db, "exists", side_effect=BROKEN), patch.object(frappe, "log_error"):
			self.assertEqual(
				json.loads(docu_tools.doctype_exists("ToDo")), {"exists": False, "custom": False}
			)

	def test_positional_arguments_reach_the_error_value(self):
		with patch.object(frappe, "get_meta", side_effect=BROKEN), patch.object(frappe, "log_error"):
			self.assertIn("'ToDo'", shared_tools.get_doctype_fields("ToDo"))

	def test_a_tool_that_does_not_raise_is_unchanged(self):
		fields = json.loads(shared_tools.get_doctype_fields("ToDo"))
		self.assertIn("description", [f["fieldname"] for f in fields])
		self.assertEqual(json.loads(docu_tools.doctype_exists("ToDo"))["exists"], True)

	def test_specific_errors_keep_their_own_message(self):
		self.assertEqual(
			logix_tools.get_server_script_content("ZZ No Such Script"),
			"# Error: Server Script 'ZZ No Such Script' not found.",
		)

	def test_the_wrapper_keeps_the_tool_name_and_signature(self):
		@tool_envelope("Test Tool", lambda doctype, limit: f"{doctype}:{limit}")
		def sample(doctype: str, limit: int = 5) -> str:
			"""A sample tool."""
			raise BROKEN

		self.assertEqual(sample.__name__, "sample")
		self.assertEqual(list(inspect.signature(sample).parameters), ["doctype", "limit"])
		with patch.object(frappe, "log_error"):
			self.assertEqual(sample("ToDo"), "ToDo:5")
