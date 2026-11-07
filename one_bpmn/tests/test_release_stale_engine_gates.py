# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from one_bpmn.one_bpmn.patches.v1_0 import release_stale_engine_gates

PATCH_PATH = "one_bpmn.one_bpmn.patches.v1_0.release_stale_engine_gates"


class TestReleaseStaleEngineGates(FrappeTestCase):
	def _instance(self, minutes_ago):
		doc = frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_id": f"t-{frappe.generate_hash(length=6)}",
				"status": "Active",
			}
		)
		doc.insert(ignore_permissions=True, ignore_mandatory=True)  # test fixture, no model needed
		frappe.db.set_value(
			"BPMN Process Instance",
			doc.name,
			{
				"engine_in_progress": 1,
				"modified": add_to_date(now_datetime(), minutes=-minutes_ago),
			},
			update_modified=False,
		)
		return doc.name

	def _state(self, name):
		return frappe.db.get_value(
			"BPMN Process Instance", name, ["engine_in_progress", "modified"], as_dict=True
		)

	def test_a_gate_untouched_for_thirty_minutes_is_cleared(self):
		stale = self._instance(minutes_ago=30)
		release_stale_engine_gates.execute()
		self.assertEqual(self._state(stale).engine_in_progress, 0)

	def test_a_gate_touched_just_now_is_kept(self):
		fresh = self._instance(minutes_ago=0)
		release_stale_engine_gates.execute()
		self.assertEqual(self._state(fresh).engine_in_progress, 1)

	def test_a_second_run_changes_nothing(self):
		stale = self._instance(minutes_ago=30)
		fresh = self._instance(minutes_ago=0)
		release_stale_engine_gates.execute()
		after_first = (self._state(stale), self._state(fresh))
		release_stale_engine_gates.execute()
		self.assertEqual((self._state(stale), self._state(fresh)), after_first)

	def test_clearing_the_gate_leaves_modified_alone(self):
		stale = self._instance(minutes_ago=30)
		before = self._state(stale).modified
		release_stale_engine_gates.execute()
		self.assertEqual(self._state(stale).modified, before)

	def test_the_patch_is_registered_after_model_sync(self):
		with open(frappe.get_app_path("one_bpmn", "patches.txt")) as f:
			text = f.read()
		post_model_sync = text.split("[post_model_sync]", 1)[1]
		registered = [line.split("#")[0].strip() for line in post_model_sync.splitlines()]
		self.assertEqual(registered.count(PATCH_PATH), 1)
