# Copyright (c) 2026, one-fm and contributors
"""A visible Process Instance row for each Call Activity a process runs.

The projection is tested against synthetic state rather than a live run, because
every failure it can have is a shape failure — a key that belongs at the top of a
workflow state and not inside a subprocess, or the other way round. Those are
exact, and building a real BPMN instance to assert them would hide them behind a
lot of unrelated machinery.

Two of the assertions here exist because the obvious implementation passes a
casual eye and then fails: leaving ``typename`` as ``BpmnSubWorkflow`` produces a
state that cannot be deserialized at all, and leaving ``spec`` as the subprocess's
spec NAME produces one that deserializes and then dies on first use. Both were
hit while building this.
"""

import json
from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.doctype.bpmn_process_instance import call_activity_instances as CAI

SPEC = {
	"name": "called_proc",
	"task_specs": {"start": {"typename": "StartEvent"}},
	"data_objects": {},
	"typename": "BpmnProcessSpec",
}


def _parent_state(**over):
	"""A caller's serialized state holding one subprocess, plus a nested one."""
	state = {
		"typename": "BpmnWorkflow",
		"serializer_version": "1.0-spiff",
		"spec": {"name": "caller", "data_objects": {}, "typename": "BpmnProcessSpec"},
		"subprocess_specs": {"called_proc": SPEC, "inner_tools": dict(SPEC, name="inner_tools")},
		"bpmn_events": [{"event": "x"}],
		"tasks": {"caller-task": {}},
		"subprocesses": {
			"call-task-1": {
				"typename": "BpmnSubWorkflow",
				"parent_task_id": "caller-task",
				"spec": "called_proc",
				"tasks": {"inner-a": {}, "inner-b": {}},
				"completed": False,
				"success": True,
				"data": {},
				"correlations": {},
				"last_task": "inner-a",
				"root": "inner-a",
			},
			# Nested one level down: its parent task lives inside call-task-1.
			"tools-task-9": {
				"typename": "BpmnSubWorkflow",
				"parent_task_id": "inner-b",
				"spec": "inner_tools",
				"tasks": {"tool-1": {}},
				"completed": False,
			},
			# Belongs to a DIFFERENT call and must not be dragged in.
			"other-call": {
				"typename": "BpmnSubWorkflow",
				"parent_task_id": "caller-task",
				"spec": "called_proc",
				"tasks": {"z": {}},
			},
		},
	}
	state.update(over)
	return state


class TestProjection(FrappeTestCase):
	def test_the_four_top_level_keys_are_added(self):
		p = CAI.project_subworkflow_state(_parent_state(), "call-task-1")
		for key in ("serializer_version", "subprocess_specs", "subprocesses", "bpmn_events"):
			self.assertIn(key, p, f"{key} missing — a subprocess does not carry it")
		self.assertEqual(p["serializer_version"], "1.0-spiff")

	def test_parent_task_id_is_dropped(self):
		"""It is the one key that only means something inside a parent."""
		p = CAI.project_subworkflow_state(_parent_state(), "call-task-1")
		self.assertNotIn("parent_task_id", p)

	def test_typename_is_promoted(self):
		"""BpmnSubWorkflow's converter takes the parent task and top workflow as
		arguments, so a state left with that typename cannot be deserialized on
		its own however complete it looks."""
		p = CAI.project_subworkflow_state(_parent_state(), "call-task-1")
		self.assertEqual(p["typename"], "BpmnWorkflow")

	def test_spec_name_is_resolved_to_the_inline_spec(self):
		"""A top-level state carries its spec inline; a subprocess carries the
		NAME. Leaving the name deserializes and then fails on first use with
		"'str' object has no attribute 'data_objects'"."""
		p = CAI.project_subworkflow_state(_parent_state(), "call-task-1")
		self.assertIsInstance(p["spec"], dict)
		self.assertEqual(p["spec"]["name"], "called_proc")

	def test_nested_subprocesses_come_across_by_ancestry(self):
		"""An ad-hoc toolbox inside the called process is its own entry in the
		CALLER's map. Dropping it leaves the projection referring to a
		subprocess that is not there."""
		p = CAI.project_subworkflow_state(_parent_state(), "call-task-1")
		self.assertIn("tools-task-9", p["subprocesses"])

	def test_a_sibling_call_is_not_dragged_in(self):
		p = CAI.project_subworkflow_state(_parent_state(), "call-task-1")
		self.assertNotIn("other-call", p["subprocesses"])
		self.assertNotIn("call-task-1", p["subprocesses"])

	def test_an_uninstantiated_subworkflow_projects_to_none(self):
		"""A Call Activity reached but not yet entered. Normal, not an error."""
		self.assertIsNone(CAI.project_subworkflow_state(_parent_state(), "not-a-task"))

	def test_a_missing_spec_projects_to_none(self):
		"""A row that cannot render is worse than no row."""
		state = _parent_state()
		state["subprocess_specs"] = {}
		self.assertIsNone(CAI.project_subworkflow_state(state, "call-task-1"))

	def test_the_projection_does_not_mutate_the_parent(self):
		state = _parent_state()
		snapshot = json.dumps(state, sort_keys=True)
		CAI.project_subworkflow_state(state, "call-task-1")
		self.assertEqual(json.dumps(state, sort_keys=True), snapshot)


