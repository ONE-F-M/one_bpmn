"""A Processa customization PR must be written the way one_fm writes them.

"Review Doctypes → Sync" used to commit one file: the Frappe-native
``custom/<dt>.json``. one_fm does not carry customizations that way. It carries
them as a data module under ``custom/custom_field/`` and ``custom/property_setter/``,
registered in ``setup/`` for fresh installs, and applied by a patch for existing
sites — four artefacts, and a PR with only one of them is half a change.

These tests pin the generated output against the app's ACTUAL source: the
aggregators are spliced by reading the real files off disk, and what the codegen
emits is exec'd and compared to what the hand-written modules return. A rename or
a reshape of one_fm's convention therefore fails here rather than producing a PR
that no longer fits the app it targets.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_onefm_customization_codegen
"""

from __future__ import annotations

import json
import os

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import onefm_customization_codegen as gen

APP = "one_fm"


def _source(rel_path: str) -> str:
    """Read a file from the app source by its repo-relative path."""
    repo_root = os.path.dirname(frappe.get_app_path(APP))
    return open(os.path.join(repo_root, rel_path)).read()


class TestCustomFieldModule(FrappeTestCase):
    RECORDS = [
        {
            "name": "abc123",  # per-site row name — must not reach the output
            "fieldname": "custom_is_weekend_reliever",
            "fieldtype": "Check",
            "label": "Is Weekend Reliever",
            "insert_after": "custom_is_reliever",
            "depends_on": "eval:!doc.attendance_by_timesheet",
            "description": "If checked, the Employee can be selected as weekend reliever.",
            "reqd": 0,
            "hidden": 0,
            "creation": "2026-01-01 00:00:00",
            "modified": "2026-01-02 00:00:00",
            "owner": "Administrator",
            "idx": 3,
        }
    ]

    def _emitted(self, dt="Employee", records=None):
        src = gen.render_custom_field_module(dt, records if records is not None else self.RECORDS)
        scope = {}
        exec(compile(src, "<generated>", "exec"), scope)
        return src, scope[gen.getter_name(dt, "custom_field")]()

    def test_generated_module_is_importable_and_returns_the_expected_shape(self):
        src, result = self._emitted()
        self.assertIn("def get_employee_custom_fields():", src)
        self.assertEqual(list(result), ["Employee"])
        self.assertEqual(result["Employee"][0]["fieldname"], "custom_is_weekend_reliever")

    def test_volatile_and_default_keys_are_pruned(self):
        """A dump of fields="*" would be ~45 keys of mostly framework defaults —
        unreadable next to the hand-written modules and a diff that churns."""
        _, result = self._emitted()
        emitted = result["Employee"][0]
        for junk in ("name", "creation", "modified", "owner", "idx"):
            self.assertNotIn(junk, emitted, f"{junk} must not reach the generated module")
        for falsy in ("reqd", "hidden"):
            self.assertNotIn(falsy, emitted, f"default-valued {falsy} should be omitted")
        self.assertIn("depends_on", emitted)
        self.assertIn("label", emitted)

    def test_identifying_keys_survive_even_when_falsy(self):
        _, result = self._emitted(records=[{"fieldname": "x", "fieldtype": ""}])
        self.assertEqual(result["Employee"][0], {"fieldname": "x", "fieldtype": ""})

    def test_values_needing_escaping_round_trip(self):
        """Property setter and depends_on values carry quotes, JSON and eval:."""
        tricky = 'eval:doc.custom_hiring_method !="A la carte" && doc.x == "y\\z"'
        _, result = self._emitted(records=[
            {"fieldname": "f", "fieldtype": "Data", "depends_on": tricky}
        ])
        self.assertEqual(result["Employee"][0]["depends_on"], tricky)

    def test_matches_the_shape_of_a_hand_written_module(self):
        """The real one_fm module is the reference for what this must look like."""
        scope = {}
        exec(compile(_source("one_fm/custom/custom_field/interview.py"), "<real>", "exec"), scope)
        real = scope["get_interview_custom_fields"]()
        self.assertEqual(list(real), ["Interview"])
        # Same call shape, same top-level structure: dict keyed by doctype label.
        _, mine = self._emitted(dt="Interview", records=self.RECORDS)
        self.assertEqual(type(real), type(mine))
        self.assertEqual(type(real["Interview"]), type(mine["Interview"]))
        self.assertEqual(gen.getter_name("Interview", "custom_field"), "get_interview_custom_fields")


