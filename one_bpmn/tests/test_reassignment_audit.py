# Copyright (c) 2026, one-fm and contributors
"""
WI-001998 — a User Task reassignment is recorded in the map's version history
and nowhere else.

The acceptance criterion is a negative one ("no log is done outside the version
history"), and a negative is easy to satisfy by accident and just as easy to
undo by accident. So both halves are asserted: that the separate log is gone,
and that the version history really does carry the change it was duplicating.

The second half is the one that matters. Deleting the log is only safe because
BPMN Process Model has track_changes on, so saving the map writes a Version
holding the bpmn_xml before and after — and the reassignment IS that diff. If
that ever stopped being true, this story would have removed the audit trail
rather than de-duplicated it, and this test is what would say so.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import frappe
from frappe.tests.utils import FrappeTestCase
from lxml import etree

from one_bpmn.api import reassignment as R

PREFIX = "ZZ Reassign"

XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
                  id="defs_zz" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="zz_proc" isExecutable="true">
    <bpmn:userTask id="zz_task" name="Approve the thing" />
  </bpmn:process>
</bpmn:definitions>"""


class TestReassignmentAudit(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._cleanup()

		self.original_instance_type = frappe.db.get_single_value("Processa Settings", "instance_type")
		# Reassign is Production-only, and that guard runs before anything else —
		# without this the endpoint refuses and the test proves nothing.
		self._set_instance_type("Production")

		# process_name is a Link to Process and is optional — left unset rather
		# than inventing a Process record this test has no use for.
		self.model = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"title": f"{PREFIX} model",
			"process_id": "zz_proc",
			"version": 1,
			"bpmn_xml": XML,
		}).insert(ignore_permissions=True).name

	def tearDown(self):
		self._set_instance_type(self.original_instance_type)
		self._cleanup()
		frappe.db.commit()

	def _set_instance_type(self, value):
		frappe.db.set_single_value("Processa Settings", "instance_type", value)
		frappe.clear_cache(doctype="Processa Settings")

	@staticmethod
	@contextmanager
	def _versioning_on():
		"""Frappe does not write Version rows under the test runner.

		``Document._save`` sets ``ignore_version = frappe.flags.in_test`` unless
		told otherwise, so a test asserting "the save records a Version" measures
		the harness rather than the behaviour and passes vacuously in reverse —
		it always finds zero. reassign_user_task calls doc.save() itself, so the
		flag cannot be passed in; it has to be cleared around the call for this to
		exercise what production does.
		"""
		was = frappe.flags.in_test
		frappe.flags.in_test = False
		try:
			yield
		finally:
			frappe.flags.in_test = was

	def _cleanup(self):
		for name in frappe.get_all("BPMN Process Model", filters={"title": ("like", f"{PREFIX}%")}, pluck="name"):
			frappe.delete_doc("BPMN Process Model", name, force=True, ignore_permissions=True)

	# ------------------------------------------------------------------
	def test_the_separate_assignment_log_no_longer_exists(self):
		"""The doctype is deleted, and so is its table — deleting the DocType
		record alone leaves every row behind, because Frappe's delete_doc does
		not drop tab<DocType>."""
		self.assertFalse(frappe.db.exists("DocType", "User Task Assignment Log"))
		self.assertFalse(frappe.db.table_exists("User Task Assignment Log"))

	def test_reassigning_records_the_change_in_the_version_history(self):
		"""The whole justification for removing the log: the map's own version
		history already holds the before and after."""
		before = frappe.db.count("Version", {"ref_doctype": "BPMN Process Model", "docname": self.model})

		with self._versioning_on():
			R.reassign_user_task(self.model, "zz_task", {"assigneeMode": "User", "assigneeUser": "Administrator"})

		versions = frappe.get_all(
			"Version",
			filters={"ref_doctype": "BPMN Process Model", "docname": self.model},
			fields=["data"],
			order_by="creation desc",
			limit=1,
		)
		self.assertEqual(
			frappe.db.count("Version", {"ref_doctype": "BPMN Process Model", "docname": self.model}),
			before + 1,
			"the save must record a Version",
		)

		changed = json.loads(versions[0].data or "{}").get("changed", [])
		xml_change = [c for c in changed if c[0] == "bpmn_xml"]
		self.assertTrue(xml_change, "the Version must carry the bpmn_xml diff")

		_, old_xml, new_xml = xml_change[0]
		self.assertIn("Administrator", new_xml or "")
		self.assertNotIn("Administrator", old_xml or "")

	def test_the_endpoint_does_not_report_a_log_it_no_longer_writes(self):
		out = R.reassign_user_task(self.model, "zz_task", {"assigneeMode": "Round Robin"})

		self.assertTrue(out["updated"])
		self.assertNotIn("log", out, "a log name would imply a record that is not written")

	def test_the_attribute_really_changed_on_the_map(self):
		"""Guards the test above from passing on a no-op: `updated` and a Version
		row only mean something if the XML actually carries the new assignment."""
		R.reassign_user_task(self.model, "zz_task", {"assigneeMode": "User", "assigneeUser": "Administrator"})

		xml = frappe.db.get_value("BPMN Process Model", self.model, "bpmn_xml")
		task = etree.fromstring(xml.encode("utf-8")).xpath("//*[local-name()='userTask']")[0]
		ns = R.SPIFF_NS
		self.assertEqual(task.get(f"{{{ns}}}assigneeMode"), "User")
		self.assertEqual(task.get(f"{{{ns}}}assigneeUser"), "Administrator")

	def test_an_unchanged_reassignment_writes_no_version(self):
		"""Reassign mode autosaves on a timer, so the same values can arrive
		twice. A second Version for a change nobody made is noise in the very
		history this story makes the single source of truth."""
		with self._versioning_on():
			R.reassign_user_task(self.model, "zz_task", {"assigneeMode": "User", "assigneeUser": "Administrator"})
			after_first = frappe.db.count("Version", {"ref_doctype": "BPMN Process Model", "docname": self.model})

			out = R.reassign_user_task(self.model, "zz_task", {"assigneeMode": "User", "assigneeUser": "Administrator"})

		self.assertFalse(out["updated"])
		self.assertEqual(
			frappe.db.count("Version", {"ref_doctype": "BPMN Process Model", "docname": self.model}),
			after_first,
		)
