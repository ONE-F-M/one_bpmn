# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A migration is refused on save unless its maps, state mapping and process ownership let it run."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

DT = "GP Letter Request"
OPEN, HOLD, DONE = "PLM Val Open", "PLM Val Hold", "PLM Val Done"
OWNER = "_plm_val_owner@example.com"
OTHER_OWNER = "_plm_val_other@example.com"
NOBODY = "_plm_val_nobody@example.com"
OWNED_PROCESS, OTHER_PROCESS = "PLM Val Owned", "PLM Val Other"

XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_{pid}"
  targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="{pid}" isExecutable="true">
    <bpmn:startEvent id="Start_1"><bpmn:outgoing>Flow_1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
    <bpmn:endEvent id="End_1"><bpmn:incoming>Flow_1</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""


def _user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			}
		).insert()


def _model(title, process, doctype=DT, sets_states=(OPEN, DONE), deployed=True):
	pid = frappe.scrub(title)
	model = frappe.get_doc(
		{
			"doctype": "BPMN Process Model",
			"title": title,
			"process_name": process,
			"process_id": pid,
			"version": 1,
			"bpmn_xml": XML.format(pid=pid),
			"target_doctypes": [{"doctype_name": doctype}],
		}
	)
	model.flags.skip_editability_check = True
	model.insert()
	if deployed:
		spec = {"service_task_extensions": {f"t{i}": {"workflowState": s} for i, s in enumerate(sets_states)}}
		model.db_set("serialized_spec", json.dumps(spec))
	return model.name


