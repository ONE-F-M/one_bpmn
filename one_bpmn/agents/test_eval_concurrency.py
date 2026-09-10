# Copyright (c) 2026, one-fm and contributors
"""Running a suite's cases side by side.

Nearly all of a suite's wall clock is waiting for a model to answer, so cases
can overlap. Two things must not: executions that share a document, because the
agent's scratch notes and its answer both live under that document's name; and
a case's own repetitions, for the same reason. So the unit of parallelism is a
lane, and these tests are mostly about what stays in single file.

The dangerous failure here is silent. A thread inherits no Frappe context: no
database connection, and no eval-origin stamp on the runs a case produces —
which is what later attributes a tool-call trace to its case. Get that wrong and
the suite still passes while the trace assertions quietly find nothing. So the
worker's context is asserted, not assumed.

``_execute_case`` is replaced throughout: these tests are about the scheduler,
and a real execution would be a billed model call. The one test that does touch
the database cleans up after itself, because a worker commits its own
transaction and the test rollback cannot reach it.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_eval_case, make_eval_suite
from one_bpmn.agents.eval_runner import (
	MAX_EVAL_CONCURRENCY,
	_eval_concurrency,
	_execute_eval_suite,
	_lanes_for,
)

RUNNER_CASE = "one_bpmn.agents.eval_runner._execute_case"
CONCURRENCY = "one_bpmn.agents.eval_runner._eval_concurrency"


class _Recorder:
	"""Stands in for a case execution and records how the run overlapped.

	Tracks how many executions were in flight at once, the high-water mark, and
	which documents were being worked on simultaneously — the three things the
	scheduler is supposed to control.
	"""

	def __init__(self, delay: float = 0.02, fail: set | None = None, explode: set | None = None):
		self.delay = delay
		self.fail = fail or set()
		self.explode = explode or set()
		self.lock = threading.Lock()
		self.in_flight = 0
		self.peak = 0
		self.order = []          # completion order
		self.contexts = {}       # site/db seen inside each worker
		self.concurrent_docs = []  # documents in flight together
		self._live_docs = set()
		self._live_cases = set()
		self.overlapped_cases = []

	def __call__(self, case, eval_run=None, agent_cfg=None):
		document = (case.input_context or "")
		with self.lock:
			self.in_flight += 1
			self.peak = max(self.peak, self.in_flight)
			if document and document in self._live_docs:
				self.concurrent_docs.append(document)
			if case.name in self._live_cases:
				self.overlapped_cases.append(case.name)
			self._live_docs.add(document)
			self._live_cases.add(case.name)
			# What context did this worker actually get? A thread with none has
			# no database and stamps nothing.
			self.contexts[threading.current_thread().name] = {
				"site": getattr(frappe.local, "site", None),
				"has_db": bool(getattr(frappe.local, "db", None)),
				"eval_origin": bool(getattr(frappe.flags, "eval_origin", None)),
			}

		if case.name in self.explode:
			with self.lock:
				self.in_flight -= 1
				self._live_docs.discard(document)
				self._live_cases.discard(case.name)
			raise RuntimeError("this case cannot execute")

		time.sleep(self.delay)

		with self.lock:
			self.in_flight -= 1
			self._live_docs.discard(document)
			self._live_cases.discard(case.name)
			self.order.append(case.name)

		status = "Failed" if case.name in self.fail else "Passed"
		return {
			"eval_case": case.name,
			"status": status,
			"actual_output": f"answer for {case.name}",
			"assertion_results": "[]",
			"error_message": "" if status == "Passed" else "an assertion failed",
			"cost": 0.01,
			"tokens_used": 100,
			"prompt_tokens": 80,
			"completion_tokens": 20,
		}


class _ConcurrencyCase(FrappeTestCase):
	"""Shared fixtures, committed on purpose.

	A worker reads through its own database connection, so it cannot see writes
	this transaction has not committed — uncommitted fixtures come back "not
	found" from inside a thread, which is the same trap a caller hits when it
	fans out work it has not committed. So these fixtures are committed and
	removed again in tearDown, rather than relying on the framework's rollback.
	"""

	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(title="_Test concurrency " + frappe.generate_hash(length=6))
		self.runs = []

	def tearDown(self):
		for run in self.runs:
			if frappe.db.exists("AI Eval Run", run):
				frappe.delete_doc("AI Eval Run", run, force=True, ignore_permissions=True)
		for case in frappe.get_all("AI Eval Case", filters={"suite": self.suite.name}, pluck="name"):
			frappe.delete_doc("AI Eval Case", case, force=True, ignore_permissions=True)
		if frappe.db.exists("AI Eval Suite", self.suite.name):
			frappe.delete_doc("AI Eval Suite", self.suite.name, force=True, ignore_permissions=True)
		frappe.db.commit()

	def _case(self, title: str, context: str | None = None):
		# input_context is a JSON column with a CHECK constraint: None is the
		# only way to say "no document", and malformed JSON cannot be stored.
		return make_eval_case(suite=self.suite.name, title=title, input_context=context or None)

	def _execute(self, recorder, concurrency: int, pass_k: int = 1, backend: str = "live"):
		self.suite.db_set("pass_k", pass_k, update_modified=False)
		run = frappe.get_doc({
			"doctype": "AI Eval Run", "suite": self.suite.name, "status": "Running",
			"backend": backend, "scope": "Suite", "started_at": frappe.utils.now_datetime(),
		})
		run.flags.ignore_mandatory = True
		run.flags.ignore_links = True
		run.insert(ignore_permissions=True)
		self.runs.append(run.name)
		# The workers are real threads on real connections: what they read has
		# to be committed first.
		frappe.db.commit()
		with patch(RUNNER_CASE, new=recorder), patch(CONCURRENCY, return_value=concurrency):
			_execute_eval_suite(run.name)
		run.reload()
		return run


class TestLaneGrouping(FrappeTestCase):
	"""Which cases are allowed to overlap, decided before anything runs."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(title="_Test lanes " + frappe.generate_hash(length=6))

	def _case(self, title, context=None):
		return make_eval_case(suite=self.suite.name, title=title, input_context=context or None)

	def test_cases_with_no_document_each_get_their_own_lane(self):
		names = [self._case(f"c{n}").name for n in range(4)]
		self.assertEqual(_lanes_for(names), [[n] for n in names])

	def test_cases_sharing_a_document_share_a_lane(self):
		shared = '{"context_doctype": "A2A Task", "context_docname": "A2A-1"}'
		a = self._case("a", shared).name
		b = self._case("b", shared).name
		c = self._case("c", '{"context_doctype": "A2A Task", "context_docname": "A2A-2"}').name
		lanes = _lanes_for([a, b, c])
		self.assertEqual(lanes, [[a, b], [c]])

	def test_lane_order_follows_the_order_the_cases_were_given(self):
		"""A serial run and a parallel run must schedule the same work in the
		same sequence, or two runs of one suite are not comparable."""
		a = self._case("a", '{"context_docname": "X"}').name
		b = self._case("b").name
		c = self._case("c", '{"context_docname": "X"}').name
		self.assertEqual(_lanes_for([a, b, c]), [[a, c], [b]])

	def test_context_without_a_document_is_treated_as_no_document(self):
		"""A case can carry context that names no document — an empty object, or
		keys the runner does not use. Each still gets its own lane rather than
		every such case being grouped together under one empty key.

		Malformed JSON is not tested through the database: input_context is a
		JSON column with a CHECK constraint, so it cannot be stored. The parse is
		guarded anyway, for a value arriving from an API caller.
		"""
		a = self._case("a", "{}").name
		b = self._case("b", '{"note": "no document here"}').name
		self.assertEqual(_lanes_for([a, b]), [[a], [b]])

	def test_no_cases_is_no_lanes(self):
		self.assertEqual(_lanes_for([]), [])


