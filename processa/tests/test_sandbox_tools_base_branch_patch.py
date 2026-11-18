# Copyright (c) 2026, one-fm and contributors
"""The patch repairs the stored Testing Agent scripts, and a second run changes nothing."""

import unittest
from unittest.mock import MagicMock, patch

from processa.patches.v1_0 import sandbox_tools_fall_back_to_base_branch as p

WRITE_SPEC = 'target_app = x\ngit_branch = (task_data.get("git_branch") or "").strip()\nrun_id = y\n'
RUN_SPECS = '_raw = execute_shape(instance, "run_specs_op", None, {})\nresult.update(_raw)\n'


class TestScriptPatch(unittest.TestCase):
	def _run(self, store):
		def get_all(doctype, filters=None, pluck=None):
			needle = filters["script"][1].strip("%")
			return [n for n, s in store.items() if needle in s]

		with (
			patch.object(p.frappe, "get_all", side_effect=get_all),
			patch.object(p.frappe, "db", new=MagicMock()) as db,
		):
			db.get_value.side_effect = lambda dt, n, f: store[n]
			db.set_value.side_effect = lambda dt, n, f, v: store.update({n: v})
			p.execute()
		return store

	def test_a_tool_script_falls_back_to_base_branch(self):
		store = self._run({"Sandbox Tool: Write Spec": WRITE_SPEC})
		self.assertIn('task_data.get("base_branch")', store["Sandbox Tool: Write Spec"])

	def test_run_specs_passes_its_task_data_to_the_connector_step(self):
		store = self._run({"Testing Agent: Run Specs": RUN_SPECS})
		self.assertIn('execute_shape(instance, "run_specs_op", None, {}, task_data)', store["Testing Agent: Run Specs"])

	def test_running_it_again_changes_nothing(self):
		once = self._run({"a": WRITE_SPEC, "b": RUN_SPECS})
		self.assertEqual(self._run(dict(once)), once)

	def test_a_script_with_neither_line_is_left_alone(self):
		self.assertEqual(self._run({"c": "result['x'] = 1\n"}), {"c": "result['x'] = 1\n"})
