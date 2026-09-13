"""A DocType we own must be edited in its own source, not overridden.

"Review Doctypes → Sync" emitted a Property Setter for every difference,
whoever owned the DocType. For erpnext's Employee that is the only mechanism
there is. For a DocType one of our own apps owns it leaves the source file no
longer true: the JSON says one thing, the setter says another, the effective
schema is knowable only on a migrated site — and the generated patch re-applies
the override on every migrate, so deleting the row does not stick.

These tests pin the routing, the edit itself (in place, order preserved), the
idempotency that keeps a no-op sync out of the diff, and the split when one
model references both kinds of DocType.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_doctype_source_sync
"""

from __future__ import annotations

import json
import os

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import doctype_source_sync as source
from one_bpmn.api.production_review import _customization_pr_files, _pr_body

SETTINGS = "Processa Settings"
OURS = "Agent Delegation"          # one_bpmn's own
THEIRS = "Employee"                # erpnext's


def _set_app(value):
    frappe.db.set_single_value(SETTINGS, "customization_app", value)
    frappe.clear_cache(doctype=SETTINGS)


def _source_text(dt):
    path = source.source_json_path(dt)
    app = path.split("/")[0]
    full = os.path.join(os.path.dirname(frappe.get_app_path(app)), path)
    return open(full).read() if os.path.exists(full) else None


class TestOwnershipDecidesTheDestination(FrappeTestCase):
    """AC1, AC2. Ownership of the DocType, not the presence of a customization."""

    def setUp(self):
        self.previous = frappe.db.get_single_value(SETTINGS, "customization_app")
        _set_app("one_fm")

    def tearDown(self):
        _set_app(self.previous)

    def test_a_doctype_one_of_our_apps_owns_is_ours(self):
        for dt in (OURS, "Attendance Check", "Work Item"):
            if not frappe.db.exists("DocType", dt):
                continue
            self.assertTrue(source.owned_in_source(dt), f"{dt} is ours")

    def test_a_third_party_doctype_is_not(self):
        for dt in (THEIRS, "User", "HD Ticket", "Interview"):
            if not frappe.db.exists("DocType", dt):
                continue
            self.assertFalse(source.owned_in_source(dt), f"{dt} belongs to an app we do not control")

    def test_a_doctype_created_through_the_ui_has_no_source_to_edit(self):
        """custom=1 lives in the database; there is no JSON to write into.

        The flag is flipped on a real DocType rather than creating one: making a
        DocType is DDL, which commits, so a fixture could not be rolled back.
        """
        if not frappe.db.exists("DocType", OURS):
            self.skipTest(f"{OURS} is not installed")
        frappe.db.set_value("DocType", OURS, "custom", 1, update_modified=False)
        self.addCleanup(frappe.db.set_value, "DocType", OURS, "custom", 0, update_modified=False)
        self.assertFalse(source.owned_in_source(OURS))

    def test_the_path_is_where_frappe_lays_the_doctype_out(self):
        if not frappe.db.exists("DocType", OURS):
            self.skipTest(f"{OURS} is not installed")
        self.assertEqual(
            source.source_json_path(OURS),
            "one_bpmn/one_bpmn/doctype/agent_delegation/agent_delegation.json",
        )
        self.assertIsNotNone(_source_text(OURS), "the file the sync would edit must exist")

    def test_nothing_is_ours_when_no_customization_app_is_configured(self):
        """The old behaviour for a site that has not filled the field in."""
        _set_app("")
        self.assertFalse(source.owned_in_source(OURS))


