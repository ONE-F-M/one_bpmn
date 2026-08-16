# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Tests for the eval -> AI Agent Run back-link.

``frappe.flags.eval_origin`` used to carry the case name and then throw it away:
observability read the flag only to decide origin="eval". Reviewing an eval
therefore meant filtering AI Agent Run by origin and matching the eval run's time
window by hand. The flag now names both the case and the run, and BOTH creators of
eval-origin runs stamp them — observability.create_ai_run for the agent's own runs
and eval_runner._record_eval_run for the direct call and each judge call.

No LLM calls: runs are created directly through the recording helpers.
"""
from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import (
	make_agent_configuration,
	make_eval_case,
	make_eval_suite,
)
from one_bpmn.agents.eval_runner import (
	EVAL_RUN_DIRECT,
	EVAL_RUN_JUDGE,
	_eval_origin_flag,
	_execute_case,
	_record_eval_run,
)

test_ignore = ["BPMN Process Instance", "AI Eval Suite"]


class _FlagScope:
	"""Set frappe.flags.eval_origin for a block and always restore it, so one
	test's flag can never leak into the next."""

	def __init__(self, value):
		self.value = value

	def __enter__(self):
		self.prev = getattr(frappe.flags, "eval_origin", None)
		frappe.flags.eval_origin = self.value

	def __exit__(self, *exc):
		frappe.flags.eval_origin = self.prev


class TestEvalOriginFlag(FrappeTestCase):
	def test_flag_carries_case_and_run(self):
		case = make_eval_case()
		self.assertEqual(
			_eval_origin_flag(case, "RUN-1"),
			{"eval_case": case.name, "eval_run": "RUN-1"},
		)

	def test_missing_run_is_empty_not_none(self):
		"""'' keeps the Link field NULL without tripping a link check."""
		case = make_eval_case()
		self.assertEqual(_eval_origin_flag(case)["eval_run"], "")


class TestRecordEvalRunStamps(FrappeTestCase):
	"""_record_eval_run covers the Direct call and every llm_judge call — the
	spend an eval incurs outside the agent's own runs."""

	def _record(self, bpmn_id):
		before = set(frappe.get_all("AI Agent Run", pluck="name"))
		# provider / model are Link fields on AI Agent Run, so they are left empty
		# rather than given placeholder names that would fail link validation —
		# _record_eval_run swallows that failure, which would make a broken test
		# look like a missing stamp.
		_record_eval_run(bpmn_id, "", "", frappe.utils.now_datetime(), 10, 5, 0.1, 0.2)
		after = set(frappe.get_all("AI Agent Run", pluck="name"))
		created = after - before
		self.assertEqual(len(created), 1, "expected exactly one AI Agent Run")
		return frappe.get_doc("AI Agent Run", created.pop())

	def _eval_run(self, suite):
		run = frappe.get_doc({
			"doctype": "AI Eval Run", "suite": suite, "status": "Running",
			"backend": "live", "started_at": frappe.utils.now_datetime(),
		})
		run.flags.ignore_links = True
		return run.insert(ignore_permissions=True).name

	def test_stamps_case_and_run_from_the_flag(self):
		suite = make_eval_suite()
		case = make_eval_case(suite=suite.name)
		eval_run = self._eval_run(suite.name)
		with _FlagScope({"eval_case": case.name, "eval_run": eval_run}):
			run = self._record(EVAL_RUN_JUDGE)
		self.assertEqual(run.eval_case, case.name)
		self.assertEqual(run.eval_run, eval_run)
		self.assertEqual(run.origin, "eval")

	def test_direct_call_is_stamped_too(self):
		suite = make_eval_suite()
		case = make_eval_case(suite=suite.name)
		eval_run = self._eval_run(suite.name)
		with _FlagScope({"eval_case": case.name, "eval_run": eval_run}):
			run = self._record(EVAL_RUN_DIRECT)
		self.assertEqual(run.eval_case, case.name)

	def test_no_flag_leaves_the_links_empty(self):
		with _FlagScope(None):
			run = self._record(EVAL_RUN_JUDGE)
		self.assertFalse(run.eval_case)
		self.assertFalse(run.eval_run)

	def test_a_non_dict_flag_does_not_raise(self):
		"""Any caller can set the flag; a bad shape must not break recording."""
		with _FlagScope("truthy-but-not-a-dict"):
			run = self._record(EVAL_RUN_JUDGE)
		self.assertFalse(run.eval_case)