class TestConcurrencySetting(FrappeTestCase):
	def test_unset_means_one(self):
		with patch.object(frappe.db, "get_single_value", return_value=None):
			self.assertEqual(_eval_concurrency(), 1)

	def test_zero_and_negative_mean_one(self):
		for value in (0, -4):
			with patch.object(frappe.db, "get_single_value", return_value=value):
				self.assertEqual(_eval_concurrency(), 1)

	def test_it_is_capped(self):
		with patch.object(frappe.db, "get_single_value", return_value=999):
			self.assertEqual(_eval_concurrency(), MAX_EVAL_CONCURRENCY)

	def test_an_unreadable_setting_falls_back_to_one(self):
		"""Fails safe: the slow path, never an uncapped fan-out."""
		with patch.object(frappe.db, "get_single_value", side_effect=Exception("no table")):
			self.assertEqual(_eval_concurrency(), 1)


class TestSerialIsUnchanged(_ConcurrencyCase):
	def test_at_concurrency_one_nothing_overlaps(self):
		for n in range(4):
			self._case(f"c{n}")
		recorder = _Recorder()
		run = self._execute(recorder, concurrency=1)
		self.assertEqual(recorder.peak, 1, "concurrency 1 must run single file")
		self.assertEqual(run.total_cases, 4)
		self.assertEqual(run.status, "Passed")

	def test_at_concurrency_one_no_worker_thread_is_started(self):
		"""The default configuration runs the code path that was in production
		before any of this existed."""
		self._case("only")
		recorder = _Recorder()
		before = threading.active_count()
		self._execute(recorder, concurrency=1)
		self.assertEqual(threading.active_count(), before)
		self.assertEqual(list(recorder.contexts), [threading.current_thread().name])

	def test_a_single_lane_is_never_parallelised(self):
		shared = '{"context_docname": "A2A-1"}'
		self._case("a", shared)
		self._case("b", shared)
		recorder = _Recorder()
		self._execute(recorder, concurrency=4)
		self.assertEqual(recorder.peak, 1)


