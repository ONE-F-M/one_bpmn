# Copyright (c) 2026, one-fm and contributors
"""Moving a record to a new map: where the replay ends, every reason it stops, and the instance swap."""

import json
from unittest.mock import patch

import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase

from one_bpmn.processa_engine.compiler.compile_step import compile_model
from one_bpmn.processa_engine.engine import TaskState
from one_bpmn.processa_engine.instances.starting import start_process
from one_bpmn.processa_engine.instances.task_actions import complete_task
from one_bpmn.processa_engine.legacy_migration import (
	MigrationSkip,
	build_context,
	migrate_record,
	replay,
	wait_ids,
)
from one_bpmn.processa_engine.runtime.messages import receive_message

DT = "GP Letter Request"
DRAFT, APPROVED, DONE = "PLM Rep Draft", "PLM Rep Approved", "PLM Rep Done"
PR_OPENED = "github:pull_request:opened"
SPIFF = 'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"'

OLD = [
	("state", "Task_draft", DRAFT),
	("user", "Task_review", "Review"),
	("state", "Task_approved", APPROVED),
	("catch", "Catch_pr", PR_OPENED),
	("user", "Task_merge", "Merge"),
	("state", "Task_done", DONE),
]


def _node(kind, node_id, arg, incoming, outgoing):
	flows = f"<bpmn:incoming>{incoming}</bpmn:incoming><bpmn:outgoing>{outgoing}</bpmn:outgoing>"
	if kind == "state":
		return (
			f'<bpmn:serviceTask id="{node_id}" name="Set {arg}" spiffworkflow:serviceType="apply_workflow" '
			f'spiffworkflow:serviceTargetDoctype="{DT}" spiffworkflow:workflowState="{arg}" '
			f'spiffworkflow:docStatus="0">{flows}</bpmn:serviceTask>'
		)
	if kind == "user":
		return (
			f'<bpmn:userTask id="{node_id}" name="{arg}" spiffworkflow:assigneeMode="DocField" '
			f'spiffworkflow:targetDoctype="{DT}" spiffworkflow:assigneeDocfield="owner" '
			f'spiffworkflow:taskActions="[{{&#34;action&#34;:&#34;Approve&#34;}}]">{flows}</bpmn:userTask>'
		)
	if kind == "catch":
		return (
			f'<bpmn:intermediateCatchEvent id="{node_id}" name="{arg}">{flows}'
			f'<bpmn:messageEventDefinition messageRef="Message_{node_id}" /></bpmn:intermediateCatchEvent>'
		)
	if kind == "script":
		return f'<bpmn:scriptTask id="{node_id}" name="Mark">{flows}<bpmn:script>script_ran = True</bpmn:script></bpmn:scriptTask>'
	if kind == "email":
		return (
			f'<bpmn:serviceTask id="{node_id}" name="Email" spiffworkflow:serviceType="send_email" '
			f'spiffworkflow:emailTo="someone@example.com" spiffworkflow:emailSubject="Hi" '
			f'spiffworkflow:emailBody="Hi">{flows}</bpmn:serviceTask>'
		)
	return f'<bpmn:callActivity id="{node_id}" name="Call" calledElement="{arg}">{flows}</bpmn:callActivity>'


def _xml(pid, nodes):
	"""A straight line Start, nodes, End."""
	ids = ["Start_1", *(n[1] for n in nodes), "End_1"]
	flows = [f"Flow_{i}" for i in range(len(ids) - 1)]
	body = [
		f'<bpmn:startEvent id="Start_1" name="Start"><bpmn:outgoing>{flows[0]}</bpmn:outgoing></bpmn:startEvent>'
	]
	for i, (kind, node_id, arg) in enumerate(nodes):
		body.append(_node(kind, node_id, arg, flows[i], flows[i + 1]))
	body.append(
		f'<bpmn:endEvent id="End_1" name="End"><bpmn:incoming>{flows[-1]}</bpmn:incoming></bpmn:endEvent>'
	)
	body += [
		f'<bpmn:sequenceFlow id="{f}" sourceRef="{ids[i]}" targetRef="{ids[i + 1]}" />'
		for i, f in enumerate(flows)
	]
	messages = "".join(
		f'<bpmn:message id="Message_{n[1]}" name="{n[2]}" />' for n in nodes if n[0] == "catch"
	)
	return _definitions(pid, "".join(body), messages)


