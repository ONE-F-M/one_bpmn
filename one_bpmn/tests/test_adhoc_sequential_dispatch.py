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
from SpiffWorkflow.bpmn.specs.mixins.subworkflow_task import SubWorkflowTask
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
			# Mirror _run_engine_inner: never force-complete a subworkflow
			# container — it is STARTED while its inner workflow runs.
			and not isinstance(t.task_spec, SubWorkflowTask)
		]
		if not started:
			break
		for task in started:
			task.complete()
			# Mirror _run_engine_inner: the adhoc completion hook fires
			# AFTER dispatch completes the task (post-write), not at run().
			if (
				did_complete_adhoc_task is not None
				and isinstance(getattr(task.workflow, "spec", None), engine.AdHocSubprocessSpec)
				and getattr(task.task_spec, "bpmn_id", None)
			):
				did_complete_adhoc_task(task)


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

	# ── Regression: doc-based completion condition must see mid-session
	# writes once refresh_context_doc runs. The env keeps its variables in
	# TaskDataEnvironment.globals; the old refresh wrote to a nonexistent
	# `.environment` attribute behind a hasattr guard — a silent no-op, so
	# `doc.<field>` conditions evaluated against the Document loaded at
	# engine construction and ad-hoc subprocesses never completed inside
	# the request that resolved their document (UAT: 7bn03s5gnm et al.) ──

	def test_doc_condition_sees_write_after_refresh(self):
		import frappe

		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "bpmn doc-refresh regression",
				"allocated_to": "Administrator",
			}
		).insert()
		xml = (FIXTURES / "adhoc_sequential.bpmn").read_text()
		spec_dict, sp_specs = engine.parse_bpmn(xml, "Process_AdhocSequential")
		wf = engine.create_workflow(
			spec_dict,
			sp_specs,
			initial_data={"done": False},
			context_doctype="ToDo",
			context_docname=todo.name,
		)
		_drive(wf)
		sp = _adhoc(wf)
		sp.spec.completion_condition = 'doc.status == "Closed"'

		# The write happens outside the env's doc object — exactly what a
		# Server-Script-backed task or update_field dispatch does.
		frappe.db.set_value("ToDo", todo.name, "status", "Closed")
		self.assertFalse(
			engine._adhoc_completion_met(sp),
			"env doc predates the write — condition must still be False",
		)

		engine.refresh_context_doc(wf, "ToDo", todo.name)
		self.assertTrue(
			engine._adhoc_completion_met(sp),
			"refresh_context_doc did not refresh the doc the condition evaluates against",
		)

		# And the gate must now complete the subprocess in this same session.
		_complete_manual(wf, "task_a")
		states = _states(sp)
		self.assertEqual(states["task_b"], "CANCELLED")
		self.assertEqual(states["task_c"], "CANCELLED")
		self.assertTrue(wf.completed)


ADHOC_USER_TASK_MODEL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    id="Defs_AdhocInstance" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_AdhocInstance" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1">
      <bpmn:outgoing>Flow_In</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_In" sourceRef="StartEvent_1" targetRef="AdhocSub_1" />
    <bpmn:adHocSubProcess id="AdhocSub_1" name="Manual Ad-hoc Work">
      <bpmn:incoming>Flow_In</bpmn:incoming>
      <bpmn:outgoing>Flow_Out</bpmn:outgoing>
      <bpmn:userTask id="task_a" name="Task A" />
      <bpmn:userTask id="task_b" name="Task B" />
      <bpmn:completionCondition xsi:type="bpmn:tFormalExpression">done</bpmn:completionCondition>
    </bpmn:adHocSubProcess>
    <bpmn:sequenceFlow id="Flow_Out" sourceRef="AdhocSub_1" targetRef="EndEvent_1" />
    <bpmn:endEvent id="EndEvent_1">
      <bpmn:incoming>Flow_Out</bpmn:incoming>
    </bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""


