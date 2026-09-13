"""A customization PR must go to a repository the organisation controls.

"Review Doctypes → Sync" grouped changed doctypes by the app that OWNS each
doctype and derived that app's git remote. On this bench those remotes are the
public upstream projects — ``frappe/erpnext``, ``frappe/hrms``,
``frappe/helpdesk`` — and every one of one_fm's 108 customization modules targets
a doctype owned by one of them. So the feature aimed 100% of real customization
PRs at a repository nobody here can merge into.

These tests pin the routing (customizations go to the configured app), the
exception (a doctype belonging to one of our own apps stays with that app), the
fallback (no configuration behaves as before), and the guard that refuses to open
a PR against an outside owner even if routing were wrong again.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_customization_pr_routing
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.production_review import (
    _allowed_repo_owners,
    _app_for_doctype,
    _customization_app_for_doctype,
    _customization_pr_files,
)

SETTINGS = "Processa Settings"


def _set_app(value):
    frappe.db.set_single_value(SETTINGS, "customization_app", value)
    frappe.clear_cache(doctype=SETTINGS)


class TestCustomizationRouting(FrappeTestCase):
    def setUp(self):
        self.previous = frappe.db.get_single_value(SETTINGS, "customization_app")
        _set_app("one_fm")

    def tearDown(self):
        _set_app(self.previous)

    def test_foreign_doctype_routes_to_the_configured_app(self):
        """The bug: Employee is erpnext's, but its Custom Fields are one_fm's."""
        if not frappe.db.exists("DocType", "Employee"):
            self.skipTest("Employee is not installed")
        self.assertNotEqual(_app_for_doctype("Employee"), "one_fm")
        self.assertEqual(_customization_app_for_doctype("Employee"), "one_fm")

    def test_every_app_one_fm_customises_routes_to_one_fm(self):
        for dt in ("Employee", "Interview", "HD Ticket", "Item", "Purchase Order"):
            if not frappe.db.exists("DocType", dt):
                continue
            self.assertEqual(
                _customization_app_for_doctype(dt), "one_fm", f"{dt} should route to one_fm"
            )

    def test_our_own_apps_doctype_stays_with_its_own_app(self):
        """one_bpmn's doctypes are customised in one_bpmn, not exported into
        one_fm — both repos are ours, so the owning app wins."""
        if not frappe.db.exists("DocType", "BPMN Process Instance"):
            self.skipTest("one_bpmn doctypes not installed")
        self.assertEqual(_app_for_doctype("BPMN Process Instance"), "one_bpmn")
        self.assertEqual(_customization_app_for_doctype("BPMN Process Instance"), "one_bpmn")

    def test_configured_app_owns_its_own_doctypes_too(self):
        if not frappe.db.exists("DocType", "Department Weekly Review"):
            self.skipTest("Department Weekly Review is not installed")
        self.assertEqual(_customization_app_for_doctype("Department Weekly Review"), "one_fm")

    def test_blank_configuration_falls_back_to_the_owning_app(self):
        """An existing site with the field unset must behave exactly as before,
        so installing this change cannot alter routing until it is configured."""
        _set_app("")
        if not frappe.db.exists("DocType", "Employee"):
            self.skipTest("Employee is not installed")
        self.assertEqual(_customization_app_for_doctype("Employee"), _app_for_doctype("Employee"))


class TestRepoOwnerGuard(FrappeTestCase):
    def setUp(self):
        self.previous = frappe.db.get_single_value(SETTINGS, "customization_app")
        _set_app("one_fm")

    def tearDown(self):
        _set_app(self.previous)

    def test_allowed_owner_is_derived_from_the_configured_app(self):
        owners = _allowed_repo_owners()
        self.assertTrue(owners, "an owner must be derived so the guard is active")
        self.assertNotIn("frappe", [o.lower() for o in owners])

    def test_guard_refuses_a_repository_outside_the_allowed_owner(self):
        """Belt and braces: even if routing regressed, nothing reaches an
        upstream project's pull request queue."""
        from one_bpmn.api.github_sync import open_customization_pr

        with self.assertRaises(frappe.ValidationError):
            open_customization_pr(
                token="dummy",
                repo="frappe/hrms",
                base_branch=None,
                head_branch="x",
                files={"a.txt": "b"},
                commit_message="m",
                pr_title="t",
                pr_body="b",
                allowed_owners=("ONE-F-M",),
            )

    def test_guard_allows_the_expected_owner(self):
        """Must fail for a reason other than the guard — proving it passed it.

        The token is fake, so the first real API call fails; what matters is that
        the refusal is not the "Unexpected Repository" one.
        """
        from one_bpmn.api.github_sync import open_customization_pr

        try:
            open_customization_pr(
                token="dummy-not-a-real-token",
                repo="ONE-F-M/one_fm",
                base_branch=None,
                head_branch="x",
                files={"a.txt": "b"},
                commit_message="m",
                pr_title="t",
                pr_body="b",
                allowed_owners=("ONE-F-M",),
            )
        except Exception as e:
            self.assertNotIn("Refusing to open a pull request", str(e))

    def test_no_allowed_owners_leaves_the_guard_inactive(self):
        """Passing none must not silently block every PR."""
        from one_bpmn.api.github_sync import open_customization_pr

        try:
            open_customization_pr(
                token="dummy", repo="anyone/anything", base_branch=None, head_branch="x",
                files={"a.txt": "b"}, commit_message="m", pr_title="t", pr_body="b",
            )
        except Exception as e:
            self.assertNotIn("Refusing to open a pull request", str(e))


