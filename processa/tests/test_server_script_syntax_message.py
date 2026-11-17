# Copyright (c) 2026, one-fm and contributors
"""Saving a Server Script with a syntax error tells the person the line and the reason."""

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api.server_scripts import create_server_script


class TestServerScriptSyntaxMessage(FrappeTestCase):
	def _save(self, script: str) -> list[str]:
		frappe.clear_messages()
		create_server_script(f"Syntax Probe {frappe.generate_hash(length=6)}", "API", script)
		return [m.get("message") for m in frappe.message_log]

	def test_a_syntax_error_is_told_as_its_line_and_reason(self):
		self.assertEqual(self._save('print(""'), ["Syntax error on line 1: '(' was never closed"])

	def test_a_name_the_restricted_compiler_dislikes_is_told_as_a_sentence(self):
		self.assertEqual(
			self._save("_x = 1"), ['Line 1: "_x" is an invalid variable name because it starts with "_"']
		)

	def test_a_script_that_parses_gets_no_syntax_message(self):
		self.assertFalse([m for m in self._save('result = {"ok": 1}') if "Syntax error" in m])