class TestEditingOurOwnJson(FrappeTestCase):
    """AC3, AC4, AC5, AC6. A Custom Field insert commits, so fixtures are
    removed by name rather than left to a rollback."""

    def setUp(self):
        if not frappe.db.exists("DocType", OURS):
            self.skipTest(f"{OURS} is not installed")
        self.previous = frappe.db.get_single_value(SETTINGS, "customization_app")
        _set_app("one_fm")
        on_disk = _source_text(OURS)
        if not on_disk:
            self.skipTest("the source file is not on disk")
        # The baseline is the file with whatever this site ALREADY says folded
        # in, so each test measures the change its own fixture makes rather than
        # the site's total state — drift left by anything else cannot make a
        # one-property edit look like eight.
        self.before = source.merge_into_source(on_disk, OURS)[0] or on_disk
        self.parsed = json.loads(self.before)

    def tearDown(self):
        _set_app(self.previous)

    def _remove_after(self, doctype, name):
        """Delete AND commit.

        A Custom Field insert commits (it changes the schema), so the row
        survives the test's rollback while a plain ``delete_doc`` in cleanup does
        not — the fixture would be left on the site for the next run to trip on.
        """
        def cleanup():
            if frappe.db.exists(doctype, name):
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                frappe.db.commit()

        self.addCleanup(cleanup)

    def _setter(self, **fields):
        doc = frappe.get_doc({"doctype": "Property Setter", "doc_type": OURS, **fields}).insert(
            ignore_permissions=True
        )
        self._remove_after("Property Setter", doc.name)
        return doc

    def _custom_field(self, **fields):
        doc = frappe.get_doc({"doctype": "Custom Field", "dt": OURS, **fields}).insert(
            ignore_permissions=True
        )
        self._remove_after("Custom Field", doc.name)
        return doc

    def test_nothing_changed_writes_nothing(self):
        """AC6 + AC9: a sync with no real change must not show a diff."""
        text, notes = source.merge_into_source(self.before, OURS)
        self.assertIsNone(text)
        self.assertEqual(notes, [])

    def test_a_field_property_lands_in_that_field(self):
        field = self.parsed["fields"][1]["fieldname"]
        self._setter(doctype_or_field="DocField", field_name=field, property="label",
                     property_type="Data", value="Renamed By Review")

        text, notes = source.merge_into_source(self.before, OURS)
        after = json.loads(text)

        self.assertEqual(notes, [f"{field}: label"])
        row = next(r for r in after["fields"] if r.get("fieldname") == field)
        self.assertEqual(row["label"], "Renamed By Review")

    def test_field_order_and_every_untouched_property_survive(self):
        """AC3: an edit is an edit, not a regeneration."""
        field = self.parsed["fields"][1]["fieldname"]
        original = next(r for r in self.parsed["fields"] if r.get("fieldname") == field)
        self._setter(doctype_or_field="DocField", field_name=field, property="label",
                     property_type="Data", value="Renamed By Review")

        after = json.loads(source.merge_into_source(self.before, OURS)[0])

        self.assertEqual(
            [r.get("fieldname") for r in after["fields"]],
            [r.get("fieldname") for r in self.parsed["fields"]],
            "field order must be preserved",
        )
        changed = [a.get("fieldname") for a, b in zip(self.parsed["fields"], after["fields"]) if a != b]
        self.assertEqual(changed, [field], "only the edited field may differ")
        row = next(r for r in after["fields"] if r.get("fieldname") == field)
        for key, value in original.items():
            if key != "label":
                self.assertEqual(row[key], value, f"{key} must be left alone")

    def test_a_cleared_property_is_removed_rather_than_written_as_a_default(self):
        """What Frappe's exporter does: a default is absent, not spelled out."""
        field = next((r["fieldname"] for r in self.parsed["fields"] if r.get("read_only")), None)
        if not field:
            self.skipTest("no read-only field in this DocType to clear")
        self._setter(doctype_or_field="DocField", field_name=field, property="read_only",
                     property_type="Check", value="0")

        after = json.loads(source.merge_into_source(self.before, OURS)[0])
        row = next(r for r in after["fields"] if r.get("fieldname") == field)
        self.assertNotIn("read_only", row)

    def test_a_new_field_is_added_at_its_position(self):
        """AC4."""
        anchor = self.parsed["fields"][1]["fieldname"]
        self._custom_field(fieldname="processa_probe_note", label="Probe Note",
                           fieldtype="Small Text", insert_after=anchor)

        after = json.loads(source.merge_into_source(self.before, OURS)[0])
        names = [r.get("fieldname") for r in after["fields"]]

        self.assertIn("processa_probe_note", names)
        self.assertEqual(names[names.index(anchor) + 1], "processa_probe_note")

        added = next(r for r in after["fields"] if r["fieldname"] == "processa_probe_note")
        self.assertEqual(
            list(added), sorted(added),
            "a new entry has no order to preserve, so it goes in Frappe's key order",
        )

    def test_a_doctype_level_property_goes_to_the_top_level_typed(self):
        """AC5. A Property Setter stores its value as text; the JSON wants an int."""
        self._setter(doctype_or_field="DocType", property="max_attachments",
                     property_type="Int", value="3")

        text, notes = source.merge_into_source(self.before, OURS)

        self.assertEqual(json.loads(text)["max_attachments"], 3)
        self.assertIn("DocType properties: max_attachments", notes)

    def test_field_order_is_written_as_a_list_not_as_a_sentence(self):
        """Frappe keeps field_order as a JSON array inside a text property.

        Seen on staging: Work Item and Visa Request both carry a field_order
        setter. Writing it back as a string would leave a DocType whose field
        order is one long line of text.
        """
        order = [r["fieldname"] for r in self.parsed["fields"] if r.get("fieldname")][:5]
        self._setter(doctype_or_field="DocType", property="field_order",
                     property_type="Small Text", value=json.dumps(order))

        text, notes = source.merge_into_source(self.before, OURS)

        written = json.loads(text)["field_order"]
        self.assertIsInstance(written, list)
        self.assertEqual(written, order)
        self.assertIn("DocType properties: field_order", notes)

    def test_the_written_file_is_valid_and_the_second_pass_is_a_no_op(self):
        """AC6: idempotent, and the formatting matches Frappe's own writer."""
        field = self.parsed["fields"][1]["fieldname"]
        self._setter(doctype_or_field="DocField", field_name=field, property="label",
                     property_type="Data", value="Renamed By Review")

        text, _notes = source.merge_into_source(self.before, OURS)
        json.loads(text)  # parses

        again, notes = source.merge_into_source(text, OURS)
        self.assertIsNone(again, "re-running with no further change must write nothing")
        self.assertEqual(notes, [])
        self.assertEqual(text.endswith("\n"), self.before.endswith("\n"))
        self.assertIn('\n "', text, "top-level keys are indented by one space, as Frappe writes them")

    def test_the_diff_is_the_change_and_nothing_else(self):
        import difflib

        field = self.parsed["fields"][1]["fieldname"]
        self._setter(doctype_or_field="DocField", field_name=field, property="label",
                     property_type="Data", value="Renamed By Review")

        text = source.merge_into_source(self.before, OURS)[0]
        added = [l for l in difflib.unified_diff(self.before.splitlines(), text.splitlines(), lineterm="")
                 if l.startswith("+") and not l.startswith("+++")]
        self.assertLessEqual(len(added), 2, f"a one-property edit should be a one-line diff: {added}")

    def test_a_file_that_is_not_json_is_refused_rather_than_overwritten(self):
        with self.assertRaises(ValueError):
            source.merge_into_source("{ not json", OURS)

    def test_merge_points_at_the_create_path_when_the_file_is_absent(self):
        """Editing nothing is not a merge — the caller creates it instead."""
        with self.assertRaisesRegex(ValueError, "create_source_files"):
            source.merge_into_source("", OURS)


