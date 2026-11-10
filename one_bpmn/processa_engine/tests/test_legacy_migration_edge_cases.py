# Copyright (c) 2026, one-fm and contributors
"""Records that change while a migration runs, a record moved twice, and runs whose jobs or checks fail."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.processa_engine import legacy_migration
from one_bpmn.processa_engine.engine import restore_workflow
from one_bpmn.processa_engine.legacy_migration import build_context, migrate_record, wait_ids
from one_bpmn.tests.factories.legacy_migration_maps import (
	APPROVED,
	DONE,
	DRAFT,
	DT,
	OLD,
	PR_OPENED,
	deploy,
	migration,
	old_instance,
	run_batch_jobs,
	run_start,
	with_changes,
)

MAPPING = [(DRAFT, DRAFT), (APPROVED, APPROVED)]
NOBODY = "_plm_edge_nobody@example.com"


class TestLegacyMigrationEdgeCases(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for state in (DRAFT, APPROVED, DONE):
			if not frappe.db.exists("Workflow State", state):
				frappe.get_doc(
					{"doctype": "Workflow State", "workflow_state_name": state, "style": "Primary"}
				).insert()
		frappe.get_doc(
			{
				"doctype": "User",
				"email": NOBODY,
				"first_name": "plm",
				"send_welcome_email": 0,
				"roles": [{"role": "Blogger"}],
			}
		).insert()
		cls.old_map = deploy("PLM Edge Old", OLD)
		cls.new_map = deploy("PLM Edge New", OLD)
		cls.waiting_review = old_instance(cls.old_map)
		cls.waiting_pr = old_instance(cls.old_map, "Task_review")
		cls.waiting_merge = old_instance(cls.old_map, "Task_review", PR_OPENED)
		cls.second_review = old_instance(cls.old_map)

	def setUp(self):
		super().setUp()
		trigger = patch("one_bpmn.processa_engine.triggers.on_doc_event")
		trigger.start()
		self.addCleanup(trigger.stop)
		# FrappeTestCase rolls back per class; the savepoint keeps each test's rows out of the next.
		frappe.db.savepoint("plm_edge_test")
		self.addCleanup(frappe.db.rollback, save_point="plm_edge_test")

	def _move(self, old, to_model):
		"""migrate_record under a Running PLM; returns moved, the PLM and the new instance."""
		from_model = frappe.db.get_value("BPMN Process Instance", old, "process_model")
		name = migration(from_model, to_model, MAPPING, status="Running")
		ctx = build_context(frappe.get_doc("Processa Legacy Migration", name))
		moved = migrate_record(ctx, frappe.get_doc("BPMN Process Instance", old), 1)
		return moved, name, frappe.db.get_value("BPMN Process Instance", {"migrated_from": old}, "name")

	@staticmethod
	def _plm(name):
		return frappe.get_doc("Processa Legacy Migration", name)

	def test_a_record_moved_once_moves_again_to_a_newer_map(self):
		# The script step shifts every later task's id, so the copied Review row matches no task on this map.
		shifted = deploy(
			"PLM Edge Shifted", with_changes(OLD, after={"Task_draft": [("script", "Task_s", None)]})
		)
		_moved, _plm, first = self._move(self.waiting_pr, shifted)
		newer = deploy("PLM Edge Newer", with_changes(OLD, relabel={"Task_review": "Manager Review"}))
		moved, plm, second = self._move(first, newer)
		self.assertEqual(self._plm(plm).error_logs, [])
		logged = frappe.get_all(
			"BPMN Activity Log",
			filters={"instance": second, "action": "Migrated"},
			pluck="data",
			order_by="timestamp asc, creation asc",
		)
		self.assertEqual(json.loads(logged[-1]), {"migrated_from": first, "migration": plm})
		self.assertTrue(moved)
		workflow_state = frappe.db.get_value("BPMN Process Instance", second, "workflow_state")
		self.assertEqual(wait_ids(restore_workflow(json.loads(workflow_state))), {"Catch_pr"})

	def test_a_record_moved_twice_moves_a_third_time(self):
		shifted = deploy(
			"PLM Edge Shifted", with_changes(OLD, after={"Task_draft": [("script", "Task_s", None)]})
		)
		relabelled = deploy(
			"PLM Edge Relabelled", with_changes(OLD, relabel={"Task_review": "Manager Review"})
		)
		_moved, _plm, first = self._move(self.waiting_pr, shifted)
		_moved, _plm, second = self._move(first, relabelled)
		moved, plm, third = self._move(second, self.new_map)
		self.assertEqual(self._plm(plm).error_logs, [])
		self.assertTrue(moved)
		workflow_state = frappe.db.get_value("BPMN Process Instance", third, "workflow_state")
		self.assertEqual(wait_ids(restore_workflow(json.loads(workflow_state))), {"Catch_pr"})

	def test_an_instance_that_finished_after_the_run_started_is_not_moved(self):
		frappe.db.set_value("BPMN Process Instance", self.waiting_review, "status", "Completed")
		record = frappe.db.get_value("BPMN Process Instance", self.waiting_review, "context_docname")
		moved, plm, new = self._move(self.waiting_review, self.new_map)
		self.assertFalse(moved)
		self.assertIsNone(new)
		row = self._plm(plm).error_logs[0]
		self.assertEqual((row.reason, row.old_instance), ("No longer open", self.waiting_review))
		self.assertEqual(frappe.db.get_value(DT, record, "workflow_state"), DRAFT)

	def test_an_instance_deleted_after_the_run_started_is_logged_and_its_batch_counted(self):
		name = migration(self.old_map, self.new_map, MAPPING, status="Queued")
		jobs, _errors = run_start(name, run_jobs=False)
		frappe.db.delete("BPMN Process Instance", self.waiting_review)
		errors = run_batch_jobs(jobs)
		plm = self._plm(name)
		self.assertEqual(errors, [])
		self.assertEqual(
			[(r.reason, r.old_instance) for r in plm.error_logs], [("No longer open", self.waiting_review)]
		)
		self.assertEqual(
			(plm.migrated_count, plm.failed_count, plm.batches_done, plm.status), (3, 1, 1, "Completed")
		)

	def test_error_log_rows_keep_their_place_when_batches_run_out_of_order(self):
		name = migration(self.old_map, self.new_map, [(DONE, DONE)], status="Queued")
		with patch.object(legacy_migration, "BATCH_SIZE", 2):
			jobs, _errors = run_start(name, run_jobs=False)
		run_batch_jobs(list(reversed(jobs)))
		order = [n for _m, kwargs in jobs for n in kwargs["instance_names"]]
		rows = {r.old_instance: r.idx for r in self._plm(name).error_logs}
		self.assertEqual(rows, {n: i for i, n in enumerate(order, start=1)})

	def test_a_finish_that_fails_keeps_the_last_batch_counted(self):
		name = migration(self.old_map, self.new_map, MAPPING, status="Queued")
		with patch.object(legacy_migration, "finish", side_effect=RuntimeError("message failed")):
			_jobs, errors = run_start(name)
		plm = self._plm(name)
		self.assertIsInstance(errors[0], RuntimeError)
		self.assertEqual((plm.batches_done, plm.total_batches, plm.migrated_count), (1, 1, 4))

	def test_one_failing_migration_does_not_stop_the_hourly_check(self):
		first, second = (migration(self.old_map, self.new_map, MAPPING, status="Running") for _ in range(2))
		for name in (self.waiting_pr, self.waiting_merge):
			frappe.db.set_value("BPMN Process Instance", name, "status", "Cancelled")
		real_finish = legacy_migration.finish

		def finish(migration_name):
			if migration_name == first:
				raise RuntimeError("finish failed")
			real_finish(migration_name)

		frappe.db.savepoint("plm_stalled_test")
		rollback = frappe.db.rollback
		with (
			patch.object(legacy_migration, "finish", side_effect=finish),
			patch.object(legacy_migration, "is_job_enqueued", return_value=False),
			patch.object(frappe.db, "commit", side_effect=lambda: frappe.db.savepoint("plm_stalled_test")),
			patch.object(
				frappe.db, "rollback", side_effect=lambda **kw: rollback(save_point="plm_stalled_test")
			),
		):
			legacy_migration.fail_stalled_migrations()
		self.assertEqual(frappe.db.get_value("Processa Legacy Migration", first, "status"), "Running")
		self.assertEqual(frappe.db.get_value("Processa Legacy Migration", second, "status"), "Failed")
		self.assertTrue(
			frappe.db.exists(
				"Error Log", {"reference_doctype": "Processa Legacy Migration", "reference_name": first}
			)
		)

	def test_a_todo_that_names_a_longer_instance_name_is_left_alone(self):
		record = frappe.db.get_value("BPMN Process Instance", self.waiting_review, "context_docname")
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"allocated_to": "Administrator",
				"reference_type": DT,
				"reference_name": record,
				"description": f'BPMN Task: "Other" on instance {self.waiting_review}9',
				"status": "Open",
			}
		).insert()
		frappe.db.set_value("ToDo", todo.name, "type", "Process")
		moved, _plm, _new = self._move(self.waiting_review, self.new_map)
		self.assertTrue(moved)
		self.assertEqual(frappe.db.get_value("ToDo", todo.name, "description"), todo.description)

	def test_a_batch_run_by_a_user_without_either_role_moves_nothing(self):
		name = migration(self.old_map, self.new_map, MAPPING, status="Running")
		with self.set_user(NOBODY), patch.dict(frappe.local.flags, {"in_test": False}):
			errors = run_batch_jobs(
				[(None, {"migration_name": name, "instance_names": [self.second_review], "first_idx": 1})]
			)
		self.assertIsInstance(errors[0], frappe.PermissionError)
		self.assertEqual(frappe.db.get_value("BPMN Process Instance", self.second_review, "status"), "Active")
		self.assertEqual([r.reason for r in self._plm(name).error_logs], ["Error"])