class TestOwnerAppPatch(FrappeTestCase):
    """The field's `default` only applies to a Single that does not exist yet, so
    every already-installed site needs the patch to set it — the same
    fresh-install / existing-site split this whole feature is about."""

    def setUp(self):
        self.previous = frappe.db.get_single_value(SETTINGS, "customization_app")

    def tearDown(self):
        _set_app(self.previous)

    def test_patch_fills_a_blank_value(self):
        from one_bpmn.one_bpmn.patches.v1_0.set_customization_owner_app import execute

        _set_app("")
        execute()
        self.assertEqual(frappe.db.get_single_value(SETTINGS, "customization_app"), "one_fm")

    def test_patch_leaves_a_deliberate_choice_alone(self):
        from one_bpmn.one_bpmn.patches.v1_0.set_customization_owner_app import execute

        _set_app("one_bpmn")
        execute()
        self.assertEqual(frappe.db.get_single_value(SETTINGS, "customization_app"), "one_bpmn")

    def test_patch_does_not_probe_a_single_with_has_column(self):
        """Processa Settings is a Single: it has no table, so has_column RAISES
        TableMissingError instead of returning False. Under
        `bench migrate --skip-failing` that exception is swallowed and the patch
        is still logged as applied — it never runs again and the field stays
        blank. Verified live: that is exactly what happened before this changed.
        """
        with self.assertRaises(Exception):
            frappe.db.has_column("Processa Settings", "customization_app")
        self.assertTrue(frappe.get_meta(SETTINGS).has_field("customization_app"))

        import inspect

        from one_bpmn.one_bpmn.patches.v1_0 import set_customization_owner_app as mod

        source = inspect.getsource(mod.execute)
        # The call, not the substring: the docstring above explains why
        # has_column is wrong here, so it legitimately appears in a comment.
        self.assertNotIn("has_column(", source)
        self.assertIn("has_field(", source)

    def test_field_default_covers_the_fresh_install_path(self):
        self.assertEqual(frappe.get_meta(SETTINGS).get_field("customization_app").default, "one_fm")


class TestPrFileSet(FrappeTestCase):
    """The PR carries all four artefacts of the convention, not just the JSON."""

    def setUp(self):
        self.previous = frappe.db.get_single_value(SETTINGS, "customization_app")
        _set_app("one_fm")
        if not frappe.db.exists("DocType", "Interview"):
            self.skipTest("Interview is not installed")
        self.files, self.build_files, self.artefacts, self.routing = _customization_pr_files(
            "one_fm", ["Interview"], "Some Map", "abc123"
        )

    def tearDown(self):
        _set_app(self.previous)

    def test_data_modules_and_patch_are_written_whole(self):
        self.assertIn("one_fm/custom/custom_field/interview.py", self.files)
        self.assertIn("one_fm/custom/property_setter/interview.py", self.files)
        self.assertIn("one_fm/patches/v15_0/processa_sync_some_map_abc123.py", self.files)

    def test_shared_files_are_deferred_to_build_files_not_written_blind(self):
        """They are appended to, so they must be read off the branch first —
        writing them from ``files`` would replace the aggregator wholesale."""
        for shared in (
            "one_fm/setup/custom_field.py",
            "one_fm/setup/property_setter.py",
            "one_fm/patches.txt",
        ):
            self.assertNotIn(shared, self.files, f"{shared} must not be a blind whole-file write")
            self.assertIn(shared, self.artefacts)

    def test_customizations_json_is_still_part_of_the_pr(self):
        json_path = "one_fm/one_fm/custom/interview.json"
        self.assertIn(json_path, self.artefacts)
        self.assertNotIn(json_path, self.files, "must be merged with the existing file, not replaced")

    def test_every_artefact_is_inside_the_target_repo(self):
        for path in self.artefacts:
            self.assertFalse(path.startswith(".."), f"{path} escapes the repository")
            self.assertTrue(path.startswith("one_fm/"), f"{path} is not in the one_fm repo")

    def test_build_files_produces_the_shared_files_when_given_a_reader(self):
        import ast
        import json
        import os

        root = os.path.dirname(frappe.get_app_path("one_fm"))

        def reader(path):
            full = os.path.join(root, path)
            return open(full).read() if os.path.exists(full) else None

        out = self.build_files(reader)
        self.assertEqual(
            set(out),
            {
                "one_fm/setup/custom_field.py",
                "one_fm/setup/property_setter.py",
                "one_fm/patches.txt",
                "one_fm/one_fm/custom/interview.json",
            },
        )
        ast.parse(out["one_fm/setup/custom_field.py"])
        ast.parse(out["one_fm/setup/property_setter.py"])
        self.assertIn("processa_sync_some_map_abc123", out["one_fm/patches.txt"])
        merged = json.loads(out["one_fm/one_fm/custom/interview.json"])
        self.assertEqual(merged["doctype"], "Interview")
        self.assertEqual(merged["sync_on_migrate"], 1)

    def test_build_files_raises_when_an_aggregator_is_missing(self):
        """Better than pushing a getter nothing ever calls."""
        with self.assertRaises(ValueError):
            self.build_files(lambda path: None)

    def test_generated_modules_are_valid_python(self):
        import ast

        for path, content in self.files.items():
            ast.parse(content)