def _definitions(pid, body, messages=""):
	return (
		f'<?xml version="1.0" encoding="UTF-8"?><bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
		f'{SPIFF} id="Defs_{pid}" targetNamespace="http://bpmn.io/schema/bpmn">{messages}'
		f'<bpmn:process id="{pid}" isExecutable="true">{body}</bpmn:process></bpmn:definitions>'
	)


def _loop_xml(pid):
	"""Set Draft, then a gateway whose condition always sends it back, so the review is never reached."""
	return _definitions(
		pid,
		f'<bpmn:startEvent id="Start_1" name="Start"><bpmn:outgoing>Flow_0</bpmn:outgoing></bpmn:startEvent>'
		f"{_node('state', 'Task_draft', DRAFT, 'Flow_0', 'Flow_1').replace('</bpmn:incoming>', '</bpmn:incoming><bpmn:incoming>Flow_back</bpmn:incoming>', 1)}"
		f'<bpmn:exclusiveGateway id="Gateway_1" name="Again?" default="Flow_2"><bpmn:incoming>Flow_1</bpmn:incoming>'
		f"<bpmn:outgoing>Flow_back</bpmn:outgoing><bpmn:outgoing>Flow_2</bpmn:outgoing></bpmn:exclusiveGateway>"
		f"{_node('user', 'Task_review', 'Review', 'Flow_2', 'Flow_3')}"
		f'<bpmn:endEvent id="End_1" name="End"><bpmn:incoming>Flow_3</bpmn:incoming></bpmn:endEvent>'
		f'<bpmn:sequenceFlow id="Flow_0" sourceRef="Start_1" targetRef="Task_draft" />'
		f'<bpmn:sequenceFlow id="Flow_1" sourceRef="Task_draft" targetRef="Gateway_1" />'
		f'<bpmn:sequenceFlow id="Flow_back" sourceRef="Gateway_1" targetRef="Task_draft">'
		f"<bpmn:conditionExpression>True</bpmn:conditionExpression></bpmn:sequenceFlow>"
		f'<bpmn:sequenceFlow id="Flow_2" sourceRef="Gateway_1" targetRef="Task_review" />'
		f'<bpmn:sequenceFlow id="Flow_3" sourceRef="Task_review" targetRef="End_1" />',
	)


def _deploy(title, xml):
	pid = frappe.scrub(title)
	model = frappe.get_doc(
		{
			"doctype": "BPMN Process Model",
			"title": title,
			"process_id": pid,
			"version": 1,
			"bpmn_xml": xml(pid) if callable(xml) else _xml(pid, xml),
		}
	)
	model.flags.skip_editability_check = True
	model.insert()
	compile_model(model)
	return model.name


def _with(nodes, **changes):
	"""OLD-style nodes with labels replaced, or nodes inserted after or removed by element id."""
	out = []
	for kind, node_id, arg in nodes:
		if changes.get("drop") == node_id:
			continue
		out.append((kind, node_id, changes.get("relabel", {}).get(node_id, arg)))
		out += changes.get("after", {}).get(node_id, [])
	return out


