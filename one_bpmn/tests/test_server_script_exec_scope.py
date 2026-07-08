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