class TestProcessaLegacyMigrationValidation(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		with patch("one_bpmn.processa_engine.triggers.on_doc_event"):
			for state in (OPEN, HOLD, DONE):
				frappe.get_doc(
					{"doctype": "Workflow State", "workflow_state_name": state, "style": "Primary"}
				).insert()
			_user(OWNER, ["Process Owner"])
			_user(OTHER_OWNER, ["Process Owner"])
			_user(NOBODY, ["Blogger"])
			for process, owner in ((OWNED_PROCESS, OWNER), (OTHER_PROCESS, OTHER_OWNER)):
				frappe.get_doc(
					{
						"doctype": "Process",
						"process_name": process,
						"process_owner": owner,
						"description": "Test",
					}
				).insert()
			cls.old_map = _model("PLM Val Old", OWNED_PROCESS)
			cls.new_map = _model("PLM Val New", OWNED_PROCESS)
			cls._open_record(OPEN)
			cls._open_record(OPEN)

	def setUp(self):
		super().setUp()
		trigger = patch("one_bpmn.processa_engine.triggers.on_doc_event")
		trigger.start()
		self.addCleanup(trigger.stop)
		# FrappeTestCase rolls back per class; the savepoint keeps each test's rows out of the next.
		frappe.db.savepoint("plm_validation_test")
		self.addCleanup(frappe.db.rollback, save_point="plm_validation_test")

	@classmethod
	def _open_record(cls, state):
		name = frappe.get_doc({"doctype": DT}).insert().name
		frappe.db.set_value(DT, name, "workflow_state", state)
		frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_model": cls.old_map,
				"status": "Active",
				"context_doctype": DT,
				"context_docname": name,
			}
		).insert()
		return name

	def _migration(self, **overrides):
		values = {
			"doctype": "Processa Legacy Migration",
			"from_model": self.old_map,
			"to_model": self.new_map,
			"target_doctype": DT,
			"state_map": [{"old_state": OPEN, "new_state": OPEN}],
		}
		values.update(overrides)
		return frappe.get_doc(values)

	def _assert_refused(self, migration, *words):
		with self.assertRaises(frappe.ValidationError) as caught:
			migration.insert()
		for word in words:
			self.assertIn(word, str(caught.exception))

	def test_a_valid_migration_saves_and_counts_records_per_old_state(self):
		name = self._migration().insert().name
		stored = frappe.get_doc("Processa Legacy Migration", name)
		self.assertEqual((stored.from_model, stored.to_model), (self.old_map, self.new_map))
		self.assertEqual([(d.old_state, d.record_count) for d in stored.state_map], [(OPEN, 2)])

	def test_a_missing_new_process_map_is_refused(self):
		with self.assertRaises(frappe.MandatoryError):
			self._migration(to_model="").insert()

	def test_the_same_map_twice_is_refused(self):
		self._assert_refused(self._migration(to_model=self.old_map), "must be different")

	def test_a_new_map_never_deployed_is_refused(self):
		undeployed = _model("PLM Val Undeployed", OWNED_PROCESS, deployed=False)
		self._assert_refused(self._migration(to_model=undeployed), undeployed, "is not currently deployed")

	def test_maps_for_different_doctypes_are_refused(self):
		note_map = _model("PLM Val Note Map", OWNED_PROCESS, doctype="Note")
		self._assert_refused(self._migration(to_model=note_map), DT, "Note")

	def test_a_duplicate_old_state_is_refused(self):
		rows = [{"old_state": OPEN, "new_state": OPEN}, {"old_state": OPEN, "new_state": DONE}]
		self._assert_refused(self._migration(state_map=rows), OPEN, "more than once")

	def test_a_new_state_the_new_map_never_sets_is_refused(self):
		self._assert_refused(self._migration(state_map=[{"old_state": OPEN, "new_state": HOLD}]), HOLD)

	def test_open_records_in_an_unmapped_state_are_refused_with_their_count(self):
		self._open_record(HOLD)
		self._assert_refused(self._migration(), f"{HOLD} (1)")

	def test_a_target_doctype_without_a_state_field_is_refused(self):
		old_note, new_note = (
			_model(f"PLM Val Note {v}", OWNED_PROCESS, doctype="Note") for v in ("Old", "New")
		)
		migration = self._migration(from_model=old_note, to_model=new_note, target_doctype="Note")
		self._assert_refused(migration, "Note", "workflow_state")

	def test_a_target_doctype_neither_map_runs_on_is_refused(self):
		self._assert_refused(self._migration(target_doctype="ToDo"), self.old_map, DT, "ToDo")

	def test_an_engine_save_that_changes_the_setup_is_still_checked(self):
		name = self._migration().insert().name
		migration = frappe.get_doc("Processa Legacy Migration", name)
		migration.to_model = self.old_map
		with patch.dict(frappe.local.flags, {"bpmn_engine_action": True}):
			with self.assertRaises(frappe.ValidationError) as caught:
				migration.save()
		self.assertIn("must be different", str(caught.exception))

	def test_an_engine_save_that_leaves_the_setup_alone_skips_the_checks(self):
		name = self._migration().insert().name
		self._open_record(HOLD)
		migration = frappe.get_doc("Processa Legacy Migration", name)
		migration.workflow_state = DONE
		with patch.dict(frappe.local.flags, {"bpmn_engine_action": True}):
			migration.save()
		self.assertEqual(frappe.db.get_value("Processa Legacy Migration", name, "workflow_state"), DONE)

	def test_a_process_owner_of_both_maps_saves_and_sees_only_their_migrations(self):
		other = self._migration().insert().name
		with self.set_user(OWNER):
			mine = self._migration().insert().name
			visible = frappe.get_list("Processa Legacy Migration", pluck="name")
		self.assertEqual(visible, [mine])
		self.assertNotIn(other, visible)

	def test_a_process_owner_of_only_one_map_is_refused(self):
		foreign_map = _model("PLM Val Foreign", OTHER_PROCESS)
		with self.set_user(OWNER), self.assertRaises(frappe.PermissionError):
			self._migration(to_model=foreign_map).insert()
		self.assertFalse(frappe.db.exists("Processa Legacy Migration", {"to_model": foreign_map}))

	def test_a_user_without_either_role_cannot_create_a_migration(self):
		with self.set_user(NOBODY), self.assertRaises(frappe.PermissionError):
			self._migration().insert()

	def test_checks_are_skipped_once_the_migration_has_left_draft(self):
		for status in ("Queued", "Running", "Completed"):
			name = self._migration(status=status, to_model=self.old_map).insert().name
			self.assertTrue(frappe.db.exists("Processa Legacy Migration", name))
