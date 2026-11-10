# Copyright (c) 2026, one-fm and contributors
"""Moving a record to a new map: where the replay ends, every reason it stops, and the instance swap."""

import json
from unittest.mock import patch

import frappe
from frappe.model.document import Document
from frappe.tests.utils import FrappeTestCase
from rq.timeouts import JobTimeoutException

from one_bpmn.processa_engine import legacy_migration
from one_bpmn.processa_engine.engine import TaskState
from one_bpmn.processa_engine.legacy_migration import (
	MigrationSkip,
	build_context,
	migrate_record,
	replay,
	wait_ids,
)
from one_bpmn.tests.factories.legacy_migration_maps import (
	APPROVED,
	DONE,
	DRAFT,
	DT,
	OLD,
	PR_OPENED,
	deploy,
	loop_xml,
	migration,
	old_instance,
	run_start,
	with_changes,
)


class TestLegacyMigrationReplay(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for state in (DRAFT, APPROVED, DONE):
			frappe.get_doc(
				{"doctype": "Workflow State", "workflow_state_name": state, "style": "Primary"}
			).insert()
		cls.old_map = deploy("PLM Rep Old", OLD)
		deploy("PLM Rep Sub", [("user", "Task_sub", "Sub Review")])
		cls.call_map = deploy(
			"PLM Rep Call", [("state", "Task_draft", DRAFT), ("call", "Call_sub", "plm_rep_sub")]
		)

		cls.waiting_review = old_instance(cls.old_map)
		cls.waiting_pr = old_instance(cls.old_map, "Task_review")
		cls.waiting_merge = old_instance(cls.old_map, "Task_review", PR_OPENED)
		cls.call_running = old_instance(cls.call_map)
		cls.errored = old_instance(cls.old_map, "Task_review")
		frappe.db.set_value("BPMN Process Instance", cls.errored, "status", "Errored")

	def setUp(self):
		super().setUp()
		# A map active on the site for the test DocType would otherwise start when a record is saved.
		trigger = patch("one_bpmn.processa_engine.triggers.on_doc_event")
		trigger.start()
		self.addCleanup(trigger.stop)
		# FrappeTestCase rolls back per class; the savepoint keeps each test's rows out of the next.
		frappe.db.savepoint("plm_replay_test")
		self.addCleanup(frappe.db.rollback, save_point="plm_replay_test")

	def _replay(self, nodes_or_xml, old, mapping, title="PLM Rep New"):
		new_map = deploy(title, nodes_or_xml)
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
		nodes = with_changes(OLD, relabel={"Task_review": "Manager Review"})
		wf, last_state = self._replay(nodes, self.waiting_pr, [(APPROVED, APPROVED)])
		self.assertEqual(self._waits(wf), ["Catch_pr"])
		review = next(t for t in wf.get_tasks() if t.task_spec.bpmn_id == "Task_review")
		self.assertEqual(review.data["action"], "Approve")
		self.assertEqual(last_state, APPROVED)

	def test_a_user_task_the_new_map_removed_is_ignored(self):
		wf, _last = self._replay(
			with_changes(OLD, drop="Task_review"), self.waiting_pr, [(APPROVED, APPROVED)]
		)
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
		nodes = with_changes(OLD, after={"Task_draft": [("user", "Task_new", "New Step")]})
		self._assert_skip(
			"Past a new step", nodes, self.waiting_review, [(DRAFT, DRAFT)], contains="Task_new"
		)

	def test_a_new_user_task_after_the_wait_point_lets_the_record_move(self):
		nodes = with_changes(OLD, after={"Task_review": [("user", "Task_new", "New Step")]})
		wf, _last = self._replay(nodes, self.waiting_review, [(DRAFT, DRAFT)])
		self.assertEqual(self._waits(wf), ["Task_review"])

	def test_an_instance_waiting_at_a_removed_step_is_refused(self):
		self._assert_skip(
			"Waiting at removed step",
			with_changes(OLD, drop="Task_review"),
			self.waiting_review,
			[(DRAFT, DRAFT)],
		)

	def test_an_unfinished_call_activity_is_refused(self):
		self._assert_skip("Sub-process running", OLD, self.call_running, [(DRAFT, DRAFT)])

	def test_a_call_activity_in_the_new_map_completes_without_its_sub_process(self):
		nodes = with_changes(OLD, after={"Task_draft": [("call", "Call_sub", "plm_rep_sub")]})
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
		nodes = with_changes(OLD, after={"Task_draft": [("user", "Task_new", "New Step")]})
		self._assert_skip("Past a new step", nodes, self.errored, [(APPROVED, APPROVED)], contains="Task_new")

	def test_a_record_already_on_the_new_map_is_refused(self):
		new_map = deploy("PLM Rep Taken", OLD)
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
		nodes = with_changes(
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
			loop_xml,
			self.waiting_review,
			[(DRAFT, DRAFT)],
			contains="without reaching a wait",
		)

	def test_a_gateway_condition_the_copied_data_cannot_evaluate_stops_the_replay(self):
		def unknown_variable(pid):
			return loop_xml(pid).replace(
				"<bpmn:conditionExpression>True</bpmn:conditionExpression>",
				"<bpmn:conditionExpression>never_set == 1</bpmn:conditionExpression>",
			)

		self._assert_skip(
			"Replay stuck", unknown_variable, self.waiting_review, [(DRAFT, DRAFT)], contains="never_set"
		)

	def _migrate(self, nodes, old, mapping):
		"""migrate_record for one old instance under a Running PLM; returns moved, PLM, new instance."""
		from_model = frappe.db.get_value("BPMN Process Instance", old, "process_model")
		name = migration(from_model, deploy("PLM Rep Move", nodes), mapping, status="Running")
		plm = frappe.get_doc("Processa Legacy Migration", name)
		moved = migrate_record(build_context(plm), frappe.get_doc("BPMN Process Instance", old))
		return moved, name, frappe.db.get_value("BPMN Process Instance", {"migrated_from": old}, "name")

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
		moved, _plm, new = self._migrate(
			with_changes(OLD, drop="Catch_pr"), self.errored, [(APPROVED, APPROVED)]
		)
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

	def _batch_plm(self, to_model, mapping, run_by=None):
		"""A Queued PLM from the old map."""
		return migration(self.old_map, to_model, mapping, status="Queued", run_by=run_by)

	def _start(self, migration_name, run_jobs=True):
		return run_start(migration_name, run_jobs)

	def _plm_row(self, name):
		return frappe.get_doc("Processa Legacy Migration", name)

	def test_start_splits_open_instances_into_batches_on_the_long_queue(self):
		name = self._batch_plm(deploy("PLM Rep Batch", OLD), [(DRAFT, DRAFT), (APPROVED, APPROVED)])
		with patch.object(legacy_migration, "BATCH_SIZE", 2):
			jobs, _errors = self._start(name, run_jobs=False)
		plm = self._plm_row(name)
		self.assertEqual((plm.total_records, plm.total_batches, plm.status), (4, 2, "Running"))
		self.assertEqual([k["job_id"] for _m, k in jobs], [f"plm::{name}::1", f"plm::{name}::2"])
		self.assertEqual(
			{(m, k["queue"]) for m, k in jobs},
			{("one_bpmn.processa_engine.legacy_migration.run_batch", "long")},
		)

	def test_batch_size_or_fewer_open_instances_queue_one_job(self):
		name = self._batch_plm(deploy("PLM Rep Batch", OLD), [(DRAFT, DRAFT), (APPROVED, APPROVED)])
		jobs, _errors = self._start(name, run_jobs=False)
		self.assertEqual(len(jobs), 1)
		self.assertEqual(len(jobs[0][1]["instance_names"]), 4)

	def test_no_open_instances_completes_without_a_batch(self):
		empty = deploy("PLM Rep Empty", OLD)
		name = migration(empty, self.old_map, [(DRAFT, DRAFT)], status="Queued")
		jobs, _errors = self._start(name)
		self.assertEqual(jobs, [])
		self.assertEqual((self._plm_row(name).status, self._plm_row(name).total_batches), ("Completed", 0))

	def test_all_batches_add_up_and_finish_runs_once(self):
		name = self._batch_plm(deploy("PLM Rep Batch", OLD), [(DRAFT, DRAFT), (APPROVED, APPROVED)])
		with (
			patch.object(legacy_migration, "BATCH_SIZE", 2),
			patch.object(legacy_migration, "finish", wraps=legacy_migration.finish) as finish,
		):
			_jobs, errors = self._start(name)
		plm = self._plm_row(name)
		self.assertEqual(errors, [])
		self.assertEqual((plm.migrated_count, plm.failed_count, plm.batches_done), (4, 0, 2))
		self.assertEqual(plm.status, "Completed")
		finish.assert_called_once_with(name)

	def test_a_timeout_logs_the_record_in_progress_and_the_rest_of_its_batch_only(self):
		name = self._batch_plm(deploy("PLM Rep Batch", OLD), [(DRAFT, DRAFT), (APPROVED, APPROVED)])
		real, calls = legacy_migration.migrate_record, []

		def migrate(ctx, old):
			calls.append(old.name)
			if len(calls) == 1:
				raise JobTimeoutException("Task exceeded maximum timeout value (600 seconds)")
			return real(ctx, old)

		with (
			patch.object(legacy_migration, "BATCH_SIZE", 2),
			patch.object(legacy_migration, "migrate_record", side_effect=migrate),
		):
			jobs, errors = self._start(name)
		plm = self._plm_row(name)
		first_batch = jobs[0][1]["instance_names"]
		self.assertIsInstance(errors[0], JobTimeoutException)
		self.assertEqual(
			sorted(r.old_instance for r in plm.error_logs if r.reason == "Timed out"), sorted(first_batch)
		)
		self.assertEqual((plm.migrated_count, plm.failed_count, plm.batches_done), (2, 2, 2))

	def test_a_batch_that_fails_before_its_records_logs_each_with_reason_error(self):
		name = self._batch_plm(deploy("PLM Rep Batch", OLD), [(DRAFT, DRAFT), (APPROVED, APPROVED)])
		with patch.object(legacy_migration, "build_context", side_effect=RuntimeError("maps failed to load")):
			_jobs, errors = self._start(name)
		plm = self._plm_row(name)
		self.assertIsInstance(errors[0], RuntimeError)
		self.assertEqual([r.reason for r in plm.error_logs], ["Error"] * 4)
		self.assertIn("maps failed to load", plm.error_logs[0].error_message)
		self.assertEqual((plm.batches_done, plm.failed_count, plm.status), (1, 4, "Failed"))

	def test_finish_sets_the_outcome_publishes_the_last_event_and_tells_the_own_process(self):
		name = self._batch_plm(deploy("PLM Rep Batch", OLD), [(DRAFT, DRAFT), (APPROVED, APPROVED)])
		own = (
			frappe.get_doc(
				{
					"doctype": "BPMN Process Instance",
					"process_model": self.old_map,
					"status": "Active",
					"context_doctype": "Processa Legacy Migration",
					"context_docname": name,
				}
			)
			.insert()
			.name
		)
		with (
			patch("frappe.publish_realtime") as publish,
			patch.object(legacy_migration, "receive_message") as message,
		):
			self._start(name)
		plm = self._plm_row(name)
		self.assertEqual(plm.status, "Completed")
		self.assertTrue(plm.completed_at)
		self.assertTrue(publish.call_args_list[-1].args[1]["completed"])
		self.assertEqual(message.call_args.args[0].name, own)
		self.assertEqual(
			message.call_args.args[1:], (legacy_migration.FINISHED_MESSAGE, {"migration_status": "Completed"})
		)

	def test_a_run_by_who_no_longer_owns_the_process_fails_without_moving_anything(self):
		user = "_plm_rep_owner@example.com"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": user,
				"first_name": "plm",
				"send_welcome_email": 0,
				"roles": [{"role": "Process Owner"}],
			}
		).insert()
		name = self._batch_plm(
			deploy("PLM Rep Batch", OLD), [(DRAFT, DRAFT), (APPROVED, APPROVED)], run_by=user
		)
		jobs, _errors = self._start(name)
		plm = self._plm_row(name)
		self.assertEqual(jobs, [])
		self.assertEqual(plm.status, "Failed")
		self.assertIn("not the Process Owner", plm.error_logs[0].error_message)
		self.assertEqual(
			frappe.db.get_value("BPMN Process Instance", self.waiting_review, "status"), "Active"
		)

	def test_a_second_run_after_a_full_run_finds_nothing_to_move(self):
		new_map = deploy("PLM Rep Batch", OLD)
		self._start(self._batch_plm(new_map, [(DRAFT, DRAFT), (APPROVED, APPROVED)]))
		second = self._batch_plm(new_map, [(DRAFT, DRAFT), (APPROVED, APPROVED)])
		jobs, _errors = self._start(second)
		plm = self._plm_row(second)
		self.assertEqual(jobs, [])
		self.assertEqual((plm.total_records, plm.migrated_count, plm.status), (0, 0, "Completed"))

	def test_migrate_record_lets_a_timeout_reach_the_batch(self):
		with (
			patch.object(legacy_migration, "replay", side_effect=JobTimeoutException("timeout")),
			self.assertRaises(JobTimeoutException),
		):
			self._migrate(OLD, self.waiting_review, [(DRAFT, DRAFT)])

	def _stalled_plm(self, status="Running", new_map=None):
		"""A PLM part way through: 2 batches queued, 1 done, the waiting_review record already logged."""
		new_map = new_map or deploy("PLM Rep Batch", OLD)
		name = self._batch_plm(new_map, [(DRAFT, DRAFT), (APPROVED, APPROVED)])
		frappe.db.set_value(
			"Processa Legacy Migration",
			name,
			{"status": status, "total_records": 4, "total_batches": 2, "batches_done": 1, "failed_count": 1},
		)
		legacy_migration.log_error_row(
			name, frappe.get_doc("BPMN Process Instance", self.waiting_review), "Replay stuck", "stuck"
		)
		return name

	def _check_stalled(self, jobs_alive):
		with (
			patch.object(legacy_migration, "is_job_enqueued", return_value=jobs_alive) as enqueued,
			patch.object(frappe.db, "commit"),
		):
			legacy_migration.fail_stalled_migrations()
		return enqueued

	def test_a_run_with_no_live_jobs_logs_what_it_never_reached_and_finishes(self):
		name = self._stalled_plm()
		frappe.db.set_value("BPMN Process Instance", self.waiting_pr, "status", "Completed")
		enqueued = self._check_stalled(jobs_alive=False)
		plm = self._plm_row(name)
		timed_out = sorted(r.old_instance for r in plm.error_logs if r.reason == "Timed out")
		self.assertEqual(timed_out, sorted([self.waiting_merge, self.errored]))
		self.assertEqual((plm.failed_count, plm.status), (3, "Failed"))
		self.assertTrue(plm.completed_at)
		checked = {c.args[0] for c in enqueued.call_args_list if f"::{name}::" in c.args[0]}
		self.assertEqual(checked, {f"plm::{name}::start", f"plm::{name}::1", f"plm::{name}::2"})

	def test_a_run_with_a_live_job_is_left_alone(self):
		name = self._stalled_plm()
		self._check_stalled(jobs_alive=True)
		plm = self._plm_row(name)
		self.assertEqual((plm.status, plm.failed_count, len(plm.error_logs)), ("Running", 1, 1))

	def test_a_completed_or_failed_run_is_not_checked(self):
		new_map = deploy("PLM Rep Batch", OLD)
		for status in ("Completed", "Failed"):
			name = self._stalled_plm(status=status, new_map=new_map)
			enqueued = self._check_stalled(jobs_alive=False)
			plm = self._plm_row(name)
			self.assertEqual((plm.status, len(plm.error_logs)), (status, 1))
			self.assertFalse([c for c in enqueued.call_args_list if f"::{name}::" in c.args[0]])

	def test_the_check_is_scheduled_hourly(self):
		self.assertIn(
			"one_bpmn.processa_engine.legacy_migration.fail_stalled_migrations",
			frappe.get_hooks("scheduler_events")["hourly"],
		)
