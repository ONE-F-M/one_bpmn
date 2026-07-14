# Copyright (c) 2026, one-fm and contributors
"""
Integration tests for the BPMN Script-Task security ENFORCEMENT gates
(``one_bpmn.security.script_gate``).

Covers the three pre-deployment gates:
  * process-model authoring / deploy → validate_process_model_scripts
  * Server Script save               → validate_server_script_on_save
  * BPMN linkage scoping             → is_bpmn_linked_server_script

Requires a Frappe bench (DB). Run with:
  bench --site <site> run-tests --app one_bpmn --module \
    one_bpmn.tests.test_script_security_gate
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.security import script_gate


def _bpmn_with_inline(script_body: str, task_id: str = "Task_1") -> str:
	"""Minimal BPMN diagram carrying a single inline <bpmn:script> task."""
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
		'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core">'
		'<bpmn:process id="Process_1" isExecutable="true">'
		f'<bpmn:scriptTask id="{task_id}">'
		f'<bpmn:script>{script_body}</bpmn:script>'
		'</bpmn:scriptTask>'
		'</bpmn:process></bpmn:definitions>'
	)


def _bpmn_with_server_script(script_name: str, task_id: str = "Task_1") -> str:
	"""Minimal BPMN diagram whose script task references a Server Script."""
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
		'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core">'
		'<bpmn:process id="Process_1" isExecutable="true">'
		f'<bpmn:scriptTask id="{task_id}" spiffworkflow:serverScript="{script_name}">'
		'<bpmn:script>pass</bpmn:script>'
		'</bpmn:scriptTask>'
		'</bpmn:process></bpmn:definitions>'
	)


class TestProcessModelScriptGate(FrappeTestCase):
	def test_safe_inline_passes(self):
		xml = _bpmn_with_inline("doc = frappe.get_doc('User', 'Administrator')")
		# Should not raise.
		script_gate.validate_process_model_scripts(xml)

	def test_unsafe_inline_raises(self):
		xml = _bpmn_with_inline("import os\nos.system('id')")
		with self.assertRaises(frappe.ValidationError):
			script_gate.validate_process_model_scripts(xml)

	def test_kwargs_bypass_inline_raises(self):
		xml = _bpmn_with_inline("doc.save(ignore_permissions=True)")
		with self.assertRaises(frappe.ValidationError):
			script_gate.validate_process_model_scripts(xml)

	def test_unparseable_xml_is_noop(self):
		# Never raise on malformed XML — other validators own that.
		script_gate.validate_process_model_scripts("<not-bpmn>")

	def test_blocked_message_is_generic_summary(self):
		# The editor modal gets a concise summary (task label + issue count +
		# where to look), NOT a dump of every rule that tripped.
		xml = _bpmn_with_inline(
			"import os\nexec('x')\neval('y')\nopen('/etc/passwd')", task_id="Task_Bad"
		)
		with self.assertRaises(frappe.ValidationError) as ctx:
			script_gate.validate_process_model_scripts(xml)
		msg = str(ctx.exception)
		# Names the affected task and summarises with a count …
		self.assertIn("Task_Bad", msg)
		self.assertIn("security issue", msg)
		self.assertIn("Deployment Readiness", msg)
		# … but does not leak the specific per-rule blacklist text.
		self.assertNotIn("Forbidden import", msg)
		self.assertNotIn("exec() is not allowed", msg)


class TestServerScriptGate(FrappeTestCase):
	def _make_server_script(self, name: str, body: str):
		if frappe.db.exists("Server Script", name):
			frappe.delete_doc("Server Script", name, force=True)
		doc = frappe.get_doc({
			"doctype": "Server Script",
			"name": name,
			"script_type": "API",
			"api_method": name.replace(" ", "_").lower(),
			"script": body,
		})
		doc.flags.ignore_permissions = True
		return doc

	def test_unlinked_server_script_is_not_gated(self):
		# An unsafe body is allowed when NO BPMN model references the script.
		doc = self._make_server_script("ZZ Unlinked Script", "import os")
		# Gate is a no-op for unlinked scripts → insert must succeed.
		doc.insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Server Script", "ZZ Unlinked Script"))
		self.addCleanup(frappe.delete_doc, "Server Script", "ZZ Unlinked Script", force=True)

	def test_linked_unsafe_server_script_is_blocked(self):
		script_name = "ZZ Linked Unsafe Script"
		# A deployed/authored model references the script by name.
		model = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"process_id": "Process_1",
			"bpmn_xml": _bpmn_with_server_script(script_name),
		})
		model.flags.skip_editability_check = True
		model.flags.skip_script_security_check = True  # model XML itself is inline 'pass'
		model.insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "BPMN Process Model", model.name, force=True)

		self.assertTrue(script_gate.is_bpmn_linked_server_script(script_name))

		doc = self._make_server_script(script_name, "getattr(frappe, '__globals__')")
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.db.exists("Server Script", script_name)
			and frappe.delete_doc("Server Script", script_name, force=True)
		)

	def test_unlinked_name_is_not_flagged_as_linked(self):
		self.assertFalse(script_gate.is_bpmn_linked_server_script("Totally Unrelated Script"))
		self.assertFalse(script_gate.is_bpmn_linked_server_script(""))