class TestPropertySetterModule(FrappeTestCase):
    RECORDS = [
        {
            "name": "ps1",
            "doctype_or_field": "DocField",
            "doc_type": "Interview",
            "field_name": "from_time",
            "property": "reqd",
            "property_type": "Check",
            "value": 0,
            "modified": "2026-01-01 00:00:00",
        },
        {
            "name": "ps2",
            "doctype_or_field": "DocType",
            "doc_type": "Interview",
            "field_name": None,
            "property": "field_order",
            "property_type": "Data",
            "value": '["a", "b"]',
        },
    ]

    def _emitted(self):
        src = gen.render_property_setter_module("Interview", self.RECORDS)
        scope = {}
        exec(compile(src, "<generated>", "exec"), scope)
        return src, scope["get_interview_properties"]()

    def test_emits_exactly_the_keys_add_property_setter_consumes(self):
        """one_fm's add_property_setter (setup/setup.py) reads these six and
        nothing else; an extra key is noise and a missing one breaks the call."""
        _, result = self._emitted()
        for rec in result:
            self.assertEqual(
                set(rec),
                {"doctype_or_field", "doc_type", "field_name", "property", "property_type", "value"},
            )

    def test_field_name_is_kept_even_when_absent(self):
        """Absent field_name means 'a property of the DocType itself' (field_order).
        add_property_setter branches on doctype_or_field, so both keys must exist."""
        _, result = self._emitted()
        doctype_level = [r for r in result if r["doctype_or_field"] == "DocType"]
        self.assertTrue(doctype_level)
        self.assertIn("field_name", doctype_level[0])
        self.assertIsNone(doctype_level[0]["field_name"])

    def test_field_order_property_is_carried(self):
        """Layout is in scope, and field_order is what makes it land."""
        _, result = self._emitted()
        self.assertIn("field_order", [r["property"] for r in result])

    def test_matches_the_hand_written_module_key_for_key(self):
        scope = {}
        exec(compile(_source("one_fm/custom/property_setter/interview.py"), "<real>", "exec"), scope)
        real = scope["get_interview_properties"]()
        _, mine = self._emitted()
        self.assertTrue(set(mine[0]).issubset(set(real[0]) | {"field_name"}))
        for rec in real:
            self.assertTrue(set(rec).issubset(set(mine[0])), f"real module key not emitted: {set(rec)}")


class TestAggregatorSplicing(FrappeTestCase):
    """Spliced against one_fm's real setup/ files, so a reshape there fails here."""

    def test_custom_field_aggregator_gains_import_and_call(self):
        text = _source("one_fm/setup/custom_field.py")
        out = gen.splice_aggregator(text, APP, "Department Weekly Review", "custom_field")
        self.assertIn(
            "from one_fm.custom.custom_field.department_weekly_review import "
            "get_department_weekly_review_custom_fields",
            out,
        )
        self.assertIn("\tcustom_fields.update(get_department_weekly_review_custom_fields())\n", out)

    def test_property_setter_aggregator_gains_import_and_call(self):
        text = _source("one_fm/setup/property_setter.py")
        out = gen.splice_aggregator(text, APP, "Department Weekly Review", "property_setter")
        self.assertIn(
            "from one_fm.custom.property_setter.department_weekly_review import "
            "get_department_weekly_review_properties",
            out,
        )
        self.assertIn("\tfield_properties.extend(get_department_weekly_review_properties())\n", out)

    def test_call_lands_before_the_return_not_after_it(self):
        """After the return it would never execute, and nothing would notice."""
        text = _source("one_fm/setup/custom_field.py")
        out = gen.splice_aggregator(text, APP, "Department Weekly Review", "custom_field")
        call = "custom_fields.update(get_department_weekly_review_custom_fields())"
        self.assertLess(out.index(call), out.rindex("return custom_fields"))

    def test_result_is_still_valid_python(self):
        import ast

        for kind in ("custom_field", "property_setter"):
            text = _source(f"one_fm/setup/{kind}.py")
            out = gen.splice_aggregator(text, APP, "Department Weekly Review", kind)
            ast.parse(out)

    def test_splicing_is_idempotent(self):
        """Syncing the same doctype twice must not duplicate the registration."""
        text = _source("one_fm/setup/custom_field.py")
        once = gen.splice_aggregator(text, APP, "Department Weekly Review", "custom_field")
        twice = gen.splice_aggregator(once, APP, "Department Weekly Review", "custom_field")
        self.assertEqual(once, twice)

    def test_already_registered_doctype_is_left_alone(self):
        """Interview is already in both aggregators; re-splicing changes nothing."""
        for kind in ("custom_field", "property_setter"):
            text = _source(f"one_fm/setup/{kind}.py")
            self.assertEqual(text, gen.splice_aggregator(text, APP, "Interview", kind))

    def test_missing_anchor_raises_rather_than_appending_blindly(self):
        with self.assertRaises(ValueError):
            gen.splice_aggregator("def build():\n\tpass\n", APP, "Employee", "custom_field")