class TestLegacyMigrationReplay(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for state in (DRAFT, APPROVED, DONE):
			frappe.get_doc(
				{"doctype": "Workflow State", "workflow_state_name": state, "style": "Primary"}
			).insert()
		cls.old_map = _deploy("PLM Rep Old", OLD)
		_deploy("PLM Rep Sub", [("user", "Task_sub", "Sub Review")])
		cls.call_map = _deploy(
			"PLM Rep Call", [("state", "Task_draft", DRAFT), ("call", "Call_sub", "plm_rep_sub")]
		)

		cls.waiting_review = cls._old_instance(cls.old_map)
		cls.waiting_pr = cls._old_instance(cls.old_map, "Task_review")
		cls.waiting_merge = cls._old_instance(cls.old_map, "Task_review", PR_OPENED)
		cls.call_running = cls._old_instance(cls.call_map)
		cls.errored = cls._old_instance(cls.old_map, "Task_review")
		frappe.db.set_value("BPMN Process Instance", cls.errored, "status", "Errored")

	@classmethod
	def _old_instance(cls, model, *history):
		"""Run the real engine on a new record: complete each named user task or deliver each message, in order."""
		with patch("one_bpmn.processa_engine.triggers.on_doc_event"):
			record = frappe.get_doc({"doctype": DT}).insert().name
		name = start_process(model, DT, record)["instance"]
		for step in history:
			instance = frappe.get_doc("BPMN Process Instance", name)
			if step == PR_OPENED:
				receive_message(instance, PR_OPENED, {"pr_url": "https://github.com/x/y/pull/1"})
			else:
				row = next(r for r in instance.active_tasks if r.status == "Waiting")
				complete_task(name, row.task_id, json.dumps({"action": "Approve"}))
		return name

	def setUp(self):
		super().setUp()
		# FrappeTestCase rolls back per class; the savepoint keeps each test's rows out of the next.
		frappe.db.savepoint("plm_replay_test")
		self.addCleanup(frappe.db.rollback, save_point="plm_replay_test")

	def _replay(self, nodes_or_xml, old, mapping, title="PLM Rep New"):
		new_map = _deploy(title, nodes_or_xml)
		plm = frappe._dict(
			from_model=frappe.db.get_value("BPMN Process Instance", old, "process_model"),
			to_model=new_map,
			target_doctype=DT,
			state_map=[frappe._dict(old_state=o, new_state=n) for o, n in mapping],
		)
		return replay(build_context(plm), frappe.get_doc("BPMN Process Instance", old))

	def _assert_skip(self, reason, *args, contains=""):
		with self.assertRaises(MigrationSkip) as caught:
			self._replay(*args)
		self.assertEqual(caught.exception.reason, reason)
		self.assertIn(contains, caught.exception.detail)

	@staticmethod
	def _waits(wf):
		return sorted(wait_ids(wf))

	@staticmethod
	def _ready(wf, bpmn_id):
		return next(t for t in wf.get_tasks(state=TaskState.READY) if t.task_spec.bpmn_id == bpmn_id)

	def test_an_instance_waiting_at_a_user_task_ends_at_the_same_user_task(self):
		wf, last_state = self._replay(OLD, self.waiting_review, [(DRAFT, DRAFT)])
		self.assertEqual(self._waits(wf), ["Task_review"])
		self.assertEqual(last_state, DRAFT)

	def test_a_logged_message_is_delivered_with_its_payload(self):
		wf, _last = self._replay(OLD, self.waiting_merge, [(APPROVED, APPROVED)])
		self.assertEqual(self._waits(wf), ["Task_merge"])
		self.assertEqual(self._ready(wf, "Task_merge").data["pr_url"], "https://github.com/x/y/pull/1")

	def test_a_relabelled_user_task_is_completed_with_the_logged_action(self):
		nodes = _with(OLD, relabel={"Task_review": "Manager Review"})
		wf, last_state = self._replay(nodes, self.waiting_pr, [(APPROVED, APPROVED)])
		self.assertEqual(self._waits(wf), ["Catch_pr"])
		review = next(t for t in wf.get_tasks() if t.task_spec.bpmn_id == "Task_review")
		self.assertEqual(review.data["action"], "Approve")
		self.assertEqual(last_state, APPROVED)

	def test_a_user_task_the_new_map_removed_is_ignored(self):
		wf, _last = self._replay(_with(OLD, drop="Task_review"), self.waiting_pr, [(APPROVED, APPROVED)])
		self.assertEqual(self._waits(wf), ["Catch_pr"])

	def test_a_user_task_not_waiting_at_that_point_stops_the_replay(self):
		nodes = [OLD[0], OLD[3], OLD[1], OLD[2], OLD[4], OLD[5]]
		self._assert_skip(
			"Replay stuck", nodes, self.waiting_merge, [(APPROVED, APPROVED)], contains="Review"
		)

	def test_a_message_nothing_waits_for_stops_the_replay(self):
		nodes = [OLD[0], OLD[1], OLD[2], OLD[4], OLD[3], OLD[5]]
		self._assert_skip(
			"Replay stuck", nodes, self.waiting_merge, [(APPROVED, APPROVED)], contains=PR_OPENED
		)

	def test_a_new_user_task_before_the_wait_point_stops_the_replay(self):
		nodes = _with(OLD, after={"Task_draft": [("user", "Task_new", "New Step")]})
		self._assert_skip(
			"Past a new step", nodes, self.waiting_review, [(DRAFT, DRAFT)], contains="Task_new"
		)

	def test_a_new_user_task_after_the_wait_point_lets_the_record_move(self):
		nodes = _with(OLD, after={"Task_review": [("user", "Task_new", "New Step")]})
		wf, _last = self._replay(nodes, self.waiting_review, [(DRAFT, DRAFT)])
		self.assertEqual(self._waits(wf), ["Task_review"])

	def test_an_instance_waiting_at_a_removed_step_is_refused(self):
		self._assert_skip(
			"Waiting at removed step", _with(OLD, drop="Task_review"), self.waiting_review, [(DRAFT, DRAFT)]
		)

	def test_an_unfinished_call_activity_is_refused(self):
		self._assert_skip("Sub-process running", OLD, self.call_running, [(DRAFT, DRAFT)])

	def test_a_call_activity_in_the_new_map_completes_without_its_sub_process(self):
		nodes = _with(OLD, after={"Task_draft": [("call", "Call_sub", "plm_rep_sub")]})
		wf, _last = self._replay(nodes, self.waiting_review, [(DRAFT, DRAFT)])
		self.assertEqual(self._waits(wf), ["Task_review"])
		self.assertFalse(wf.subprocesses)

	def test_a_last_state_other_than_the_mapped_one_is_refused(self):
		self._assert_skip(
			"State not reached", OLD, self.waiting_review, [(DRAFT, APPROVED)], contains=APPROVED
		)

	def test_an_errored_instance_ends_at_the_next_wait_without_an_end_check(self):
		wf, last_state = self._replay(OLD, self.errored, [(APPROVED, DRAFT)])
		self.assertEqual(self._waits(wf), ["Catch_pr"])
		self.assertEqual(last_state, APPROVED)

	def test_an_errored_instance_reaching_a_new_step_with_history_left_is_refused(self):
		nodes = _with(OLD, after={"Task_draft": [("user", "Task_new", "New Step")]})
		self._assert_skip("Past a new step", nodes, self.errored, [(APPROVED, APPROVED)], contains="Task_new")

	def test_a_record_already_on_the_new_map_is_refused(self):
		new_map = _deploy("PLM Rep Taken", OLD)
		record = frappe.db.get_value("BPMN Process Instance", self.waiting_review, "context_docname")
		frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_model": new_map,
				"status": "Active",
				"context_doctype": DT,
				"context_docname": record,
			}
		).insert()
		plm = frappe._dict(
			from_model=self.old_map,
			to_model=new_map,
			target_doctype=DT,
			state_map=[frappe._dict(old_state=DRAFT, new_state=DRAFT)],
		)
		with self.assertRaises(MigrationSkip) as caught:
			replay(build_context(plm), frappe.get_doc("BPMN Process Instance", self.waiting_review))
		self.assertEqual(caught.exception.reason, "Already on new map")

	def test_a_record_whose_state_has_no_mapping_row_is_refused(self):
		self._assert_skip(
			"No state mapping", OLD, self.waiting_review, [(APPROVED, APPROVED)], contains=DRAFT
		)

	def test_scripts_and_emails_on_the_new_map_do_not_run(self):
		nodes = _with(
			OLD, after={"Task_draft": [("script", "Task_script", None), ("email", "Task_email", None)]}
		)
		with (
			patch("frappe.sendmail") as sendmail,
			patch("one_bpmn.processa_engine.runtime.dispatch.dispatch_service_task") as dispatch,
		):
			wf, _last = self._replay(nodes, self.waiting_review, [(DRAFT, DRAFT)])
		self.assertNotIn("script_ran", self._ready(wf, "Task_review").data)
		sendmail.assert_not_called()
		dispatch.assert_not_called()

	def test_a_loop_the_history_cannot_leave_stops_at_the_run_limit(self):
		self._assert_skip(
			"Replay stuck",
			_loop_xml,
			self.waiting_review,
			[(DRAFT, DRAFT)],
			contains="without reaching a wait",
		)

	def test_a_gateway_condition_the_copied_data_cannot_evaluate_stops_the_replay(self):
		def unknown_variable(pid):
			return _loop_xml(pid).replace(
				"<bpmn:conditionExpression>True</bpmn:conditionExpression>",
				"<bpmn:conditionExpression>never_set == 1</bpmn:conditionExpression>",
			)

		self._assert_skip(
			"Replay stuck", unknown_variable, self.waiting_review, [(DRAFT, DRAFT)], contains="never_set"
		)

	def _migrate(self, nodes, old, mapping):
		"""Run migrate_record for one old instance under a Running PLM; returns moved, the PLM and the new instance."""
		new_map = _deploy("PLM Rep Move", nodes)
		with patch("one_bpmn.processa_engine.triggers.on_doc_event"):
			plm = frappe.get_doc(
				{
					"doctype": "Processa Legacy Migration",
					"from_model": frappe.db.get_value("BPMN Process Instance", old, "process_model"),
					"to_model": new_map,
					"target_doctype": DT,
					"status": "Running",
					"state_map": [{"old_state": o, "new_state": n} for o, n in mapping],
				}
			).insert()
		moved = migrate_record(build_context(plm), frappe.get_doc("BPMN Process Instance", old))
		return moved, plm.name, frappe.db.get_value("BPMN Process Instance", {"migrated_from": old}, "name")

	def test_a_clean_replay_creates_the_new_instance_from_the_old_one(self):
		moved, _plm, new = self._migrate(OLD, self.waiting_review, [(DRAFT, DRAFT)])
		self.assertTrue(moved)
		old_doc, new_doc = (frappe.get_doc("BPMN Process Instance", n) for n in (self.waiting_review, new))
		self.assertEqual(new_doc.status, "Active")
		self.assertEqual(new_doc.process_model, "PLM Rep Move")
		self.assertEqual(
			(new_doc.initiated_by, new_doc.started_at), (old_doc.initiated_by, old_doc.started_at)
		)

	def test_waiting_tasks_keep_their_assignment_and_no_email_is_sent(self):
		before = next(
			r
			for r in frappe.get_doc("BPMN Process Instance", self.waiting_review).active_tasks
			if r.status == "Waiting"
		)
		with (
			patch("frappe.sendmail") as sendmail,
			patch("one_bpmn.processa_engine.assignment.notify_task_assignee") as notify,
		):
			_moved, _plm, new = self._migrate(OLD, self.waiting_review, [(DRAFT, DRAFT)])
		after = next(
			r for r in frappe.get_doc("BPMN Process Instance", new).active_tasks if r.status == "Waiting"
		)
		fields = ("assigned_user", "assigned_role", "reliever_user", "relieved_user")
		self.assertEqual([after.get(f) for f in fields], [before.get(f) for f in fields])
		self.assertEqual(after.task_name, "Review")
		sendmail.assert_not_called()
		notify.assert_not_called()

	def test_history_is_copied_with_original_users_and_times_and_both_instances_log_the_move(self):
		fields = ["task_id", "action", "user", "timestamp"]
		old_rows = frappe.get_all(
			"BPMN Activity Log", filters={"instance": self.waiting_review}, fields=fields
		)
		_moved, plm, new = self._migrate(OLD, self.waiting_review, [(DRAFT, DRAFT)])
		new_rows = frappe.get_all("BPMN Activity Log", filters={"instance": new}, fields=[*fields, "data"])
		self.assertEqual(len(new_rows), len(old_rows) + 1)
		copied = {tuple(r[f] for f in fields) for r in new_rows}
		self.assertTrue({tuple(r[f] for f in fields) for r in old_rows} <= copied)
		migrated = next(r for r in new_rows if r.action == "Migrated")
		self.assertEqual(json.loads(migrated.data), {"migrated_from": self.waiting_review, "migration": plm})
		retired = frappe.get_all(
			"BPMN Activity Log", filters={"instance": self.waiting_review, "action": "Retired"}, pluck="data"
		)
		self.assertEqual(json.loads(retired[0]), {"replaced_by": new})

	def test_the_record_moves_to_the_mapped_state_through_the_workflow(self):
		record = frappe.db.get_value("BPMN Process Instance", self.errored, "context_docname")
		modified = frappe.db.get_value(DT, record, "modified")
		with patch.object(
			Document, "run_method", autospec=True, side_effect=Document.run_method
		) as run_method:
			moved, _plm, _new = self._migrate(OLD, self.errored, [(APPROVED, DRAFT)])
		self.assertTrue(moved)
		self.assertEqual(frappe.db.get_value(DT, record, ["workflow_state", "modified"]), (DRAFT, modified))
		self.assertIn("validate", [c.args[1] for c in run_method.call_args_list if c.args[0].doctype == DT])
		self.assertTrue(
			frappe.db.exists(
				"Comment",
				{
					"reference_doctype": DT,
					"reference_name": record,
					"comment_type": "Workflow",
					"content": DRAFT,
				},
			)
		)

	def test_the_open_process_todo_now_names_the_new_instance(self):
		record = frappe.db.get_value("BPMN Process Instance", self.waiting_review, "context_docname")
		todo = frappe.get_all(
			"ToDo", filters={"reference_name": record, "status": "Open", "type": "Process"}, pluck="name"
		)
		_moved, _plm, new = self._migrate(OLD, self.waiting_review, [(DRAFT, DRAFT)])
		status, description = frappe.db.get_value("ToDo", todo[0], ["status", "description"])
		self.assertEqual(status, "Open")
		self.assertIn(new, description)
		self.assertNotIn(self.waiting_review, description)

	def test_the_old_instance_and_its_waiting_tasks_are_cancelled(self):
		self._migrate(OLD, self.waiting_review, [(DRAFT, DRAFT)])
		old = frappe.get_doc("BPMN Process Instance", self.waiting_review)
		self.assertEqual(old.status, "Cancelled")
		self.assertTrue(old.completed_at)
		self.assertNotIn("Waiting", [r.status for r in old.active_tasks])
		self.assertIn("Cancelled", [r.status for r in old.active_tasks])

	def test_an_errored_instance_is_assigned_by_the_map_rules_with_a_new_todo(self):
		moved, _plm, new = self._migrate(_with(OLD, drop="Catch_pr"), self.errored, [(APPROVED, APPROVED)])
		self.assertTrue(moved)
		new_doc = frappe.get_doc("BPMN Process Instance", new)
		row = next(r for r in new_doc.active_tasks if r.status == "Waiting")
		self.assertEqual(
			(new_doc.status, row.task_name, row.assigned_user), ("Active", "Merge", "Administrator")
		)
		self.assertTrue(
			frappe.db.exists(
				"ToDo", {"status": "Open", "type": "Process", "description": ["like", f"%{new}%"]}
			)
		)

	def test_an_error_after_the_insert_rolls_the_record_back_and_logs_reason_error(self):
		with patch(
			"one_bpmn.processa_engine.legacy_migration._repoint_todos",
			side_effect=RuntimeError("todo update failed"),
		):
			moved, plm, new = self._migrate(OLD, self.waiting_review, [(DRAFT, DRAFT)])
		self.assertFalse(moved)
		self.assertIsNone(new)
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self.waiting_review, "status"), "Active"
		)
		row = frappe.get_doc("Processa Legacy Migration", plm).error_logs[0]
		self.assertEqual((row.reason, row.old_instance), ("Error", self.waiting_review))
		self.assertIn("todo update failed", row.error_message)

	def test_a_refused_replay_logs_its_reason_and_leaves_the_old_instance(self):
		moved, plm, new = self._migrate(OLD, self.waiting_review, [(APPROVED, APPROVED)])
		self.assertFalse(moved)
		self.assertIsNone(new)
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self.waiting_review, "status"), "Active"
		)
		row = frappe.get_doc("Processa Legacy Migration", plm).error_logs[0]
		self.assertEqual(
			(row.reason, row.document_name),
			(
				"No state mapping",
				frappe.db.get_value("BPMN Process Instance", self.waiting_review, "context_docname"),
			),
		)