class TestCreateAiRunStamps(FrappeTestCase):
	"""observability.create_ai_run records the agent's own runs — the ones that
	carry the steps and tool calls."""

	def _instance(self):
		doc = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_id": f"link-{frappe.generate_hash(length=6)}",
			"status": "Active",
		})
		doc.flags.ignore_mandatory = True
		return doc.insert(ignore_permissions=True, ignore_mandatory=True)

	def _create(self):
		from one_bpmn.agents.executor import ExecutorConfig
		from one_bpmn.agents.observability import create_ai_run

		# provider_name / model land in Link fields, so they stay empty here.
		config = ExecutorConfig(
			backend="direct_api", provider_name="", model="",
			system_prompt="", user_prompt="hi",
		)
		run = create_ai_run(self._instance(), "ai_agent_task", "task", config)
		self.assertFalse(getattr(run, "stub", False), "create_ai_run fell back to a stub")
		return run

	def test_stamps_case_and_run(self):
		suite = make_eval_suite()
		case = make_eval_case(suite=suite.name)
		eval_run = frappe.get_doc({
			"doctype": "AI Eval Run", "suite": suite.name, "status": "Running",
			"backend": "live", "started_at": frappe.utils.now_datetime(),
		})
		eval_run.flags.ignore_links = True
		eval_run.insert(ignore_permissions=True)
		with _FlagScope({"eval_case": case.name, "eval_run": eval_run.name}):
			run = self._create()
		self.assertEqual(run.origin, "eval")
		self.assertEqual(run.eval_case, case.name)
		self.assertEqual(run.eval_run, eval_run.name)

	def test_production_run_is_not_stamped(self):
		with _FlagScope(None):
			run = self._create()
		self.assertEqual(run.origin, "production")
		self.assertFalse(run.eval_case)
		self.assertFalse(run.eval_run)


class TestExecuteCaseFlagLifecycle(FrappeTestCase):
	def test_flag_is_set_for_the_whole_case_and_restored(self):
		"""Set around the WHOLE case, not just the agent call: the judge calls
		made while evaluating assertions must be attributed to the same case."""
		cfg = make_agent_configuration()
		suite = make_eval_suite(agent_configuration=cfg.name, eval_type="Direct")
		case = make_eval_case(suite=suite.name)

		seen = {}

		def fake_direct(_cfg, _case):
			seen["flag"] = getattr(frappe.flags, "eval_origin", None)
			return "out", {"prompt_tokens": 0, "completion_tokens": 0, "tokens": 0, "cost": 0}

		with patch("one_bpmn.agents.eval_runner._run_direct_eval", new=fake_direct):
			_execute_case(case, "RUN-77")

		self.assertEqual(seen["flag"], {"eval_case": case.name, "eval_run": "RUN-77"})
		self.assertIsNone(getattr(frappe.flags, "eval_origin", None))

	def test_flag_restored_even_when_the_case_raises(self):
		cfg = make_agent_configuration()
		suite = make_eval_suite(agent_configuration=cfg.name, eval_type="Direct")
		case = make_eval_case(suite=suite.name)

		def boom(_cfg, _case):
			raise RuntimeError("kaboom")

		with patch("one_bpmn.agents.eval_runner._run_direct_eval", new=boom):
			# _execute_case swallows the failure into an Error result row.
			row = _execute_case(case, "RUN-88")

		self.assertEqual(row["status"], "Error")
		self.assertIsNone(getattr(frappe.flags, "eval_origin", None))
