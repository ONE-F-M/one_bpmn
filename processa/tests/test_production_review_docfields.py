# Copyright (c) 2026, one-fm and contributors
# Review Doctypes must see a standard DocType edited directly.
#
# The reported symptom: a Link filter was added to Process Creation Request's
# parent_process field on the BA site, and Review Doctypes answered "No changes
# seen in the relevant doctype(s)". Frappe writes that filter straight onto the
# DocField row of a standard DocType and mints no Property Setter, while the
# snapshot only carried Custom Fields and Property Setters — so a real, wanted
# change was invisible and the tool reported agreement it had not verified.
#
# These tests are on the pure snapshot/diff functions: that is where the hole
# was, and they run without touching Production.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.api.production_review import (
	_build_doctype_snapshot,
	_clean_docfield,
	_diff_doctypes,
)

LINK_FILTERS = '[["Process","is_group","=",1]]'


def _snap(link_filters=None, extra_fields=None):
	"""A minimal one-DocType snapshot shaped like _build_doctype_snapshot's output."""
	fields = {"parent_process": {"fieldname": "parent_process", "fieldtype": "Link",
	                             "options": "Process", "link_filters": link_filters}}
	fields.update(extra_fields or {})
	return {"Demo DT": {"exists": True, "custom": 0, "custom_fields": {},
	                    "property_setters": {}, "docfields": fields}}


class TestDocFieldDriftIsVisible(FrappeTestCase):
	def test_a_link_filter_added_on_ba_is_reported(self):
		"""The exact reported case: filter on BA, absent on Production."""
		changes = _diff_doctypes(_snap(LINK_FILTERS), _snap(None))

		self.assertEqual(len(changes), 1, msg=f"expected one change, got {changes}")
		c = changes[0]
		self.assertEqual(c["object_type"], "DocField")
		self.assertEqual(c["action"], "Update")
		self.assertEqual(c["doctype"], "Demo DT")
		self.assertIn("link_filters", c["detail"])

	def test_identical_docfields_are_not_a_change(self):
		self.assertEqual(_diff_doctypes(_snap(LINK_FILTERS), _snap(LINK_FILTERS)), [])

	def test_a_field_absent_on_production_is_reported(self):
		local = _snap(None, extra_fields={"new_field": {"fieldname": "new_field", "fieldtype": "Data"}})
		changes = [c for c in _diff_doctypes(local, _snap(None)) if c["object_type"] == "DocField"]

		self.assertEqual(len(changes), 1)
		self.assertEqual(changes[0]["action"], "Create")
		self.assertTrue(changes[0]["name"].endswith("new_field"))


class TestOlderProductionIsNotMisreported(FrappeTestCase):
	def test_a_production_without_the_key_reports_no_docfield_drift(self):
		"""Absent must not read as empty.

		A Production still running the previous version returns no ``docfields``
		key at all. Treating that as "no fields there" would announce every field
		of every DocType as missing — noise that would bury real changes.
		"""
		remote = _snap(None)
		del remote["Demo DT"]["docfields"]

		changes = [c for c in _diff_doctypes(_snap(LINK_FILTERS), remote) if c["object_type"] == "DocField"]

		self.assertEqual(changes, [])


class TestSnapshotShape(FrappeTestCase):
	def test_docfields_are_keyed_by_fieldname_and_drop_the_row_name(self):
		"""A DocField's name is a per-site hash, so it can neither key nor be compared."""
		snap = _build_doctype_snapshot(["DocType"])["DocType"]

		self.assertIn("docfields", snap)
		self.assertTrue(snap["docfields"], msg="DocType should report its own fields")
		self.assertIn("module", snap["docfields"], msg="keys must be fieldnames")
		for fieldname, rec in snap["docfields"].items():
			self.assertNotIn("name", rec, msg=f"{fieldname} kept the volatile row name")
			self.assertNotIn("modified", rec)
			self.assertEqual(rec.get("fieldname"), fieldname)

	def test_clean_docfield_keeps_the_properties_that_matter(self):
		row = {"name": "122sed55hv", "modified": "2026-08-10", "parent": "Demo DT",
		       "fieldname": "parent_process", "link_filters": LINK_FILTERS, "reqd": 1}
		cleaned = _clean_docfield(row)

		self.assertEqual(cleaned, {"fieldname": "parent_process", "link_filters": LINK_FILTERS, "reqd": 1})

	def test_a_missing_doctype_reports_no_fields(self):
		snap = _build_doctype_snapshot([f"ZZ Nonexistent {frappe.generate_hash(length=6)}"])
		only = next(iter(snap.values()))

		self.assertFalse(only["exists"])
		self.assertEqual(only["docfields"], {})


