# Copyright (c) 2026, one-fm and contributors
"""Server Script that runs its document events through the Processa runner inside a map."""

import ast
import json

import frappe
from frappe import _
from frappe.core.doctype.server_script.server_script import ServerScript
from frappe.utils.safe_exec import FrappeTransformer
from RestrictedPython import compile_restricted


class ProcessaServerScript(ServerScript):
	def check_if_compilable_in_restricted_context(self):
		"""Compile warnings as plain sentences; Frappe's own check prints the raw exception."""
		script = self.script or ""
		try:
			ast.parse(script)
		except SyntaxError as exc:
			frappe.msgprint(
				_("Syntax error on line {0}: {1}").format(exc.lineno, exc.msg), title=_("Compilation warning")
			)
			return
		try:
			compile_restricted(script, policy=FrappeTransformer)
		except SyntaxError as exc:
			frappe.msgprint("<br>".join(exc.msg), title=_("Compilation warning"))

	def execute_doc(self, doc):
		"""Inside a Processa script task or tool, validate and run with real imports; elsewhere use safe_exec."""
		if not frappe.flags.in_processa_script:
			super().execute_doc(doc)
			return

		from processa.processa_engine.engine import check_server_script

		check_server_script(self)
		# json is bound like safe_exec binds it, so doc event scripts written for safe_exec keep working.
		exec(self.script, {"__builtins__": __builtins__, "frappe": frappe, "json": json, "doc": doc})
