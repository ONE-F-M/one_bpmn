# Copyright (c) 2026, one-fm and contributors
# Regression: BPMN Server Scripts run via exec() with a SINGLE namespace.
#
# With separate globals/locals dicts (the old code), top-level `def`s land
# in locals but each function's __globals__ is exec_globals — so a script
# where one top-level function calls another (or reads a top-level
# variable) crashed at runtime with NameError. First hit in production by
# the "JS Payload Stripper" script of the Resignation process.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.engine import _make_script_engine

test_ignore = ["BPMN Process Model"]

_HELPER_CALLS_HELPER = """
def strip_payload(value):
	if isinstance(value, str):
		return value.replace("<script>", "")
	return value


def check_security(value):
	# calls a sibling top-level function — the old two-dict exec broke here
	return strip_payload(value)


THRESHOLD = 5  # top-level variable read from inside a function


def over_threshold(n):
	return n > THRESHOLD


result["cleaned"] = check_security(raw_value)
result["flagged"] = over_threshold(9)
"""


class _FakeTaskSpec:
	bpmn_id = "script_1"
	name = "script_1"


class _FakeTask:
	def __init__(self, data):
		self.data = data
		self.task_spec = _FakeTaskSpec()


class TestServerScriptExecScope(FrappeTestCase):
	def _script(self, name, body):
		if not frappe.db.exists("Server Script", name):
			frappe.get_doc(
				{
					"doctype": "Server Script",
					"name": name,
					"script_type": "API",
					"api_method": name.lower().replace(" ", "_"),
					"script": body,
				}
			).insert(ignore_permissions=True)
		return name

	def test_function_calling_function_and_module_var(self):
		name = self._script("Exec Scope Regression", _HELPER_CALLS_HELPER)
		engine = _make_script_engine()
		task = _FakeTask({"raw_value": "<script>x"})
		engine._run_frappe_server_script(name, task)
		self.assertEqual(task.data["cleaned"], "x")
		self.assertTrue(task.data["flagged"])


# ─────────────────────────────────────────────────────────────────────────
# Security: the runtime gate (_check_script_permissions) must block the same
# permission-bypass constructs regardless of how they are spelled — not only
# the two literal substrings ("frappe.set_user", "frappe.flags.ignore_permissions")
# the old blocklist looked for. Each test below is a distinct evasion
# technique that a plain substring check would miss but the AST-based
# structural gate (one_bpmn.security.script_validator.deep_inspect_script)
# catches by the *shape* of the code.
# ─────────────────────────────────────────────────────────────────────────

_GETATTR_INDIRECTION = """
fn = getattr(frappe, "set_" + "user")
fn("Administrator")
"""

_STRING_CONCAT_KWARGS = """
doc = frappe.get_doc(context_doctype, context_docname)
key = "ignore_" + "permissions"
doc.save(**{key: True})
"""

_LOCAL_FLAGS_IGNORE_PERMISSIONS = """
frappe.local.flags.ignore_permissions = True
result["done"] = True
"""

_DYNAMIC_IMPORT = """
mod = __import__("os")
mod.system("id")
"""


class TestServerScriptExecutionGateHardening(FrappeTestCase):
	"""Runtime-gate bypass attempts — each must be blocked before exec()."""

	def _script(self, name, body):
		if frappe.db.exists("Server Script", name):
			frappe.delete_doc("Server Script", name, force=True)
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": name,
				"script_type": "API",
				"api_method": name.lower().replace(" ", "_"),
				"script": body,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.db.exists("Server Script", name)
			and frappe.delete_doc("Server Script", name, force=True)
		)
		return name

	def test_getattr_indirection_bypass_is_blocked(self):
		"""getattr(frappe, "set_" + "user") never spells the banned literal
		"frappe.set_user" as a substring, so the old blocklist let it run."""
		name = self._script("ZZ Gate Getattr Indirection", _GETATTR_INDIRECTION)
		engine = _make_script_engine()
		task = _FakeTask({})
		with self.assertRaises(frappe.ValidationError):
			engine._run_frappe_server_script(name, task)

	def test_string_concatenation_kwargs_bypass_is_blocked(self):
		"""**{"ignore_" + "permissions": True} never contains the literal
		substring "frappe.flags.ignore_permissions" the old check looked for."""
		name = self._script("ZZ Gate String Concat Kwargs", _STRING_CONCAT_KWARGS)
		engine = _make_script_engine()
		task = _FakeTask({})
		with self.assertRaises(frappe.ValidationError):
			engine._run_frappe_server_script(name, task)

	def test_frappe_local_flags_ignore_permissions_bypass_is_blocked(self):
		"""frappe.local.flags.ignore_permissions = True is a different attribute
		chain than frappe.flags.ignore_permissions, so the substring check
		(looking for the exact text "frappe.flags.ignore_permissions") missed it."""
		name = self._script(
			"ZZ Gate Local Flags Ignore Permissions", _LOCAL_FLAGS_IGNORE_PERMISSIONS
		)
		engine = _make_script_engine()
		task = _FakeTask({})
		with self.assertRaises(frappe.ValidationError):
			engine._run_frappe_server_script(name, task)

	def test_dynamic_import_bypass_is_blocked(self):
		"""__import__("os") loads a forbidden module dynamically, bypassing an
		`import os` statement a naive check might look for at the top of the file."""
		name = self._script("ZZ Gate Dynamic Import", _DYNAMIC_IMPORT)
		engine = _make_script_engine()
		task = _FakeTask({})
		with self.assertRaises(frappe.ValidationError):
			engine._run_frappe_server_script(name, task)
