# Copyright (c) 2026, one-fm and contributors
"""Current-step derivation for the instance dashboard (list_process_instances)."""

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase


class TestDeriveCurrentStep(FrappeTestCase):
	"""list_process_instances' fallback: name the engine position when no
	user task is waiting — running automations, inner subprocess tasks, or
	an ad-hoc subprocess with everything parked (selector declined/stalled)."""

	def _derive(self, state):
		import json as _json

		from one_bpmn.api.instance_api import _derive_current_step

		return _derive_current_step(_json.dumps(state))

	def test_active_top_level_task(self):
		state = {
			"spec": {"task_specs": {"do_it": {"bpmn_name": "Do It"}}},
			"tasks": {"t1": {"task_spec": "do_it", "state": 16}},
		}
		self.assertEqual(self._derive(state), "Do It")

	def test_active_inner_task_wins_over_container(self):
		state = {
			"spec": {"task_specs": {"Sub_1": {"bpmn_name": "Triage", "typename": "AdHocSubprocess"}}},
			"tasks": {"p1": {"task_spec": "Sub_1", "state": 32}},
			"subprocesses": {"p1": {"tasks": {
				"c1": {"task_spec": "escalate", "state": 16},
				"c2": {"task_spec": "Sub_1.EndJoin", "state": 8},
			}}},
			"subprocess_specs": {"Sub_1": {"task_specs": {"escalate": {"bpmn_name": "Escalate to agent"}}}},
		}
		self.assertEqual(self._derive(state), "Escalate to agent")

	def test_stalled_adhoc_reports_awaiting_selection(self):
		state = {
			"spec": {"task_specs": {"Sub_1": {"bpmn_name": "Triage", "typename": "AdHocSubprocess"}}},
			"tasks": {"p1": {"task_spec": "Sub_1", "state": 32}},
			"subprocesses": {"p1": {"tasks": {"c2": {"task_spec": "Sub_1.EndJoin", "state": 8}}}},
			"subprocess_specs": {"Sub_1": {"task_specs": {}}},
		}
		self.assertEqual(self._derive(state), "Triage — awaiting task selection")

	def test_empty_or_bad_state_is_safe(self):
		from one_bpmn.api.instance_api import _derive_current_step

		self.assertEqual(_derive_current_step(""), "")
		self.assertEqual(_derive_current_step("not json"), "")