class TestCreatingSourceForADoctypeTheRepoLacks(FrappeTestCase):
    """A DocType authored on the BA site has never been in source.

    Seen live: "Sync" raised "not in the repository, so there is nothing to
    edit" for a DocType created through Customize Form on BA. There is nothing
    to edit because it has to be written.
    """

    def setUp(self):
        if not frappe.db.exists("DocType", OURS):
            self.skipTest(f"{OURS} is not installed")
        self.previous = frappe.db.get_single_value(SETTINGS, "customization_app")
        _set_app("one_fm")

    def tearDown(self):
        _set_app(self.previous)

    def test_it_writes_the_three_files_a_standard_doctype_loads_through(self):
        files, notes = source.create_source_files(OURS)
        folder = source.source_json_path(OURS).rsplit("/", 1)[0]

        self.assertEqual(
            set(files),
            {f"{folder}/__init__.py",
             source.source_json_path(OURS),
             f"{folder}/{frappe.scrub(OURS)}.py"},
        )
        self.assertIn("created in source", notes)

    def test_the_json_is_what_frappe_would_have_exported(self):
        files, _notes = source.create_source_files(OURS)
        text = files[source.source_json_path(OURS)]
        doc = json.loads(text)

        self.assertEqual(doc["name"], OURS)
        self.assertEqual(doc["module"], frappe.db.get_value("DocType", OURS, "module"))
        self.assertEqual(list(doc), sorted(doc), "Frappe's exporter sorts keys")
        self.assertFalse(text.endswith("\n"), "Frappe's exporter writes no trailing newline")
        self.assertTrue(doc["fields"], "the fields have to be in there")

    def test_the_controller_is_importable_python_with_the_right_class(self):
        import ast

        files, _notes = source.create_source_files(OURS)
        folder = source.source_json_path(OURS).rsplit("/", 1)[0]
        controller = files[f"{folder}/{frappe.scrub(OURS)}.py"]

        tree = ast.parse(controller)
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        self.assertEqual(classes, [OURS.replace(" ", "")])
        self.assertIn("from frappe.model.document import Document", controller)

    def test_a_customization_is_folded_into_the_file_it_creates(self):
        """The point of the sync: the created file carries the BA state."""
        setter = frappe.get_doc({
            "doctype": "Property Setter", "doc_type": OURS, "doctype_or_field": "DocType",
            "property": "max_attachments", "property_type": "Int", "value": "4",
        }).insert(ignore_permissions=True)
        self.addCleanup(lambda: (
            frappe.db.exists("Property Setter", setter.name)
            and frappe.delete_doc("Property Setter", setter.name, force=True, ignore_permissions=True)
            and frappe.db.commit()
        ))

        files, notes = source.create_source_files(OURS)
        doc = json.loads(files[source.source_json_path(OURS)])

        self.assertEqual(doc["max_attachments"], 4)
        self.assertIn("DocType properties: max_attachments", notes)

    def test_a_doctype_with_no_owning_app_has_nowhere_to_go(self):
        with self.assertRaises(ValueError):
            source.create_source_files("Not A Real Doctype At All")

    def test_the_created_set_carries_no_override_artefacts(self):
        files, _notes = source.create_source_files(OURS)
        for path in files:
            self.assertNotIn("property_setter", path)
            self.assertNotIn("custom_field", path)
            self.assertNotIn("patches", path)


