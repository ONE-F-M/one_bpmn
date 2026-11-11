# Copyright (c) 2026, one-fm and contributors
"""Where an element's time goes: step labels, the time split, and its slowest runs.

Every test uses its own model and bpmn_ids, so rows other suites leave behind cannot change the figures.

	bench run-tests --module one_bpmn.ai_agent_observability.tests.test_insights_step_latency
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.ai_agent_observability.reports.performance import step_kind
from one_bpmn.api.insights import get_element_runs, get_step_latency_report

FROM, TO = "2026-09-01", "2026-09-07"


class TestStepKind(FrappeTestCase):
	def test_each_role_gets_its_label(self):
		self.assertEqual(step_kind("tool", None, ["a", "b"]), "tool: a, b")
		self.assertEqual(step_kind("assistant", {"tool": "x"}, [], "m"), "sub-call: x")
		self.assertEqual(step_kind("assistant", None, [], "m"), "model call: m")
		self.assertEqual(step_kind("system", None, []), "prompt: system")


class TestStepLatencyReport(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.maps = []
		for _index in range(2):
			suffix = frappe.generate_hash(length=6)
			cls.maps.append(
				frappe.get_doc(
					{
						"doctype": "BPMN Process Model",
						"title": f"_Test Step Latency {suffix}",
						"process_id": f"_steplat_{suffix}",
						"version": 1,
					}
				)
				.insert()
				.name
			)

	def setUp(self):
		frappe.set_user("Administrator")
		tag = frappe.generate_hash(length=6)
		self.model = f"lat-model-{tag}"
		self.element = f"steplat_task_{tag}"

	def _run(self, latency=9000, status="Success", process_model=None, day="2026-09-02", **extra):
		return frappe.get_doc(
			{
				"doctype": "AI Agent Run",
				"bpmn_id": self.element,
				"process_model": process_model or self.maps[0],
				"model": self.model,
				"status": status,
				"agent_latency_ms": latency,
				"started_at": f"{day} 10:00:00",
				**extra,
			}
		).insert()

	def _step(self, run, index, role, kind, latency, content="answer", tools=()):
		frappe.get_doc(
			{
				"doctype": "AI Agent Step",
				"run": run.name,
				"step_index": index,
				"role": role,
				"step_kind": kind,
				"latency_ms": latency,
				"content": content,
				"tool_calls": [{"tool_name": name, "status": "Success"} for name in tools],
			}
		).insert()

	def _four_kinds(self, run, stored=True):
		self._step(run, 0, "system", "prompt" if stored else "", 0, "You answer.")
		self._step(
			run,
			1,
			"assistant",
			"sub_call" if stored else "",
			5000,
			"[sub-call: lat_test_review via lat-model]",
		)
		self._step(run, 2, "tool", "tool_turn" if stored else "", 3000, tools=["lat_test_tool"])
		self._step(run, 3, "assistant", "model_call" if stored else "", 1000)

	def _key(self, process_model=None):
		return f"{self.element}|{process_model or self.maps[0]}|{self.model}"

	def _report(self, **kwargs):
		return get_step_latency_report(from_date=FROM, to_date=TO, origin="all", model=self.model, **kwargs)

	def test_rows_and_split_cover_every_kind_but_prompts(self):
		self._four_kinds(self._run())

		report = self._report()

		self.assertEqual(
			[(r["step_kind"], r["total_ms"], r["max_ms"]) for r in report["rows"]],
			[
				("sub-call: lat_test_review", 5000, 5000),
				("tool: lat_test_tool", 3000, 3000),
				(f"model call: {self.model}", 1000, 1000),
			],
		)
		split = report["split"]
		self.assertEqual(
			(split["model_share"], split["tool_share"], split["sub_call_share"]), (11.1, 33.3, 55.6)
		)
		self.assertEqual(
			(split["model_avg_ms"], split["tool_avg_ms"], split["sub_call_avg_ms"]), (1000, 3000, 5000)
		)

	def test_steps_without_a_stored_kind_are_classified(self):
		self._four_kinds(self._run(), stored=False)

		report = self._report()

		self.assertEqual(
			[r["step_kind"] for r in report["rows"]],
			["sub-call: lat_test_review", "tool: lat_test_tool", f"model call: {self.model}"],
		)
		self.assertEqual(report["split"]["sub_call_share"], 55.6)

	def test_a_key_narrows_the_split_and_rows_to_one_element(self):
		self._four_kinds(self._run())
		other = self._run(process_model=self.maps[1])
		self._step(other, 0, "tool", "tool_turn", 7000, tools=["other_tool"])

		report = self._report(key=self._key(), limit=3)

		self.assertNotIn("tool: other_tool", [r["step_kind"] for r in report["rows"]])
		self.assertEqual(len(report["rows"]), 3)
		self.assertEqual(report["split"]["tool_share"], 33.3)

	def test_element_runs_page_the_slowest_runs_above_a_threshold(self):
		slow = [self._run(31400 + index * 100) for index in range(11)]
		self._run(31399)
		self._run(40000, status="Running")
		self._run(50000, parent_run=slow[0].name)
		self._run(50000, day="2026-08-20")
		self._step(slow[-1], 0, "assistant", "model_call", 400)
		self._step(slow[-1], 1, "tool", "tool_turn", 900, tools=["slow_tool"])

		first = get_element_runs(self._key(), FROM, TO, origin="all", min_agent_latency_ms=31400, limit=3)
		rest = get_element_runs(
			self._key(), FROM, TO, origin="all", min_agent_latency_ms=31400, limit=10, offset=3
		)

		self.assertEqual(first["total"], 11)
		self.assertEqual([r["agent_latency_ms"] for r in first["runs"]], [32400, 32300, 32200])
		top = first["runs"][0]
		self.assertEqual((top["status"], top["step_count"]), ("Success", 2))
		self.assertEqual(top["slowest_step"], {"label": "tool: slow_tool", "latency_ms": 900})
		self.assertEqual(len(rest["runs"]), 8)
		self.assertEqual(rest["runs"][-1]["agent_latency_ms"], 31400)

	def test_element_runs_keep_errors_and_honour_header_filters(self):
		self._run(5000, status="Error", error_code="lat_timeout")
		self._run(6000, status="Error", error_code="lat_timeout", process_model=self.maps[1])

		runs = get_element_runs(
			self._key(), FROM, TO, origin="all", model=self.model, process_model=self.maps[0]
		)["runs"]
		other_model = get_element_runs(self._key(), FROM, TO, origin="all", model=f"{self.model}-other")

		self.assertEqual([(r["status"], r["error_code"]) for r in runs], [("Error", "lat_timeout")])
		self.assertEqual(other_model["total"], 0)

	def test_a_malformed_key_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			get_element_runs("only|two", FROM, TO)
		with self.assertRaises(frappe.ValidationError):
			get_step_latency_report(from_date=FROM, to_date=TO, key="a|b|c|d")

	def test_a_user_without_system_manager_is_refused(self):
		email = f"steplat-{frappe.generate_hash(length=6)}@example.com"
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Steps", "send_welcome_email": 0}
		).insert()
		self.addCleanup(lambda: frappe.set_user("Administrator"))
		frappe.set_user(email)

		# frappe.only_for is a no-op while in_test is set, so the guard cannot fire unless it is cleared.
		frappe.flags.in_test = False
		try:
			with self.assertRaises(frappe.PermissionError):
				get_step_latency_report(from_date=FROM, to_date=TO)
			with self.assertRaises(frappe.PermissionError):
				get_element_runs(self._key(), FROM, TO)
		finally:
			frappe.flags.in_test = True
