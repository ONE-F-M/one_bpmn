# Copyright (c) 2026, one-fm and contributors
"""Deploying or disabling one map must never switch off a Server Script another
active map still runs — including one reached only through a Call Activity.

Two Software Development versions both call the Orchestrator, so both compiled
specs embed its six scripts. Deploying one version used to treat those six as
"exclusive" to the deactivated sibling and disable them, taking the live
Orchestrator down with it (twice in 24 hours).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import compilation as comp

SHARED = {"Orchestrator Agent: Read the Work Item", "Orchestrator Agent: Record the Outcome"}
OWN_V3 = {"Set PR Link", "Validate Assignee User"}
ONLY_V4 = {"Legacy V4 Only Script"}


def _spec(*script_sets):
	names = set().union(*script_sets)
	return json.dumps({"script_task_extensions": {f"t{i}": {"serverScript": n} for i, n in enumerate(sorted(names))}})


class TestDeployKeepsSharedScriptsEnabled(FrappeTestCase):
	def _deploy_v3(self, other_active_specs):
		"""Deploy SD v3 while sibling v4 is active; both embed the Orchestrator's scripts."""
		model = frappe._dict(name="Software Development v3", process_name="Software Development",
		                     serialized_spec=_spec(OWN_V3, SHARED), version=None)
		siblings = [frappe._dict(name="Software Development v4", version=3, serialized_spec=_spec(SHARED, ONLY_V4))]
		writes = []

		def get_all(doctype, filters=None, fields=None, **kw):
			if filters.get("process_name"):
				return siblings
			return [frappe._dict(serialized_spec=s) for s in other_active_specs]

		def set_value(doctype, name, field, value, *a, **kw):
			writes.append((doctype, name, field, value))

		with patch.object(frappe, "get_all", side_effect=get_all), patch.object(frappe.db, "exists", return_value=True), \
		     patch.object(frappe.db, "set_value", side_effect=set_value):
			# only the map's OWN script tasks come through script_extensions — the bug's blind spot
			comp._activate_deployed_model(model, {f"o{i}": {"serverScript": n} for i, n in enumerate(sorted(OWN_V3))})
		return writes

	def test_scripts_the_deployed_map_reaches_through_a_call_activity_stay_enabled(self):
		writes = self._deploy_v3(other_active_specs=[])
		disabled = {n for d, n, f, v in writes if d == "Server Script" and f == "disabled" and v == 1}
		enabled = {n for d, n, f, v in writes if d == "Server Script" and f == "disabled" and v == 0}
		self.assertFalse(SHARED & disabled, f"shared scripts were disabled: {SHARED & disabled}")
		self.assertTrue(SHARED <= enabled)

	def test_a_script_truly_exclusive_to_the_deactivated_sibling_is_still_disabled(self):
		writes = self._deploy_v3(other_active_specs=[])
		disabled = {n for d, n, f, v in writes if d == "Server Script" and f == "disabled" and v == 1}
		self.assertEqual(disabled, ONLY_V4)

	def test_a_sibling_script_another_active_map_runs_is_kept(self):
		writes = self._deploy_v3(other_active_specs=[_spec(ONLY_V4)])
		disabled = {n for d, n, f, v in writes if d == "Server Script" and f == "disabled" and v == 1}
		self.assertEqual(disabled, set())


class TestScriptsUsedByActiveModels(FrappeTestCase):
	def test_excludes_the_named_models_and_unions_the_rest(self):
		seen = {}

		def get_all(doctype, filters=None, fields=None, **kw):
			seen.update(filters)
			return [frappe._dict(serialized_spec=_spec(SHARED)), frappe._dict(serialized_spec=_spec(OWN_V3))]

		with patch.object(frappe, "get_all", side_effect=get_all):
			used = comp._scripts_used_by_active_models({"Software Development v3", "Software Development v4"})
		self.assertEqual(used, SHARED | OWN_V3)
		self.assertEqual(seen["is_active"], 1)
		self.assertEqual(seen["name"], ["not in", ["Software Development v3", "Software Development v4"]])


class TestRecompileOnlyActiveCallers(FrappeTestCase):
	"""Recompiling the callers of a changed map must not decide which version of
	a process is live. Software Development v3 and v4 both call the Orchestrator;
	recompiling the Orchestrator used to recompile both, and whichever came last
	deactivated the other — reverting a deploy a person had just made."""

	def test_inactive_callers_are_left_alone(self):
		captured = {}

		def get_all(doctype, filters=None, fields=None, **kw):
			captured.update(filters or {})
			return []

		with patch.object(frappe, "get_all", side_effect=get_all):
			comp._recompile_callers_of("orchestrator_agent", "Orchestrator Agent")
		self.assertEqual(captured.get("is_active"), 1)
		self.assertIn("calledElement=\"orchestrator_agent\"", captured["bpmn_xml"][1])

	def test_active_callers_are_still_recompiled(self):
		compiled = []
		with patch.object(frappe, "get_all", return_value=[frappe._dict(name="Software Development v4", process_id="sd")]), \
		     patch.object(comp, "compile_process_model", side_effect=lambda n: compiled.append(n)):
			comp._recompile_callers_of("orchestrator_agent", "Orchestrator Agent")
		self.assertEqual(compiled, ["Software Development v4"])
