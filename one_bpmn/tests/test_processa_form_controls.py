"""Tests for the Processa-controlled DocType list (WI-001813).

bpmn_form_actions.js uses this list to suppress the native Frappe controls
Processa owns — the Submit button, the "Submit this document to confirm"
banner, and the no-op Save button on an unchanged document.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_processa_form_controls
"""

from __future__ import annotations

from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.instance_api import (
	PROCESSA_DOCTYPES_CACHE_KEY,
	clear_processa_doctype_cache,
	get_processa_controlled_doctypes,
)

class TestProcessaControlledDoctypes(FrappeTestCase):
	"""Each test uses its own real-but-unrelated probe DocType and deletes the
	model it created: FrappeTestCase rolls back per class, not per test, so
	models would otherwise leak into the tests that follow."""

	def setUp(self):
		clear_processa_doctype_cache()
		self.addCleanup(clear_processa_doctype_cache)

	def _assert_unrelated(self, doctype):
		"""Baseline guard — the probe must not already be Processa-controlled."""
		self.assertNotIn(
			doctype,
			get_processa_controlled_doctypes(),
			msg=f"{doctype} is already Processa-controlled; pick another probe",
		)
		clear_processa_doctype_cache()

	def _delete_model(self, name):
		if frappe.db.exists("BPMN Process Model", name):
			frappe.delete_doc("BPMN Process Model", name, force=True, ignore_permissions=True)

	def _make_model(self, is_active, start_doctype=None, target_doctype=None):
		"""A minimal BPMN Process Model.

		No ``process_name`` on purpose: that short-circuits both
		attach_process_implementation() and enforce_single_active(), so the
		model cannot disturb any real process.
		"""
		doc = frappe.get_doc(
			{
				"doctype": "BPMN Process Model",
				"title": f"WI-001813 Probe {frappe.generate_hash(length=6)}",
				"process_id": f"wi1813_{frappe.generate_hash(length=8)}",
				"version": 1,
				"is_active": 1 if is_active else 0,
			}
		)
		if start_doctype:
			doc.append(
				"start_events",
				{
					"event_type": "None",
					"trigger_type": "DocType Event",
					"trigger_doctype": start_doctype,
					"trigger_event": "After Insert",
				},
			)
		if target_doctype:
			doc.append("target_doctypes", {"doctype_name": target_doctype})

		doc.flags.skip_editability_check = True
		doc.insert(ignore_permissions=True)
		self.addCleanup(self._delete_model, doc.name)
		return doc

	def test_doctype_event_start_trigger_is_controlled(self):
		probe = "Note"
		self._assert_unrelated(probe)
		self._make_model(is_active=True, start_doctype=probe)
		clear_processa_doctype_cache()
		self.assertIn(probe, get_processa_controlled_doctypes())

	def test_target_doctype_is_controlled(self):
		probe = "Blog Category"
		self._assert_unrelated(probe)
		self._make_model(is_active=True, target_doctype=probe)
		clear_processa_doctype_cache()
		self.assertIn(probe, get_processa_controlled_doctypes())

	def test_inactive_model_is_ignored(self):
		probe = "Web Page"
		self._assert_unrelated(probe)
		self._make_model(is_active=False, start_doctype=probe)
		clear_processa_doctype_cache()
		self.assertNotIn(probe, get_processa_controlled_doctypes())

	def test_result_is_cached_and_invalidated_on_model_save(self):
		probe = "Email Group"
		self._assert_unrelated(probe)
		model = self._make_model(is_active=True, start_doctype=probe)
		clear_processa_doctype_cache()

		self.assertIn(probe, get_processa_controlled_doctypes())
		self.assertIsNotNone(frappe.cache().get_value(PROCESSA_DOCTYPES_CACHE_KEY))

		# Deactivating the model must drop the cache via the doc_events hook,
		# otherwise the desk would keep hiding buttons for a dead process.
		model.is_active = 0
		model.flags.skip_editability_check = True
		model.save(ignore_permissions=True)

		self.assertIsNone(frappe.cache().get_value(PROCESSA_DOCTYPES_CACHE_KEY))
		self.assertNotIn(probe, get_processa_controlled_doctypes())

	def test_cache_invalidation_hook_is_registered(self):
		hooks = frappe.get_hooks("doc_events") or {}
		model_hooks = hooks.get("BPMN Process Model", {})
		for event in ("on_update", "after_delete"):
			self.assertIn(
				"one_bpmn.api.instance_api.clear_processa_doctype_cache",
				model_hooks.get(event, []),
				msg=f"clear_processa_doctype_cache not wired to {event}",
			)

	def test_no_duplicates_and_sorted(self):
		probe = "Blog Post"
		self._assert_unrelated(probe)
		# Same doctype as both start trigger and target — must appear once.
		self._make_model(is_active=True, start_doctype=probe, target_doctype=probe)
		clear_processa_doctype_cache()
		controlled = get_processa_controlled_doctypes()
		self.assertEqual(controlled.count(probe), 1)
		self.assertEqual(controlled, sorted(controlled))


class TestFormActionsClientContract(FrappeTestCase):
	"""The suppression happens in JS; assert the contract stays in place."""

	@property
	def source(self) -> str:
		path = (
			Path(frappe.get_app_path("one_bpmn"))
			/ "public"
			/ "js"
			/ "bpmn_form_actions.js"
		)
		return path.read_text()

	def test_fetches_the_controlled_doctype_list(self):
		self.assertIn(
			"one_bpmn.api.instance_api.get_processa_controlled_doctypes", self.source
		)

	def test_overrides_can_submit_and_can_save(self):
		self.assertIn("ToolbarProto.can_submit = function", self.source)
		self.assertIn("ToolbarProto.can_save = function", self.source)

	def test_suppresses_submit_message_at_source(self):
		self.assertIn("FormProto.show_submit_message = function", self.source)

	def test_save_is_kept_for_new_and_dirty_documents(self):
		# The guards that keep documents creatable and editable.
		self.assertIn("!this.frm.is_new()", self.source)
		self.assertIn("!this.frm.is_dirty()", self.source)

	def test_banner_removal_targets_the_layout_message_container(self):
		# frappe renders the banner into layout.message, NOT dashboard.wrapper.
		self.assertIn("frm.layout.message", self.source)

	def test_asset_cache_buster_bumped(self):
		# Pinned to the exact value on purpose: the point of the test is that
		# editing bpmn_form_actions.js without bumping the query string fails
		# here, so the pin has to be updated deliberately alongside the file.
		#
		# v=4 rather than the v=3 this feature first shipped as. The revert
		# (416bc6a) dropped the query string entirely, so version-15 has been
		# serving the bare URL — and /assets carries a 12h Cache-Control, so
		# desks hold a cached copy under that URL. Going back to v=3 would be a
		# value some browsers have already seen; v=4 has never been served.
		hooks_py = (Path(frappe.get_app_path("one_bpmn")) / "hooks.py").read_text()
		self.assertIn("bpmn_form_actions.js?v=4", hooks_py)
