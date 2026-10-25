# Copyright (c) 2026, one-fm and contributors
"""The AI Queue Wait report gives each agent's p90 queue wait over the last days and whether it is under 5 seconds."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.report.ai_queue_wait import ai_queue_wait as report

MODULE = "one_bpmn.one_bpmn.report.ai_queue_wait.ai_queue_wait"


def _runs(agent, waits):
	return [frappe._dict(agent_configuration=agent, queue_wait_ms=wait) for wait in waits]


class TestAiQueueWaitReport(FrappeTestCase):
	def _execute(self, rows, filters=None):
		with patch(f"{MODULE}.frappe.get_list", return_value=rows) as get_list:
			columns, data = report.execute(filters)
		return columns, data, get_list

	def test_each_agent_gets_a_row_with_its_p90(self):
		rows = _runs("docu_agent", [100 * n for n in range(1, 11)]) + _runs("prosally_agent", [178720, 94731])
		_, data, _ = self._execute(rows)
		by_agent = {row["agent"]: row for row in data}
		self.assertEqual(by_agent["docu_agent"]["runs"], 10)
		self.assertEqual(by_agent["docu_agent"]["p90_ms"], 910)
		self.assertEqual(by_agent["docu_agent"]["max_ms"], 1000)
		self.assertAlmostEqual(by_agent["prosally_agent"]["p90_ms"], 170321.1, places=1)

	def test_an_agent_is_within_target_only_when_its_p90_is_under_five_seconds(self):
		rows = _runs("fast", [100, 200, 300]) + _runs("slow", [1000, 9000, 9500])
		_, data, _ = self._execute(rows)
		by_agent = {row["agent"]: row["within_target"] for row in data}
		self.assertEqual(by_agent, {"fast": 1, "slow": 0})

	def test_a_single_run_is_its_own_p90(self):
		_, data, _ = self._execute(_runs("lonely", [4000]))
		self.assertEqual((data[0]["p90_ms"], data[0]["within_target"]), (4000, 1))

	def test_no_runs_give_no_rows(self):
		self.assertEqual(self._execute([])[1], [])

	def test_the_window_is_a_week_of_runs_unless_asked_otherwise(self):
		_, _, get_list = self._execute([])
		filters = get_list.call_args.kwargs["filters"]
		self.assertIn("started_at", filters)
		self.assertEqual(filters["status"], ["in", ["Success", "Error"]])
		self.assertNotIn("origin", filters)
		_, _, asked = self._execute([], {"days": 1, "origin": "production"})
		self.assertEqual(asked.call_args.kwargs["filters"]["origin"], "production")