class TestPatchGeneration(FrappeTestCase):
    def test_one_patch_per_sync_run_covers_every_doctype(self):
        src = gen.render_patch(APP, "My Map", ["Employee", "Interview"], "abc123")
        self.assertEqual(src.count("def execute():"), 1)
        for getter in (
            "get_employee_custom_fields",
            "get_interview_custom_fields",
            "get_employee_properties",
            "get_interview_properties",
        ):
            self.assertIn(getter, src)

    def test_patch_is_valid_python_and_imports_resolve(self):
        import ast

        src = gen.render_patch(APP, "My Map", ["Interview"], "abc123")
        ast.parse(src)
        # The two things the patch depends on must really exist with these names.
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields  # noqa: F401

        from one_fm.setup.setup import add_property_setter  # noqa: F401

        self.assertIn("create_custom_fields(get_interview_custom_fields(), update=True)", src)
        self.assertIn("add_property_setter(get_interview_properties())", src)

    def test_update_true_so_a_rerun_updates_instead_of_failing(self):
        src = gen.render_patch(APP, "My Map", ["Employee"], "abc123")
        self.assertIn("update=True", src)

    def test_patches_txt_entry_is_appended_once(self):
        text = _source("one_fm/patches.txt")
        once = gen.splice_patches_txt(text, APP, "My Map", "abc123", "2026-08-17", note="Processa sync")
        twice = gen.splice_patches_txt(once, APP, "My Map", "abc123", "2026-08-17", note="Processa sync")
        self.assertEqual(once, twice)
        self.assertIn("one_fm.patches.v15_0.processa_sync_my_map_abc123 #2026-08-17", once)

    def test_patch_module_path_matches_the_patches_txt_entry(self):
        """A mismatch means the entry names a module that is not there, and
        migrate fails on every site."""
        path = gen.patch_path(APP, "My Map", "abc123")
        entry = gen.splice_patches_txt("", APP, "My Map", "abc123", "2026-08-17").strip()
        dotted = entry.split()[0]
        self.assertEqual(path, dotted.replace(".", "/") + ".py")

    def test_entry_is_appended_at_the_end(self):
        text = _source("one_fm/patches.txt")
        out = gen.splice_patches_txt(text, APP, "My Map", "abc123", "2026-08-17")
        self.assertTrue(out.rstrip().endswith("processa_sync_my_map_abc123 #2026-08-17"))


class TestPathsResolveAgainstTheRealRepo(FrappeTestCase):
    """Every path the PR names must be a real path in the target repository.

    Both of the bugs this class exists to prevent shipped past unit tests that
    only ever compared strings to strings: the data-module paths carried the app
    name twice (``one_fm/one_fm/custom/...``, the on-disk bench layout rather than
    the repo-relative one), and the customizations JSON was placed under the
    DocType's OWNING module, which for a foreign DocType resolves outside the
    repo altogether (``../hrms/hrms/hr/custom/interview.json``).
    """

    def setUp(self):
        self.repo_root = os.path.dirname(frappe.get_app_path(APP))

    def _abs(self, rel: str) -> str:
        return os.path.normpath(os.path.join(self.repo_root, rel))

    def test_no_generated_path_escapes_the_repository(self):
        paths = [
            gen.module_path(APP, "Interview", "custom_field"),
            gen.module_path(APP, "Interview", "property_setter"),
            gen.customization_json_path(APP, "Interview"),
            gen.patch_path(APP, "My Map", "abc123"),
            gen.aggregator_path(APP, "custom_field"),
            gen.aggregator_path(APP, "property_setter"),
            gen.patches_txt_path(APP),
        ]
        for rel in paths:
            self.assertFalse(rel.startswith(".."), f"{rel} escapes the repo root")
            self.assertTrue(
                self._abs(rel).startswith(self.repo_root + os.sep),
                f"{rel} resolves outside {self.repo_root}",
            )

    def test_spliced_files_exist_on_disk(self):
        """These are read-modify-write, so they must already be present."""
        for rel in (
            gen.aggregator_path(APP, "custom_field"),
            gen.aggregator_path(APP, "property_setter"),
            gen.patches_txt_path(APP),
        ):
            self.assertTrue(os.path.isfile(self._abs(rel)), f"{rel} is not a file in the repo")

    def test_generated_files_land_in_directories_that_exist(self):
        """A new data module goes beside the hand-written ones, and the patch into
        the app's existing patch directory — not into a directory this invents."""
        for rel in (
            gen.module_path(APP, "Interview", "custom_field"),
            gen.module_path(APP, "Interview", "property_setter"),
            gen.patch_path(APP, "My Map", "abc123"),
            gen.customization_json_path(APP, "Interview"),
        ):
            parent = os.path.dirname(self._abs(rel))
            self.assertTrue(os.path.isdir(parent), f"{rel}: parent dir {parent} does not exist")

    def test_data_module_path_matches_where_the_hand_written_modules_live(self):
        """interview.py already exists; the generated path must be that path."""
        rel = gen.module_path(APP, "Interview", "custom_field")
        self.assertTrue(
            os.path.isfile(self._abs(rel)),
            f"{rel} should be the existing hand-written module's own path",
        )
        self.assertEqual(rel, "one_fm/custom/custom_field/interview.py")

    def test_module_path_is_importable_as_the_patch_imports_it(self):
        """The patch does `from one_fm.custom.custom_field.interview import ...`;
        the file path and that dotted name have to describe the same file."""
        rel = gen.module_path(APP, "Interview", "custom_field")
        dotted = rel[: -len(".py")].replace("/", ".")
        self.assertEqual(dotted, "one_fm.custom.custom_field.interview")
        __import__(dotted)

    def test_customization_json_sits_under_a_module_of_the_customization_app(self):
        """sync_customizations only walks <app>/<module>/custom/, and the module
        must belong to that app or the file is never read."""
        rel = gen.customization_json_path(APP, "Interview")
        parts = rel.split("/")
        self.assertEqual(parts[0], APP)
        self.assertIn(parts[1], frappe.local.app_modules.get(APP) or [])
        self.assertEqual(parts[2], "custom")
        self.assertEqual(parts[3], "interview.json")