class TestAdhocInstanceLifecycle(FrappeTestCase):
	"""Instance-level (doctype) coverage: the engine-level tests above drive
	the gate directly, which let a bug in BPMNProcessInstance._run_engine_inner
	slip through — its STARTED-dispatch loop force-completed the ad-hoc
	subprocess PARENT task (STARTED while inner work runs), running the
	process to the End Event while inner user tasks were still pending."""

	def _start_instance(self):
		import frappe

		from one_bpmn.api.compilation import compile_process_model

		process = frappe.get_doc({
			"doctype": "Process",
			"process_name": f"adhoc-test-{frappe.generate_hash(length=6)}",
			"description": "Ad-hoc instance lifecycle test",
			"process_owner": "Administrator",
		})
		process.insert(ignore_permissions=True)

		suffix = frappe.generate_hash(length=6)
		model = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"title": f"adhoc-test-model-{suffix}",
			"process_id": f"adhoc-test-{suffix}",
			"version": 1,
			"process_name": process.name,
			"bpmn_xml": ADHOC_USER_TASK_MODEL_XML,
		})
		model.flags.skip_editability_check = True
		model.insert(ignore_permissions=True)
		compile_process_model(model.name)

		instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_model": model.name,
		})
		instance.insert(ignore_permissions=True)
		instance.start(initial_data={})
		return instance

	def test_instance_stays_active_while_adhoc_user_task_pending(self):
		instance = self._start_instance()

		self.assertEqual(instance.status, "Active")
		waiting = [(r.task_name, r.status) for r in instance.active_tasks]
		self.assertIn(("Task A", "Waiting"), waiting)

		# The ad-hoc PARENT task must still be running (STARTED), not
		# force-completed by the ServiceTask dispatch loop.
		state = json.loads(instance.workflow_state)
		parent_states = [
			TaskState.get_name(t["state"])
			for t in state["tasks"].values()
			if t["task_spec"] == "AdhocSub_1"
		]
		self.assertEqual(parent_states, ["STARTED"])


ADHOC_SEND_TASK_MODEL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs_AdhocSend" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_AdhocSend" isExecutable="true">
    <bpmn:startEvent id="StartEvent_1">
      <bpmn:outgoing>Flow_In</bpmn:outgoing>
    </bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_In" sourceRef="StartEvent_1" targetRef="AdhocSub_1" />
    <bpmn:adHocSubProcess id="AdhocSub_1" name="Send Work">
      <bpmn:incoming>Flow_In</bpmn:incoming>
      <bpmn:outgoing>Flow_Out</bpmn:outgoing>
      <bpmn:sendTask id="send_ack" name="Send Ack" spiffworkflow:notificationName="__NOTIFICATION__" />
      <bpmn:userTask id="task_wait" name="Wait Here" />
      <bpmn:completionCondition xsi:type="bpmn:tFormalExpression">done</bpmn:completionCondition>
    </bpmn:adHocSubProcess>
    <bpmn:sequenceFlow id="Flow_Out" sourceRef="AdhocSub_1" targetRef="EndEvent_1" />
    <bpmn:endEvent id="EndEvent_1">
      <bpmn:incoming>Flow_Out</bpmn:incoming>
    </bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>
