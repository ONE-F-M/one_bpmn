# Copyright (c) 2026, one-fm and contributors
# Tests for the Service Task connector layer (serviceType="connector").

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.processa_connectors.manifest import get_operation_spec, load_manifests
from one_bpmn.processa_connectors.google.common import normalize_drive_id
from one_bpmn.processa_engine.dispatch.connector import dispatch_connector

_GD = "one_bpmn.processa_connectors.google.drive"


def _echo(params, ctx):
    """Handler for the throwaway test connector.

    Reached by its dotted path from the operation row — the same way every real
    Python operation is now resolved. There is no registry to register with.
    """
    return {"got": params, "td_title": ctx["task_data"].get("title")}


def _ensure_echo_connector():
    """A real configured connector, because that is the only kind there is."""
    if not frappe.db.exists("BPMN Connector", "test_echo"):
        frappe.get_doc({
            "doctype": "BPMN Connector",
            "connector_id": "test_echo",
            "label": "Test Echo",
            "enabled": 1,
            "execution_type": "Python Handler",
        }).insert(ignore_permissions=True)
    if not frappe.db.exists("BPMN Connector Operation", {"connector": "test_echo", "operation_id": "echo"}):
        op = frappe.get_doc({
            "doctype": "BPMN Connector Operation",
            "connector": "test_echo",
            "operation_id": "echo",
            "label": "Echo",
            "enabled": 1,
            "execution_type": "Python Handler",
            "handler_path": "one_bpmn.processa_connectors.tests.test_connector_dispatch._echo",
        })
        for name in ("a", "b"):
            op.append("fields", {"field_name": name, "field_type": "String", "expression": 1})
        op.insert(ignore_permissions=True)
    from one_bpmn.processa_connectors.manifest import clear_manifest_cache

    clear_manifest_cache()


def _instance():
    return SimpleNamespace(context_doctype="", context_docname="", name="T", initiated_by="Administrator")


class TestNormalizeDriveId(FrappeTestCase):
    def test_link_forms_and_bare_id(self):
        self.assertEqual(normalize_drive_id("https://docs.google.com/document/d/ABCDEFGHIJ123/edit"), "ABCDEFGHIJ123")
        self.assertEqual(normalize_drive_id("https://drive.google.com/open?id=ZYXWVUT98765"), "ZYXWVUT98765")
        self.assertEqual(normalize_drive_id("PlainBareId_123456"), "PlainBareId_123456")
        self.assertEqual(normalize_drive_id(""), "")


class TestManifestAndRegistry(FrappeTestCase):
    def test_only_the_operations_that_need_python_name_a_handler(self):
        """Everything an HTTP template can express is configuration now.

        What is left needs multipart upload, binary parsing, or several calls
        with reasoning in between.
        """
        from one_bpmn.processa_connectors.manifest import get_execution_spec, load_manifests

        manifest = next(m for m in load_manifests() if m["connectorId"] == "google_drive")
        python_ops = {
            op["value"]
            for op in manifest["operations"]
            if (get_execution_spec("google_drive", op["value"]) or frappe._dict()).handler_path
        }
        self.assertEqual(
            python_ops,
            {"downloadText", "createFile", "updateFileContent", "setPermissions", "revokePermissions"},
        )


    def test_every_manifest_operation_resolves_to_an_executor(self):
        """The real invariant: an operation must be runnable — by a configured
        HTTP request or by a named handler. There is no third way any more."""
        from one_bpmn.processa_connectors.manifest import get_execution_spec

        manifest = next(m for m in load_manifests() if m["connectorId"] == "google_drive")
        for op in manifest["operations"]:
            name = op["value"]
            spec = get_execution_spec("google_drive", name)
            self.assertIsNotNone(spec, f"{name} has no execution configuration")
            runnable = bool(
                (spec.execution_type == "HTTP Request" and spec.url_template) or spec.handler_path
            )
            self.assertTrue(runnable, f"manifest op {name} cannot be run by anything")
            self.assertIsNotNone(op.get("fields"))


    def test_permission_enums_match_drive_api(self):
        spec = get_operation_spec("google_drive", "setPermissions")
        roles = next(f for f in spec["fields"] if f["name"] == "role")["choices"]
        self.assertEqual({c["value"] for c in roles},
                         {"owner", "organizer", "fileOrganizer", "writer", "commenter", "reader"})