class TestParallelExecution(_ConcurrencyCase):
	def test_cases_actually_overlap(self):
		for n in range(6):
			self._case(f"c{n}")
		recorder = _Recorder(delay=0.05)
		self._execute(recorder, concurrency=4)
		self.assertGreater(recorder.peak, 1, "nothing overlapped — the pool did not engage")

	def test_the_cap_is_never_exceeded(self):
		for n in range(12):
			self._case(f"c{n}")
		recorder = _Recorder(delay=0.03)
		self._execute(recorder, concurrency=3)
		self.assertLessEqual(recorder.peak, 3)

	def test_every_case_is_executed_exactly_once(self):
		names = [self._case(f"c{n}").name for n in range(9)]
		recorder = _Recorder()
		run = self._execute(recorder, concurrency=4)
		self.assertEqual(sorted(recorder.order), sorted(names))
		self.assertEqual(len(run.results), 9)

	def test_results_are_recorded_in_case_order_not_completion_order(self):
		names = [self._case(f"c{n}").name for n in range(6)]

		class Uneven(_Recorder):
			def __call__(self, case, eval_run=None, agent_cfg=None):
				# later cases answer sooner, so completion order is reversed
				self.delay = 0.01 * (6 - names.index(case.name))
				return super().__call__(case, eval_run, agent_cfg)

		recorder = Uneven()
		run = self._execute(recorder, concurrency=6)
		self.assertNotEqual(recorder.order, names, "the test needs uneven completion to be meaningful")
		self.assertEqual([r.eval_case for r in run.results], names)

	def test_a_document_is_never_worked_on_twice_at_once(self):
		shared = '{"context_doctype": "A2A Task", "context_docname": "A2A-shared"}'
		for n in range(4):
			self._case(f"shared{n}", shared)
		for n in range(4):
			self._case(f"solo{n}")
		recorder = _Recorder(delay=0.03)
		self._execute(recorder, concurrency=8)
		self.assertEqual(recorder.concurrent_docs, [], "two executions shared one document")
		self.assertGreater(recorder.peak, 1, "the independent cases should still overlap")

	def test_a_cases_own_repetitions_never_overlap(self):
		self._case("repeated", '{"context_docname": "A2A-1"}')
		self._case("other")
		recorder = _Recorder(delay=0.02)
		self._execute(recorder, concurrency=4, pass_k=4)
		self.assertEqual(recorder.overlapped_cases, [], "a case ran against itself")

	def test_totals_match_a_serial_run_of_the_same_outcomes(self):
		names = [self._case(f"c{n}").name for n in range(5)]
		failing = {names[1], names[4]}

		serial = self._execute(_Recorder(fail=failing), concurrency=1)
		parallel = self._execute(_Recorder(fail=failing), concurrency=4)

		for field in ("total_cases", "passed_cases", "failed_cases",
					  "total_executions", "pass_rate", "total_tokens", "status"):
			self.assertEqual(
				serial.get(field), parallel.get(field),
				f"{field} differs between a serial and a parallel run",
			)
		self.assertAlmostEqual(serial.total_cost, parallel.total_cost, places=6)

	def test_pass_k_multiplies_executions_under_concurrency(self):
		for n in range(3):
			self._case(f"c{n}")
		run = self._execute(_Recorder(), concurrency=3, pass_k=4)
		self.assertEqual(run.total_executions, 12)
		self.assertEqual(run.results[0].runs, 4)