class TestCustomizationJsonMerge(FrappeTestCase):
    EXISTING = json.dumps(
        {
            "doctype": "Employee",
            "sync_on_migrate": 1,
            "custom_fields": [
                {"fieldname": "keep_me", "fieldtype": "Data", "label": "Kept"},
                {"fieldname": "update_me", "fieldtype": "Data", "label": "Old"},
            ],
            "property_setters": [
                {"doctype_or_field": "DocField", "field_name": "x", "property": "reqd", "value": 0}
            ],
        }
    )

    def test_untouched_records_are_preserved(self):
        """The file carries every customization of the doctype, not just this
        sync's. Regenerating it from one snapshot would delete the rest."""
        incoming = {"doctype": "Employee", "custom_fields": [
            {"fieldname": "brand_new", "fieldtype": "Check"}], "property_setters": []}
        out = json.loads(gen.merge_customization_json(self.EXISTING, incoming))
        names = [f["fieldname"] for f in out["custom_fields"]]
        self.assertIn("keep_me", names)
        self.assertIn("update_me", names)
        self.assertIn("brand_new", names)

    def test_matching_record_is_updated_in_place(self):
        incoming = {"doctype": "Employee", "custom_fields": [
            {"fieldname": "update_me", "fieldtype": "Data", "label": "New"}], "property_setters": []}
        out = json.loads(gen.merge_customization_json(self.EXISTING, incoming))
        row = [f for f in out["custom_fields"] if f["fieldname"] == "update_me"][0]
        self.assertEqual(row["label"], "New")
        self.assertEqual(len([f for f in out["custom_fields"] if f["fieldname"] == "update_me"]), 1)

    def test_property_setters_match_on_the_identifying_triple_not_name(self):
        """Row names are per-site and differ between BA and Production, so
        matching on them would append a duplicate every sync."""
        incoming = {
            "doctype": "Employee",
            "custom_fields": [],
            "property_setters": [
                {"doctype_or_field": "DocField", "field_name": "x", "property": "reqd", "value": 1}
            ],
        }
        out = json.loads(gen.merge_customization_json(self.EXISTING, incoming))
        self.assertEqual(len(out["property_setters"]), 1)
        self.assertEqual(out["property_setters"][0]["value"], 1)

    def test_empty_existing_file_is_created_from_scratch(self):
        incoming = {"doctype": "Employee", "custom_fields": [{"fieldname": "a", "fieldtype": "Data"}],
                    "property_setters": []}
        out = json.loads(gen.merge_customization_json("", incoming))
        self.assertEqual(out["doctype"], "Employee")
        self.assertEqual(out["sync_on_migrate"], 1)

    def test_sync_on_migrate_always_set(self):
        out = json.loads(gen.merge_customization_json(
            json.dumps({"doctype": "Employee", "custom_fields": []}), {"doctype": "Employee"}))
        self.assertEqual(out["sync_on_migrate"], 1)

    def test_corrupt_existing_file_is_not_silently_overwritten(self):
        with self.assertRaises(ValueError):
            gen.merge_customization_json("{not json", {"doctype": "Employee"})