class TestTheArtefactSetFollowsOwnership(FrappeTestCase):
    """AC1, AC7, AC8."""

    def setUp(self):
        if not frappe.db.exists("DocType", OURS):
            self.skipTest(f"{OURS} is not installed")
        self.previous = frappe.db.get_single_value(SETTINGS, "customization_app")
        _set_app("one_fm")

    def tearDown(self):
        _set_app(self.previous)

    def test_our_own_doctype_gets_its_json_and_no_override(self):
        files, _build, artefacts, routing = _customization_pr_files(
            "one_bpmn", [OURS], "Some Map", "abc123"
        )
        self.assertEqual(routing["owned"], [OURS])
        self.assertEqual(routing["foreign"], [])
        self.assertEqual(artefacts, [source.source_json_path(OURS)])
        for path in artefacts + list(files):
            self.assertNotIn("property_setter", path)
            self.assertNotIn("custom_field", path)
            self.assertNotIn("patches", path)

    def test_a_third_party_doctype_still_gets_the_customization_artefacts(self):
        """AC2: unchanged for anything we do not own."""
        if not frappe.db.exists("DocType", THEIRS):
            self.skipTest(f"{THEIRS} is not installed")
        files, _build, artefacts, routing = _customization_pr_files(
            "one_fm", [THEIRS], "Some Map", "abc123"
        )
        self.assertEqual(routing["owned"], [])
        self.assertIn("one_fm/custom/property_setter/employee.py", files)
        self.assertIn("one_fm/custom/custom_field/employee.py", files)
        self.assertTrue(any("patches/v15_0" in p for p in artefacts))
        self.assertIn("one_fm/setup/property_setter.py", artefacts)

    def test_a_mixed_selection_splits_by_owner(self):
        """AC7. One sync, both routes, each in the right place."""
        if not frappe.db.exists("DocType", "Attendance Check"):
            self.skipTest("Attendance Check is not installed")
        _files, _build, artefacts, routing = _customization_pr_files(
            "one_fm", [THEIRS, "Attendance Check"], "Some Map", "abc123"
        )
        self.assertEqual(routing["owned"], ["Attendance Check"])
        self.assertEqual(routing["foreign"], [THEIRS])
        self.assertIn("one_fm/one_fm/doctype/attendance_check/attendance_check.json", artefacts)
        self.assertIn("one_fm/custom/property_setter/employee.py", artefacts)
        self.assertNotIn("one_fm/custom/property_setter/attendance_check.py", artefacts)

    def test_the_body_says_which_route_each_doctype_took_and_why(self):
        """AC8. A reviewer can see at a glance that we did not override our own."""
        _files, _build, artefacts, routing = _customization_pr_files(
            "one_bpmn", [OURS], "Some Map", "abc123"
        )
        body = _pr_body("one_bpmn", [OURS], "Some Map", artefacts, routing,
                        {OURS: ["Update DocField instruction (reqd)"]})

        self.assertIn("| DocType | Written to | Why | What changed |", body)
        self.assertNotIn("\n|  |", body, "no empty rows")
        self.assertIn("its own DocType JSON", body)
        self.assertIn("no Property Setter", body)
        self.assertIn("Update DocField instruction (reqd)", body)

    def test_a_long_change_list_is_summarised_rather_than_dumped(self):
        """Seen on a real run: 15 reported changes made one unreadable cell."""
        _files, _build, artefacts, routing = _customization_pr_files(
            "one_bpmn", [OURS], "Some Map", "abc123"
        )
        many = [f"Create DocField {OURS}-field_{i}" for i in range(15)]
        body = _pr_body("one_bpmn", [OURS], "Some Map", artefacts, routing, {OURS: many})

        self.assertIn("and 10 more", body)
        self.assertIn("field_4", body)
        self.assertNotIn("field_9", body)

    def test_the_body_still_explains_the_override_route(self):
        if not frappe.db.exists("DocType", THEIRS):
            self.skipTest(f"{THEIRS} is not installed")
        _files, _build, artefacts, routing = _customization_pr_files(
            "one_fm", [THEIRS], "Some Map", "abc123"
        )
        body = _pr_body("one_fm", [THEIRS], "Some Map", artefacts, routing, {})
        self.assertIn("customization artefacts", body)
        self.assertIn("override is the only mechanism", body)
