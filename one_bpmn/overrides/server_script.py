# Copyright (c) 2026, one-fm and contributors
"""Server Script that runs its document events through the Processa runner inside a map."""

import json

import frappe
from frappe.core.doctype.server_script.server_script import ServerScript


class ProcessaServerScript(ServerScript):
	def execute_doc(self, doc):
		"""Inside a Processa script task or tool, validate and run with real imports; elsewhere use safe_exec."""
		if not frappe.flags.in_processa_script:
			super().execute_doc(doc)
			return

		from one_bpmn.processa_engine.engine import check_server_script

		check_server_script(self)
		# json is bound like safe_exec binds it, so doc event scripts written for safe_exec keep working.
		exec(self.script, {"__builtins__": __builtins__, "frappe": frappe, "json": json, "doc": doc})