def _ordered_snap(names):
	"""A snapshot whose docfields keep the given order, as the idx-ordered query yields them."""
	fields = {n: {"fieldname": n, "fieldtype": "Data"} for n in names}
	return {"Demo DT": {"exists": True, "custom": 0, "custom_fields": {},
	                    "property_setters": {}, "docfields": fields}}


class TestFieldMovesAreVisible(FrappeTestCase):
	"""idx is not part of a cleaned DocField, so a move needs its own comparison."""

	OWNED = "processa/processa_engine/doctype/demo_dt/demo_dt.json"

	def _diff(self, local, remote, destination):
		from unittest import mock

		with mock.patch("processa.api.production_review._sync_destination", return_value=destination):
			return _diff_doctypes(local, remote)

	def test_the_same_fields_in_a_new_order_are_one_update_on_an_owned_doctype(self):
		changes = self._diff(_ordered_snap(["a", "c", "b"]), _ordered_snap(["a", "b", "c"]), self.OWNED)

		self.assertEqual(changes, [{
			"object_type": "Field", "name": "Demo DT → field order", "doctype": "Demo DT",
			"action": "Update", "detail": "Field order", "destination": self.OWNED,
		}])

	def test_the_same_order_is_not_a_change(self):
		self.assertEqual(self._diff(_ordered_snap(["a", "b", "c"]), _ordered_snap(["a", "b", "c"]), self.OWNED), [])

	def test_a_doctype_we_do_not_own_reports_no_move(self):
		changes = self._diff(_ordered_snap(["a", "c", "b"]), _ordered_snap(["a", "b", "c"]), "")

		self.assertEqual(changes, [])

	def test_a_field_only_one_side_has_is_not_a_move(self):
		"""Only the fieldnames on both sides are compared; a new field is reported as Create."""
		changes = self._diff(_ordered_snap(["a", "new", "b"]), _ordered_snap(["a", "b"]), self.OWNED)

		self.assertEqual([c["action"] for c in changes], ["Create"])


class TestAFieldDeletedOnBaIsReported(FrappeTestCase):
	"""AC1, AC3. On Production, missing on BA: a deletion only when a Version says so."""

	OWNED = "processa/processa_engine/doctype/demo_dt/demo_dt.json"

	def _diff(self, local, remote, destination):
		from unittest import mock

		with mock.patch("processa.api.production_review._sync_destination", return_value=destination):
			return _diff_doctypes(local, remote)

	def _local(self, deleted):
		local = _ordered_snap(["a"])
		if deleted is not None:
			local["Demo DT"]["deleted_fields"] = deleted
		return local

	def test_a_listed_deleted_field_is_one_delete_change(self):
		changes = self._diff(self._local(["b"]), _ordered_snap(["a", "b"]), self.OWNED)

		self.assertEqual(changes, [{
			"object_type": "Field", "name": "Demo DT \u2192 b", "doctype": "Demo DT",
			"action": "Delete", "detail": "Deleted on BA", "destination": self.OWNED,
		}])

	def test_a_field_missing_on_ba_without_deleted_fields_is_not_a_change(self):
		self.assertEqual(self._diff(self._local(None), _ordered_snap(["a", "b"]), self.OWNED), [])
		self.assertEqual(self._diff(self._local([]), _ordered_snap(["a", "b"]), self.OWNED), [])

	def test_a_doctype_we_do_not_own_reports_no_deletion(self):
		self.assertEqual(self._diff(self._local(["b"]), _ordered_snap(["a", "b"]), ""), [])

	def test_a_deleted_field_production_no_longer_has_is_not_a_change(self):
		self.assertEqual(self._diff(self._local(["b"]), _ordered_snap(["a"]), self.OWNED), [])