class _FakeSpec:
	"""Stands in for SpiffWorkflow's CallActivity task spec."""

	def __init__(self, name, called=None, kind="CallActivity"):
		self.name = name
		self.bpmn_id = name
		self.spec = called
		self.__class__ = type(kind, (_FakeSpec,), {})


class _FakeWf:
	def __init__(self, tasks):
		self._tasks = tasks
		self.subprocesses = {"call-task-1": object()}

	def get_tasks(self, *a, **k):
		return self._tasks


def _call_task(task_id, called="called_proc", kind="CallActivity"):
	spec = _FakeSpec.__new__(type(kind, (), {}))
	spec.name = task_id
	spec.bpmn_id = task_id
	spec.spec = called
	return SimpleNamespace(id=task_id, task_spec=spec)


class TestRowSync(FrappeTestCase):
	def setUp(self):
		self.model = frappe.get_all(
			"BPMN Process Model", filters={"process_id": ["is", "set"]},
			fields=["name", "process_id"], limit=1,
		)
		if not self.model:
			self.skipTest("no Process Model with a process_id on this site")
		self.model = self.model[0]

		self.parent = frappe.new_doc("BPMN Process Instance")
		self.parent.process_model = self.model.name
		self.parent.status = "Active"
		state = _parent_state()
		state["subprocesses"]["call-task-1"]["spec"] = self.model.process_id
		state["subprocess_specs"][self.model.process_id] = dict(SPEC, name=self.model.process_id)
		self.parent.workflow_state = json.dumps(state)
		self.parent.insert(ignore_permissions=True)

	def _children(self):
		return frappe.get_all(
			"BPMN Process Instance", filters={"parent_instance": self.parent.name},
			fields=["name", "process_model", "status", "parent_task_id"],
		)

	def test_a_row_is_created_for_the_call(self):
		wf = _FakeWf([_call_task("call-task-1", called=self.model.process_id)])
		CAI.sync_call_activity_instances(self.parent, wf)
		rows = self._children()
		self.assertEqual(len(rows), 1, rows)
		self.assertEqual(rows[0]["process_model"], self.model.name)
		self.assertEqual(rows[0]["parent_task_id"], "call-task-1")

	def test_syncing_twice_does_not_duplicate(self):
		wf = _FakeWf([_call_task("call-task-1", called=self.model.process_id)])
		for _ in range(3):
			CAI.sync_call_activity_instances(self.parent, wf)
		self.assertEqual(len(self._children()), 1)

	def test_completion_is_carried_over(self):
		state = json.loads(self.parent.workflow_state)
		state["subprocesses"]["call-task-1"]["completed"] = True
		self.parent.workflow_state = json.dumps(state)
		wf = _FakeWf([_call_task("call-task-1", called=self.model.process_id)])
		CAI.sync_call_activity_instances(self.parent, wf)
		row = self._children()[0]
		self.assertEqual(row["status"], "Completed")
		self.assertTrue(
			frappe.db.get_value("BPMN Process Instance", row["name"], "completed_at")
		)

	def test_the_timestamp_moves_when_the_status_moves(self):
		"""A run that finished must not go on reading as last-touched hours ago.

		This is the defect that made a completed orchestrator look like a stuck
		one: the status went to Completed but `modified` still showed the moment
		the row was created, so any list sorted or filtered by Last Updated
		presented a finished run as stale and still open.
		"""
		wf = _FakeWf([_call_task("call-task-1", called=self.model.process_id)])
		CAI.sync_call_activity_instances(self.parent, wf)
		row = self._children()[0]["name"]
		before = frappe.db.get_value("BPMN Process Instance", row, "modified")

		state = json.loads(self.parent.workflow_state)
		state["subprocesses"]["call-task-1"]["completed"] = True
		self.parent.workflow_state = json.dumps(state)
		CAI.sync_call_activity_instances(self.parent, wf)

		after = frappe.db.get_value("BPMN Process Instance", row, "modified")
		self.assertGreater(after, before, "modified did not move on a real transition")

	def test_the_timestamp_holds_still_while_nothing_changes(self):
		"""The other half: the caller persists constantly, and touching this row
		every time would make Last Updated worthless."""
		wf = _FakeWf([_call_task("call-task-1", called=self.model.process_id)])
		CAI.sync_call_activity_instances(self.parent, wf)
		row = self._children()[0]["name"]
		before = frappe.db.get_value("BPMN Process Instance", row, "modified")
		for _ in range(3):
			CAI.sync_call_activity_instances(self.parent, wf)
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", row, "modified"), before
		)

	def test_started_at_is_when_the_call_was_seen_not_when_the_caller_began(self):
		"""A Call Activity usually sits behind human steps, so the caller's start
		can be hours earlier. Copying it made the called process look as though it
		had run for the caller's whole lifetime."""
		long_ago = "2020-01-01 00:00:00"
		frappe.db.set_value(
			"BPMN Process Instance", self.parent.name, "started_at", long_ago,
			update_modified=False,
		)
		self.parent.started_at = long_ago
		wf = _FakeWf([_call_task("call-task-1", called=self.model.process_id)])
		CAI.sync_call_activity_instances(self.parent, wf)
		started = frappe.db.get_value(
			"BPMN Process Instance", self._children()[0]["name"], "started_at"
		)
		self.assertNotEqual(str(started), long_ago)

	def test_a_plain_subprocess_gets_no_row(self):
		"""Sub-Process, ad-hoc and Transaction are SubWorkflowTasks too, and none
		of them calls another process model — a row for them would be noise."""
		wf = _FakeWf([_call_task("call-task-1", called=None, kind="SubWorkflowTask")])
		CAI.sync_call_activity_instances(self.parent, wf)
		self.assertEqual(self._children(), [])

	def test_an_unknown_called_process_gets_no_row(self):
		wf = _FakeWf([_call_task("call-task-1", called="no_such_process_id_here")])
		CAI.sync_call_activity_instances(self.parent, wf)
		self.assertEqual(self._children(), [])

	def test_a_broken_sync_never_breaks_the_run(self):
		"""A missing row is a reporting gap; an exception here is a failed
		process. The caller's run must not depend on its own bookkeeping."""

		class Exploding:
			subprocesses = {"x": object()}

			def get_tasks(self, *a, **k):
				raise RuntimeError("boom")

		CAI.sync_call_activity_instances(self.parent, Exploding())  # must not raise