class TestDispatchConnector(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _ensure_echo_connector()

    def test_render_and_result_mapping(self):
        task = SimpleNamespace(data={"title": "Hello"})
        dispatch_connector(_instance(), task, {
            "connectorId": "test_echo", "operation": "echo", "resultVariable": "echo_out",
            "connectorParams": '{"a": "{{ task_data.title }}", "b": "plain"}',
        }, "t1")
        self.assertEqual(task.data["echo_out"]["got"]["a"], "Hello")
        self.assertEqual(task.data["echo_out"]["got"]["b"], "plain")

    def test_drive_create_file_output_mapped(self):
        task = SimpleNamespace(data={"title": "My SOP", "sop_markdown": "BODY"})
        with patch(f"{_GD}.create_file",
                   return_value={"id": "FILE_1", "name": "My SOP", "webViewLink": "http://drive/FILE_1"}) as cf:
            dispatch_connector(_instance(), task, {
                "connectorId": "google_drive", "operation": "createFile", "resultVariable": "drive_file",
                "connectorParams": ('{"folder": "https://drive.google.com/drive/folders/FOLDER_ABC123", '
                                    '"filename": "{{task_data.title}}", "content": "{{task_data.sop_markdown}}"}'),
            }, "t2")
        self.assertEqual(task.data["drive_file"]["id"], "FILE_1")
        # folder link normalized to id, and rendered inputs reached the function
        self.assertEqual(cf.call_args.kwargs["folder_id"], "FOLDER_ABC123")
        self.assertEqual(cf.call_args.kwargs["filename"], "My SOP")
        self.assertEqual(cf.call_args.kwargs["content"], "BODY")

    def test_drive_file_link_normalized_before_handler(self):
        task = SimpleNamespace(data={})
        with patch(f"{_GD}.download_file_text", side_effect=lambda file, mime_type=None: f"C:{file}") as dl:
            dispatch_connector(_instance(), task, {
                "connectorId": "google_drive", "operation": "downloadText", "resultVariable": "tpl",
                "connectorParams": '{"file": "https://docs.google.com/document/d/ABCDEFGHIJ123/edit"}',
            }, "t3")
        self.assertEqual(dl.call_args.args[0], "ABCDEFGHIJ123")
        self.assertEqual(task.data["tpl"]["text"], "C:ABCDEFGHIJ123")

    def test_fail_on_error_raises_for_unknown(self):
        with self.assertRaises(Exception):
            dispatch_connector(_instance(), SimpleNamespace(data={}),
                               {"connectorId": "nope", "operation": "x", "failOnError": "1"}, "t4")

    def test_unknown_connector_non_fatal_by_default(self):
        task = SimpleNamespace(data={})
        dispatch_connector(_instance(), task, {"connectorId": "nope", "operation": "x"}, "t5")
        # no exception, no result written
        self.assertNotIn("x", task.data)


_GDOCS = "one_bpmn.processa_connectors.google.docs"
_GSLIDES = "one_bpmn.processa_connectors.google.slides"


class TestDocsSlidesConnectors(FrappeTestCase):
    def test_only_the_multi_call_operations_name_a_handler(self):
        from one_bpmn.processa_connectors.manifest import get_execution_spec, load_manifests

        for connector_id, expected in (
            ("google_docs", {"appendText", "getText", "fillTemplate", "fillBrandedTemplate"}),
            ("google_slides", {"getText"}),
        ):
            manifest = next(m for m in load_manifests() if m["connectorId"] == connector_id)
            named = {
                op["value"]
                for op in manifest["operations"]
                if (get_execution_spec(connector_id, op["value"]) or frappe._dict()).handler_path
            }
            with self.subTest(connector=connector_id):
                self.assertEqual(named, expected)


    def test_sheets_needs_no_python_at_all(self):
        """Every Sheets operation is plain REST, so the module is gone."""
        from one_bpmn.processa_connectors.manifest import get_execution_spec, load_manifests

        manifest = next(m for m in load_manifests() if m["connectorId"] == "google_sheets")
        for op in manifest["operations"]:
            spec = get_execution_spec("google_sheets", op["value"])
            with self.subTest(operation=op["value"]):
                self.assertFalse(spec.handler_path, "Sheets must need no Python")



class TestManifestValidator(FrappeTestCase):
    def test_all_manifests_valid(self):
        from one_bpmn.processa_connectors.validator import validate_manifests
        issues = validate_manifests()
        self.assertEqual(issues, [], "manifest issues: " + "; ".join(issues))


class TestRetryAndChoices(FrappeTestCase):
    def test_call_with_retry_retries_transient(self):
        from one_bpmn.processa_connectors.retry import call_with_retry
        calls = {"n": 0}

        class _Err(Exception):
            resp = SimpleNamespace(status=503)

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise _Err()
            return "ok"

        self.assertEqual(call_with_retry(flaky, attempts=3, base_delay=0), "ok")
        self.assertEqual(calls["n"], 3)

    def test_call_with_retry_reraises_non_transient(self):
        from one_bpmn.processa_connectors.retry import call_with_retry

        class _Err(Exception):
            resp = SimpleNamespace(status=404)

        def boom():
            raise _Err()

        with self.assertRaises(_Err):
            call_with_retry(boom, attempts=3, base_delay=0)

    def test_field_choices_unconfigured_is_empty(self):
        """A field with no Choices From path yields [] rather than an error."""
        from one_bpmn.api.connectors import get_connector_field_choices
        self.assertEqual(get_connector_field_choices("google_drive", "createFile", "folder"), [])
        self.assertEqual(get_connector_field_choices("__nope__", "__nope__", "__nope__"), [])


class TestSheetsIsPureConfiguration(FrappeTestCase):
    """Sheets was the proof that a whole provider can be configuration.

    Its Python module is gone: every operation is a Jinja-templated REST call on
    its own row. These assert the templates, because there is nothing else left
    to assert — and a broken template is exactly what would otherwise reach
    Google as a malformed body.
    """

    def _spec(self, operation):
        from one_bpmn.processa_connectors.manifest import get_execution_spec

        spec = get_execution_spec("google_sheets", operation)
        self.assertIsNotNone(spec, f"{operation} has no execution configuration")
        self.assertEqual(spec.execution_type, "HTTP Request")
        return spec

    def test_every_sheets_operation_is_http(self):
        for op in ("createSpreadsheet", "getValues", "updateValues",
                   "appendValues", "clearValues", "addSheet"):
            with self.subTest(operation=op):
                self.assertTrue(self._spec(op).url_template)

    def test_create_spreadsheet_posts_to_drive_not_sheets(self):
        """sheets.create puts the file in the service account's own storage,
        which has no quota — it must go through Drive with a parent folder."""
        spec = self._spec("createSpreadsheet")
        self.assertTrue(spec.url_template.startswith("https://www.googleapis.com/drive/v3/files"))
        self.assertIn("vnd.google-apps.spreadsheet", spec.body_template)
        self.assertIn("parents", spec.body_template)

    def test_update_values_uses_bracket_access_for_the_values_field(self):
        """`values` shadows dict.values(), so params.values would render the
        METHOD into the body. This is the regression guard for that."""
        spec = self._spec("updateValues")
        self.assertIn('params["values"]', spec.body_template)
        self.assertNotIn("params.values", spec.body_template)

    def test_the_validator_catches_that_mistake(self):
        from one_bpmn.processa_connectors.validator import shadowed_field_access

        broken = frappe._dict(body_template='{"values": {{ params.values }}}',
                              url_template="x", query_params_json="", headers_json="")
        self.assertTrue(shadowed_field_access("google_sheets", "updateValues", broken))
        self.assertFalse(shadowed_field_access("google_sheets", "updateValues", self._spec("updateValues")))



class TestConnectorModuleMove(FrappeTestCase):
    """Stored paths follow the move into processa_connectors, and one lookup finds an operation."""

    OLD_HANDLER = "one_bpmn.one_bpmn.connectors.google_drive_ops.download_text"
    OLD_TRANSFORM = "one_bpmn.one_bpmn.integrations.google_common.normalize_drive_id"

    def setUp(self):
        _ensure_echo_connector()
        self.op = frappe.db.get_value(
            "BPMN Connector Operation", {"connector": "test_echo", "operation_id": "echo"}, "name"
        )

    def _store(self, handler_path, transform=None):
        frappe.db.set_value("BPMN Connector Operation", self.op, "handler_path", handler_path)
        if transform:
            field = frappe.db.get_value("BPMN Connector Field", {"parent": self.op, "field_name": "a"}, "name")
            frappe.db.set_value("BPMN Connector Field", field, "value_transform", transform)
        frappe.clear_document_cache("BPMN Connector Operation", self.op)

    def test_an_old_handler_path_fails_with_an_error_naming_it(self):
        from one_bpmn.processa_engine.dispatch.connector import _resolve_connector_handler

        self._store(self.OLD_HANDLER)
        with patch("frappe.log_error") as log_error:
            self.assertIsNone(_resolve_connector_handler("test_echo", "echo"))
        self.assertIn(self.OLD_HANDLER, log_error.call_args.kwargs["message"])

    def test_migrate_points_stored_paths_at_the_new_modules(self):
        from one_bpmn.one_bpmn.patches.v1_0 import repath_connector_handlers
        from one_bpmn.processa_connectors.manifest import field_transforms
        from one_bpmn.processa_connectors.operations import google_drive
        from one_bpmn.processa_engine.dispatch.connector import _resolve_connector_handler

        self._store(self.OLD_HANDLER, self.OLD_TRANSFORM)
        repath_connector_handlers.execute()

        self.assertIs(_resolve_connector_handler("test_echo", "echo"), google_drive.download_text)
        self.assertEqual(
            field_transforms("test_echo", "echo")["a"],
            "one_bpmn.processa_connectors.google.common.normalize_drive_id",
        )

    def test_an_operation_lookup_reuses_the_cached_map(self):
        get_operation_spec("test_echo", "echo")
        with patch("one_bpmn.processa_connectors.manifest.load_manifests", side_effect=AssertionError):
            self.assertEqual(get_operation_spec("test_echo", "echo")["value"], "echo")

    def test_the_drive_client_builds_through_the_common_credential_path(self):
        from one_bpmn.processa_connectors.google import drive

        with patch.object(drive.gc, "get_service") as get_service:
            drive._get_service()
        get_service.assert_called_once_with(
            "drive", "v3", scopes=[drive.gc.DRIVE_SCOPE], connector_id="google_drive"
        )
        with patch.object(drive.gc, "_connector_service_account", return_value=None):
            with self.assertRaises(drive.GoogleDriveConfigError):
                drive._get_service()

    def test_fetch_url_refuses_an_internal_host(self):
        from one_bpmn.processa_connectors.operations.http import fetch_url

        result = fetch_url("http://127.0.0.1/spec.json")
        self.assertFalse(result["ok"])
        self.assertIn("internal address", result["error"])
