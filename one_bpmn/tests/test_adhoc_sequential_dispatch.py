# Copyright (c) 2026, one-fm and contributors
# WI-001350 (1-03): Ad-hoc subprocess decide/execute dispatch loop with
# sequential enforcement.
#
# SpiffWorkflow readies EVERY unconditional no-input inner task at ad-hoc
# subprocess entry and has no working sequential mode (AdHocSubprocessSpec's
# `parallel` argument is stored but never read). one_bpmn enforces
# one-task-at-a-time in engine.do_engine_steps_gated(): exactly one "head"
# may be READY/STARTED/WAITING; the rest are parked FUTURE and promoted in
# diagram-XML order.

from __future__ import annotations

import json
from pathlib import Path

from frappe.tests.utils import FrappeTestCase
from SpiffWorkflow.util.task import TaskState

from one_bpmn.one_bpmn import engine

FIXTURES = Path(__file__).parent / "fixtures"

ACTIVE = TaskState.READY | TaskState.STARTED | TaskState.WAITING


def _build(fixture, process_id, initial_data=None):
	xml = (FIXTURES / fixture).read_text()
	spec_dict, sp_specs = engine.parse_bpmn(xml, process_id)
	return engine.create_workflow(spec_dict, sp_specs, initial_data=initial_data)


def _adhoc(wf):
	subprocesses = engine._adhoc_subworkflows(wf)
	return subprocesses[0] if subprocesses else None


def _states(sp):
	return {
		t.task_spec.name: TaskState.get_name(t.state)
		for t in sp.get_tasks(skip_subprocesses=True)
		if t.task_spec.name.startswith(("task_", "script_"))
	}


def _drive(wf, did_complete_task=None, did_complete_adhoc_task=None):
	"""
	Mimic BPMNProcessInstance._run_engine's pass structure: gated engine
	steps, then complete non-manual STARTED tasks (script/service tasks end
	up STARTED because FrappeScriptEngine.execute returns None), repeat.
	"""
	for _ in range(20):
		engine.do_engine_steps_gated(
			wf,
			did_complete_task=did_complete_task,
			did_complete_adhoc_task=did_complete_adhoc_task,
		)
		started = [
			t
			for t in wf.get_tasks(state=TaskState.STARTED)
			if not getattr(t.task_spec, "manual", False)
		]
		if not started:
			break
		for task in started:
			task.complete()


def _complete_manual(wf, name, data=None):
	task = next(t for t in engine.get_ready_user_tasks(wf) if t.task_spec.name == name)
	if data:
		task.data.update(data)
	task.run()
	_drive(wf)
	return task