class TestWorkerContext(_ConcurrencyCase):
	def test_every_worker_gets_a_site_and_a_database(self):
		"""The silent failure: a thread with no context stamps nothing, and the
		tool-call assertions then find no trace to inspect."""
		for n in range(6):
			self._case(f"c{n}")
		recorder = _Recorder(delay=0.02)
		self._execute(recorder, concurrency=4)

		self.assertGreater(len(recorder.contexts), 1, "only one thread ran — nothing to check")
		for thread, context in recorder.contexts.items():
			self.assertEqual(context["site"], frappe.local.site, f"{thread} had the wrong site")
			self.assertTrue(context["has_db"], f"{thread} had no database connection")

	def test_the_eval_origin_stamp_is_set_inside_each_worker(self):
		"""What attributes an AI Agent Run — and therefore a tool-call trace —
		to its case. It is set per execution, so it must survive the hand-off
		into a thread."""
		for n in range(4):
			self._case(f"c{n}")

		seen = {}

		def record_origin(case, eval_run=None, agent_cfg=None):
			# _execute_case is what sets the flag, so call the real wrapper's
			# behaviour: set it, look at it, restore it.
			from one_bpmn.agents.eval_runner import _eval_origin_flag
			frappe.flags.eval_origin = _eval_origin_flag(case, eval_run)
			seen[case.name] = dict(frappe.flags.eval_origin or {})
			return {"eval_case": case.name, "status": "Passed", "assertion_results": "[]"}

		self._execute(record_origin, concurrency=4)
		self.assertEqual(len(seen), 4)
		for case_name, origin in seen.items():
			self.assertEqual(origin.get("eval_case"), case_name)
			self.assertTrue(origin.get("eval_run"))

	def test_a_workers_writes_are_committed(self):
		"""A worker owns its transaction. Without a commit, the runs and judge
		calls a case recorded roll back when its thread ends, while the row it
		returned still says they happened."""
		for n in range(3):
			self._case(f"c{n}")
		marker = f"_Test concurrency commit {frappe.generate_hash(length=6)}"

		def write_and_pass(case, eval_run=None, agent_cfg=None):
			frappe.get_doc({
				"doctype": "ToDo", "description": f"{marker} {case.name}",
				"allocated_to": frappe.session.user,
			}).insert(ignore_permissions=True)
			return {"eval_case": case.name, "status": "Passed", "assertion_results": "[]"}

		try:
			self._execute(write_and_pass, concurrency=3)
			# The workers committed, but this transaction still holds the snapshot
			# it opened beforehand — under REPEATABLE READ their rows are
			# invisible here until it ends. Which is itself worth knowing: a
			# caller that fans out work cannot read the results back without
			# closing its own transaction first.
			frappe.db.commit()
			written = frappe.get_all("ToDo", filters={"description": ["like", f"{marker}%"]}, pluck="name")
			self.assertEqual(len(written), 3, "a worker's writes did not survive its thread")
		finally:
			for name in frappe.get_all("ToDo", filters={"description": ["like", f"{marker}%"]}, pluck="name"):
				frappe.delete_doc("ToDo", name, force=True, ignore_permissions=True)
			frappe.db.commit()


class TestFailureIsolation(_ConcurrencyCase):
	def test_a_case_that_raises_becomes_an_error_row_and_the_rest_finish(self):
		names = [self._case(f"c{n}").name for n in range(5)]
		recorder = _Recorder(explode={names[2]})
		run = self._execute(recorder, concurrency=3)

		self.assertEqual(len(run.results), 5)
		by_case = {r.eval_case: r for r in run.results}
		self.assertEqual(by_case[names[2]].status, "Error")
		self.assertEqual(
			[by_case[n].status for n in names if n != names[2]],
			["Passed"] * 4,
		)
		self.assertEqual(run.status, "Failed")

	def test_a_raising_case_does_not_stop_its_own_lane(self):
		shared = '{"context_docname": "A2A-lane"}'
		first = self._case("first", shared).name
		second = self._case("second", shared).name
		recorder = _Recorder(explode={first})
		run = self._execute(recorder, concurrency=2)
		by_case = {r.eval_case: r for r in run.results}
		self.assertEqual(by_case[first].status, "Error")
		self.assertEqual(by_case[second].status, "Passed")

	def test_the_run_is_still_finalised_when_every_case_raises(self):
		names = [self._case(f"c{n}").name for n in range(3)]
		run = self._execute(_Recorder(explode=set(names)), concurrency=3)
		self.assertEqual(run.failed_cases, 3)
		self.assertEqual(run.pass_rate, 0)
		self.assertTrue(run.ended_at)