"""


class TestSendTaskDispatch(FrappeTestCase):
	"""Send Tasks were runtime no-ops until 2026-07-04: nothing consumed
	spiffworkflow:notificationName, so 'send acknowledgment' shapes completed
	without sending anything or leaving evidence — selector prompts gating on
	'email sent' variables stalled forever (support_triage_selector v1)."""

	def _start_instance(self, notification_name):
		import frappe

		from one_bpmn.api.compilation import compile_process_model

		process = frappe.get_doc({
			"doctype": "Process",
			"process_name": f"send-test-{frappe.generate_hash(length=6)}",
			"description": "Send task dispatch test",
			"process_owner": "Administrator",
		})
		process.insert(ignore_permissions=True)

		suffix = frappe.generate_hash(length=6)
		model = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"title": f"send-test-model-{suffix}",
			"process_id": f"send-test-{suffix}",
			"version": 1,
			"process_name": process.name,
			"bpmn_xml": ADHOC_SEND_TASK_MODEL_XML.replace("__NOTIFICATION__", notification_name),
		})
		model.flags.skip_editability_check = True
		model.insert(ignore_permissions=True)
		compile_process_model(model.name)

		todo = frappe.get_doc({
			"doctype": "ToDo",
			"description": "send task dispatch test",
			"allocated_to": "Administrator",
		}).insert(ignore_permissions=True)

		instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_model": model.name,
			"context_doctype": "ToDo",
			"context_docname": todo.name,
		})
		instance.insert(ignore_permissions=True)
		instance.start(initial_data={"done": False})
		return instance

	def _sp_scope(self, instance):
		state = json.loads(instance.workflow_state)
		return next(iter((state.get("subprocesses") or {}).values()), {}).get("data", {})

	def test_send_task_sends_notification_and_leaves_evidence(self):
		import frappe
		from unittest.mock import patch

		notification = frappe.get_doc({
			"doctype": "Notification",
			"__newname": f"send-test-notif-{frappe.generate_hash(length=6)}",
			"subject": "Test send task",
			"document_type": "ToDo",
			"event": "Method",
			"method": "one_bpmn.tests.never_fired_directly",
			"channel": "Email",
			"message": "Test",
			"recipients": [{"receiver_by_document_field": "allocated_to"}],
		}).insert(ignore_permissions=True)

		with patch(
			"frappe.email.doctype.notification.notification.Notification.send"
		) as mock_send:
			instance = self._start_instance(notification.name)

		# The send actually fired, against the context document
		mock_send.assert_called_once()
		self.assertEqual(mock_send.call_args[0][0].doctype, "ToDo")

		# Evidence convention: the subprocess scope records the send, so
		# selector prompts can gate follow-up steps on send_ack_sent.
		scope = self._sp_scope(instance)
		self.assertEqual(scope.get("send_ack_sent"), 1)
		self.assertNotIn("send_ack_send_error", scope)

		# Flow continues normally — the user task head is now waiting.
		self.assertEqual(instance.status, "Active")
		self.assertIn("Wait Here", [r.task_name for r in instance.active_tasks])

	def test_send_task_failure_leaves_error_evidence_not_success(self):
		instance = self._start_instance("no-such-notification-record")

		scope = self._sp_scope(instance)
		self.assertNotIn("send_ack_sent", scope, "failure must not fake a sent email")
		self.assertIn("send_ack_send_error", scope)

		# The engine is not wedged: the task completed, the flow moved on.
		self.assertEqual(instance.status, "Active")
		self.assertIn("Wait Here", [r.task_name for r in instance.active_tasks])


class TestUnseededCompletionCondition(FrappeTestCase):
	"""The completion-condition variable typically doesn't exist until a
	late inner task sets it (e.g. a wrap-up script running `done = True`).
	Upstream path_complete evaluated the condition with a raw eval after
	EVERY inner completion — the unset name raised NameError and failed
	the user's task completion. The engine now treats an unresolvable
	condition as not met (Camunda semantics)."""

	def test_first_completion_does_not_raise_on_unset_variable(self):
		# NOTE: no {"done": False} seeding — mirrors real instances
		wf = _build("adhoc_sequential.bpmn", "Process_AdhocSequential")
		_drive(wf)
		sp = _adhoc(wf)

		_complete_manual(wf, "task_a")  # raised NameError before the fix

		states = _states(sp)
		self.assertEqual(states["task_a"], "COMPLETED")
		self.assertIn(states["task_b"], ("READY", "STARTED", "WAITING"))
		self.assertFalse(wf.completed)

	def test_condition_still_fires_once_variable_is_set(self):
		wf = _build("adhoc_sequential.bpmn", "Process_AdhocSequential")
		_drive(wf)
		sp = _adhoc(wf)

		_complete_manual(wf, "task_a")
		_complete_manual(wf, "task_b", data={"done": True})

		states = _states(sp)
		self.assertEqual(states["task_b"], "COMPLETED")
		self.assertEqual(states["task_c"], "CANCELLED")
		self.assertTrue(wf.completed)


class TestDeciderChoosesEntryTask(FrappeTestCase):
	"""User decision 2026-07-04: an installed AI Task Selector decider picks
	even the FIRST task at subprocess entry (previously the first head in
	diagram order auto-ran before the selector was ever consulted). Plain
	ad-hoc subprocesses (no decider) keep diagram-order entry unchanged —
	covered by test_single_task_active_at_entry above."""

	def tearDown(self):
		engine.adhoc_next_task_decider = None
		super().tearDown()

	def test_decider_picks_the_entry_task(self):
		wf = _build("adhoc_sequential.bpmn", "Process_AdhocSequential")
		engine.adhoc_next_task_decider = lambda sp, pending: next(
			t for t in pending if t.task_spec.name == "task_c"
		)
		_drive(wf)

		states = _states(_adhoc(wf))
		self.assertIn(states["task_c"], ("READY", "STARTED", "WAITING"))
		self.assertEqual(states["task_a"], "FUTURE")
		self.assertEqual(states["task_b"], "FUTURE")

	def test_decider_no_activation_parks_everything_at_entry(self):
		wf = _build("adhoc_sequential.bpmn", "Process_AdhocSequential")
		engine.adhoc_next_task_decider = lambda sp, pending: engine.NO_ACTIVATION
		_drive(wf)

		states = _states(_adhoc(wf))
		self.assertEqual(
			{states["task_a"], states["task_b"], states["task_c"]}, {"FUTURE"}
		)