class TestAdhocSequentialDispatch(FrappeTestCase):
	# ── Scenario 1: only one head activated even though Spiff readied all ──

	def test_single_task_active_at_entry(self):
		wf = _build("adhoc_sequential.bpmn", "Process_AdhocSequential", {"done": False})
		_drive(wf)
		sp = _adhoc(wf)
		states = _states(sp)
		self.assertEqual(states["task_a"], "READY")
		self.assertEqual(states["task_b"], "FUTURE")
		self.assertEqual(states["task_c"], "FUTURE")

	# ── Scenario 6: only the active head appears in ready_human_tasks ──

	def test_ready_human_tasks_gated(self):
		wf = _build("adhoc_sequential.bpmn", "Process_AdhocSequential", {"done": False})
		_drive(wf)
		ready = {t.task_spec.name for t in engine.get_ready_user_tasks(wf)}
		self.assertEqual(ready, {"task_a"})

	# ── Scenario 2: next task promoted in diagram order, one at a time ──

	def test_promotion_in_diagram_order(self):
		wf = _build("adhoc_sequential.bpmn", "Process_AdhocSequential", {"done": False})
		_drive(wf)

		_complete_manual(wf, "task_a")
		ready = {t.task_spec.name for t in engine.get_ready_user_tasks(wf)}
		self.assertEqual(ready, {"task_b"})

		_complete_manual(wf, "task_b")
		ready = {t.task_spec.name for t in engine.get_ready_user_tasks(wf)}
		self.assertEqual(ready, {"task_c"})

	def test_script_heads_run_one_at_a_time_in_order(self):
		wf = _build("adhoc_script_order.bpmn", "Process_AdhocScripts", {"done": False})
		execution_order = []
		violations = []

		def record(task):
			if task.task_spec.name.startswith("script_"):
				execution_order.append(task.task_spec.name)
				sp = _adhoc(wf)
				if sp is not None:
					active = [
						t
						for t in engine.adhoc_head_tasks(sp)
						if t.state & ACTIVE and t.task_spec.name != task.task_spec.name
					]
					if active:
						violations.append((task.task_spec.name, [t.task_spec.name for t in active]))

		_drive(wf, did_complete_task=record)
		self.assertEqual(execution_order, ["script_a", "script_b", "script_c"])
		# At no point was a second head active while one ran.
		self.assertEqual(violations, [])
		# Subprocess completed once script_c set done=True; whole flow finished.
		self.assertTrue(wf.completed)

	# ── Scenario 3: completion condition + cancel_remaining=True ──

	def test_completion_condition_cancels_parked_heads(self):
		wf = _build("adhoc_sequential.bpmn", "Process_AdhocSequential", {"done": False})
		_drive(wf)
		sp = _adhoc(wf)

		_complete_manual(wf, "task_a", data={"done": True})

		states = _states(sp)
		self.assertEqual(states["task_a"], "COMPLETED")
		self.assertEqual(states["task_b"], "CANCELLED")
		self.assertEqual(states["task_c"], "CANCELLED")
		self.assertTrue(wf.completed)

	# ── Scenario 4: cancel_remaining=False — parked heads still must not
	# start once the condition is true; only in-flight work may finish ──

	def test_condition_with_cancel_remaining_false(self):
		wf = _build("adhoc_sequential.bpmn", "Process_AdhocSequential", {"done": False})
		_drive(wf)
		sp = _adhoc(wf)
		# The unqualified-attribute parsing fix ships on WI-001348; set the
		# spec flag directly so this branch tests the loop semantics alone.
		sp.spec.cancel_remaining = False

		_complete_manual(wf, "task_a", data={"done": True})

		states = _states(sp)
		self.assertEqual(states["task_a"], "COMPLETED")
		# Never-started heads must not run after the condition became true;
		# the gate cancels them so the subprocess EndJoin can complete.
		self.assertEqual(states["task_b"], "CANCELLED")
		self.assertEqual(states["task_c"], "CANCELLED")
		self.assertTrue(wf.completed)

	# ── Scenario 5/8: mid-flight state survives serialize/restore ──

	def test_serialize_restore_resumes_mid_adhoc(self):
		wf = _build("adhoc_sequential.bpmn", "Process_AdhocSequential", {"done": False})
		_drive(wf)
		_complete_manual(wf, "task_a")

		# Mid-flight: task_a done, task_b active, task_c parked in order.
		state = json.loads(json.dumps(engine.serialize_workflow(wf)))
		restored = engine.restore_workflow(state)

		sp = _adhoc(restored)
		states = _states(sp)
		self.assertEqual(states["task_a"], "COMPLETED")
		self.assertEqual(states["task_b"], "READY")
		self.assertEqual(states["task_c"], "FUTURE")

		# Round-trip stability: serializing the restored workflow reproduces
		# the stored state byte for byte.
		self.assertEqual(
			json.dumps(engine.serialize_workflow(restored), sort_keys=True),
			json.dumps(state, sort_keys=True),
		)

		# And the loop resumes exactly where it left off.
		engine.do_engine_steps_gated(restored)
		_complete_manual(restored, "task_b")
		_complete_manual(restored, "task_c", data={"done": True})
		self.assertTrue(restored.completed)

	# ── Scenario 8: loop + multi-instance tasks active at serialization ──

	def test_round_trip_with_loop_and_multiinstance_active(self):
		wf = _build(
			"adhoc_reference.bpmn",
			"main",
			{
				"done": False,
				"revision_requested": True,
				"edit_requested": False,
				"editing_done": False,
				"graphics_needed": ["g1"],
				"graphics": [],
			},
		)
		_drive(wf)
		sp = _adhoc(wf)

		# research → first_draft → organize_references is a connected chain;
		# path_complete only fires when the chain's LAST task (the one with no
		# outgoing flow) completes. It then re-adds the conditional paths whose
		# conditions warrant: revise (standardLoopCharacteristics,
		# revision_requested is True) and make_graphics
		# (multiInstanceLoopCharacteristics, its completion condition not met).
		_complete_manual(wf, "research")
		_complete_manual(wf, "first_draft")
		_complete_manual(wf, "organize_references")

		spec_names = {t.task_spec.name for t in sp.get_tasks(skip_subprocesses=True)}
		self.assertIn("revise", spec_names)
		self.assertIn("make_graphics", spec_names)

		state = json.loads(json.dumps(engine.serialize_workflow(wf)))
		restored = engine.restore_workflow(state)

		before = {
			(t.task_spec.name, TaskState.get_name(t.state))
			for t in sp.get_tasks(skip_subprocesses=True)
		}
		after = {
			(t.task_spec.name, TaskState.get_name(t.state))
			for t in _adhoc(restored).get_tasks(skip_subprocesses=True)
		}
		self.assertEqual(before, after)

		# Byte-for-byte: restore → serialize reproduces the stored state.
		self.assertEqual(
			json.dumps(engine.serialize_workflow(restored), sort_keys=True),
			json.dumps(state, sort_keys=True),
		)

	# ── Scenario 7 wiring: the ad-hoc completion callback fires per task ──

	def test_adhoc_completion_callback_fires_for_inner_tasks_only(self):
		wf = _build("adhoc_script_order.bpmn", "Process_AdhocScripts", {"done": False})
		adhoc_completions = []
		_drive(wf, did_complete_adhoc_task=lambda t: adhoc_completions.append(t.task_spec.name))
		# Fires exactly once per real inner task, in execution order — never
		# for main-flow tasks or the subworkflow's internal Start/EndJoin/End.
		self.assertEqual(adhoc_completions, ["script_a", "script_b", "script_c"])
